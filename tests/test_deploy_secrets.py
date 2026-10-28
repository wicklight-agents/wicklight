"""Runtime secrets held by the harness (DTN-255) and image inputs (DTN-253).

Host-side and in-process tests only (no container) — the Docker build + scan
tests live in test_deploy_image.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from wicklight.agent import Agent
from wicklight.contracts import ToolContext, ToolResult, ToolRisk, tool
from wicklight.deploy import (
    EngineError,
    MissingSecretsError,
    detect_engine,
    generate_containerfile,
    image_tag,
    parse_and_validate_deploy,
    resolve_secrets,
    secrets_for_tool,
)
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import read_trace

SECRET = "deploy-secret-abc123-not-key-shaped"  # exact-value redaction, not a pattern


# --- resolve_secrets: env/file, fail-fast ------------------------------------


def _config(text: str):
    return parse_and_validate_deploy(text)[1]


def test_resolve_env_and_file(tmp_path: Path) -> None:
    (tmp_path / "tok").write_text("file-value\n", encoding="utf-8")
    config = _config(
        "name: d\nagent: a.md\nsecrets:\n"
        "  E: { from: env }\n"
        "  F: { from: file, path: tok }\n"
    )
    resolved = resolve_secrets(config, base_dir=tmp_path, env={"E": "env-value"})
    assert resolved == {"E": "env-value", "F": "file-value"}  # trailing newline dropped


def test_missing_secrets_are_all_named_at_once(tmp_path: Path) -> None:
    config = _config(
        "name: d\nagent: a.md\nsecrets:\n"
        "  A: { from: env }\n"
        "  B: { from: env }\n"
        "  C: { from: file, path: nope }\n"
    )
    with pytest.raises(MissingSecretsError) as exc:
        resolve_secrets(config, base_dir=tmp_path, env={})
    assert set(exc.value.names) == {"A", "B", "C"}


def test_secrets_for_tool_filters_to_declared() -> None:
    assert secrets_for_tool({"A": "1", "B": "2"}, ["A"]) == {"A": "1"}
    assert secrets_for_tool({"A": "1"}, []) == {}


# --- the harness hands each tool only its declared secrets --------------------


class _NoArgs(BaseModel):
    pass


@tool(
    risk=ToolRisk.READ,
    network_hosts=[],
    sensitive=False,
    required_secrets=["API_TOKEN"],
)
async def uses_secret(_inp: _NoArgs, ctx: ToolContext) -> ToolResult:
    return ToolResult.success(f"secret seen: {ctx.secret('API_TOKEN')}")


@tool(risk=ToolRisk.READ, network_hosts=[], sensitive=False)
async def no_declaration(_inp: _NoArgs, ctx: ToolContext) -> ToolResult:
    # Did not declare the secret, so it must not be available.
    return ToolResult.success(f"secret seen: {ctx.secret('API_TOKEN')}")


@tool(
    risk=ToolRisk.READ,
    network_hosts=[],
    sensitive=False,
    required_secrets=["API_TOKEN"],
)
async def leaks_in_error(_inp: _NoArgs, ctx: ToolContext) -> ToolResult:
    raise RuntimeError(f"boom with {ctx.secret('API_TOKEN')}")


AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools:\n  uses_secret: read\n  no_declaration: read\n  leaks_in_error: read\n"
    "---\nGo.\n"
)
SCRIPT = (
    "responses:\n"
    "  - tool_calls:\n"
    "      - name: uses_secret\n"
    "      - name: no_declaration\n"
    "      - name: leaks_in_error\n"
    "  - text: done\n"
)


def _run_with_secret(tmp_path: Path):
    (tmp_path / "a.md").write_text(AGENT, encoding="utf-8")
    return Agent.load(tmp_path / "a.md").run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(SCRIPT)),
        tools={
            "uses_secret": uses_secret,
            "no_declaration": no_declaration,
            "leaks_in_error": leaks_in_error,
        },
        secrets={"API_TOKEN": SECRET},
        run_id="sec",
        runs_dir=tmp_path,
    )


def test_only_declaring_tools_receive_the_secret(tmp_path: Path) -> None:
    result = _run_with_secret(tmp_path)
    trace = read_trace(result.trace_path)
    ok = {
        e.payload.tool: e.payload.ok for e in trace.events if e.type == "tool_executed"
    }
    assert ok["uses_secret"] is True  # declared it → got it
    assert ok["no_declaration"] is False  # didn't declare → not available
    assert ok["leaks_in_error"] is False  # declared, but raised


def test_secret_value_never_reaches_a_trace_even_on_error(tmp_path: Path) -> None:
    result = _run_with_secret(tmp_path)
    run_dir = Path(result.trace_path).parent
    everything = "".join(
        path.read_text(encoding="utf-8")
        for path in run_dir.rglob("*")
        if path.is_file()
    )
    assert SECRET not in everything  # redacted from trace and every blob
    assert "REDACTED" in everything  # and the marker is present where it was


# --- image inputs (DTN-253, no container needed) ------------------------------


def test_image_tag_is_name_plus_content_hash() -> None:
    tag = image_tag("Inbox Summarizer", agent_text="a", deploy_text="b")
    name, _, digest = tag.partition(":")
    assert name == "wicklight-inbox-summarizer"
    assert len(digest) == 12
    # Stable for the same inputs, different when they change.
    assert tag == image_tag("Inbox Summarizer", agent_text="a", deploy_text="b")
    assert tag != image_tag("Inbox Summarizer", agent_text="a", deploy_text="c")


def test_generated_containerfile_is_hardened() -> None:
    containerfile = generate_containerfile(Path("examples/deploy.yaml"))
    assert "gcr.io/distroless/python3-debian12:nonroot" in containerfile
    assert "USER nonroot" in containerfile
    assert "wicklight.deploy.entry" in containerfile


def test_detect_engine_finds_docker_or_podman() -> None:
    # One of these should be present in dev/CI; a bogus preferred engine errors.
    assert detect_engine() in ("docker", "podman")
    with pytest.raises(EngineError):
        detect_engine("not-a-real-engine")
