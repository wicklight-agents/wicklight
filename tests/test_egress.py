"""Egress allowlist derivation and the CONNECT proxy (DTN-254)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel
from typer.testing import CliRunner

from wicklight.agentfile import build_effective_config, parse_and_validate
from wicklight.cli import app
from wicklight.contracts import (
    ProviderRegistry,
    ToolRegistry,
    ToolResult,
    ToolRisk,
    tool,
)
from wicklight.deploy import (
    DeniedConnection,
    EgressProxy,
    derive_allowlist,
    host_allowed,
    parse_and_validate_deploy,
    trace_deny_writer,
)
from wicklight.trace import read_trace

runner = CliRunner()


class _NoArgs(BaseModel):
    pass


@tool(risk=ToolRisk.WRITE, network_hosts=["hooks.example.com"], sensitive=False)
async def notify(_inp: _NoArgs, _ctx: object) -> ToolResult:
    return ToolResult.success("ok")


# --- allowlist derivation -----------------------------------------------------


def _effective_agent(text: str):
    agent, config = parse_and_validate(text)
    return build_effective_config(config, provided=agent.frontmatter)


def test_allowlist_unions_providers_tools_and_extras() -> None:
    deploy = parse_and_validate_deploy(
        "name: d\nagent: a.md\negress:\n  extra_hosts: [events.example.com]\n"
    )[1]
    agent = _effective_agent(
        "---\nname: t\nmodels: { default: anthropic/claude, fallback: [openai/gpt] }\n"
        "tools: { notify: write }\n---\nx\n"
    )
    allow = derive_allowlist(
        deploy,
        agent,
        provider_registry=ProviderRegistry.discover(),
        tool_registry=ToolRegistry({"notify": notify}),
    )
    by_host = {entry.host: entry.source for entry in allow}
    assert by_host["api.anthropic.com"] == "provider:anthropic"
    assert by_host["api.openai.com"] == "provider:openai"
    assert by_host["hooks.example.com"] == "tool:notify"
    assert by_host["events.example.com"] == "extra_hosts"


def test_off_tools_and_uninstalled_are_skipped() -> None:
    deploy = parse_and_validate_deploy("name: d\nagent: a.md\n")[1]
    agent = _effective_agent(
        "---\nname: t\nmodels: { default: anthropic/claude }\n"
        "tools: { notify: off, ghost: read }\n---\nx\n"
    )
    allow = derive_allowlist(
        deploy,
        agent,
        provider_registry=ProviderRegistry.discover(),
        tool_registry=ToolRegistry({"notify": notify}),
    )
    hosts = {entry.host for entry in allow}
    assert "hooks.example.com" not in hosts  # notify is off
    assert hosts == {"api.anthropic.com"}


def test_host_allowed() -> None:
    assert host_allowed("api.openai.com", ["api.openai.com"])
    assert not host_allowed("evil.example", ["api.openai.com"])


def test_cli_check_shows_the_allowlist() -> None:
    result = runner.invoke(app, ["check", "examples/deploy.yaml"])
    assert result.exit_code == 0
    assert "egress allowlist:" in result.stdout
    assert "api.anthropic.com (provider:anthropic)" in result.stdout
    assert "every other host is refused and logged" in result.stdout


# --- the proxy ----------------------------------------------------------------


async def _echo_server() -> tuple[asyncio.AbstractServer, int]:
    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        data = await reader.read(100)
        writer.write(data)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def _request(
    proxy_port: int, target: str
) -> tuple[bytes, asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection("127.0.0.1", proxy_port)
    writer.write(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
    await writer.drain()
    response = await reader.readuntil(b"\r\n\r\n")
    return response, reader, writer


def test_allowed_host_tunnels_through() -> None:
    async def run() -> tuple[bytes, bytes]:
        echo, echo_port = await _echo_server()
        proxy = EgressProxy({"127.0.0.1"})
        proxy_port = await proxy.start(port=0)
        try:
            response, reader, writer = await _request(
                proxy_port, f"127.0.0.1:{echo_port}"
            )
            writer.write(b"ping")
            await writer.drain()
            echoed = await reader.read(4)
            writer.close()
            return response, echoed
        finally:
            await proxy.stop()
            echo.close()
            await echo.wait_closed()

    response, echoed = asyncio.run(run())
    assert b"200" in response
    assert echoed == b"ping"  # bytes flowed through, no interception


def test_denied_host_is_refused_and_recorded(tmp_path: Path) -> None:
    trace_path = tmp_path / "egress.jsonl"
    denied: list[DeniedConnection] = []

    async def run() -> bytes:
        def on_deny(d: DeniedConnection) -> None:
            denied.append(d)
            trace_deny_writer(trace_path)(d)

        proxy = EgressProxy({"api.anthropic.com"}, on_deny=on_deny)
        proxy_port = await proxy.start(port=0)
        try:
            response, _reader, writer = await _request(proxy_port, "evil.example:443")
            writer.close()
            return response
        finally:
            await proxy.stop()

    response = asyncio.run(run())
    assert b"403" in response
    assert denied and denied[0].host == "evil.example" and denied[0].port == 443

    # The refusal was recorded as a parseable egress_denied trace event.
    events = read_trace(trace_path).events
    assert len(events) == 1
    assert events[0].type == "egress_denied"
    assert events[0].payload.host == "evil.example"
    assert "evil.example" in events[0].explain
