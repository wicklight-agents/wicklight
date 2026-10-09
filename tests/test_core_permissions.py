"""Tests for permission checks and limits in the core (DTN-212)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from wicklight.agentfile import build_effective_config, parse_and_validate
from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    StopReason,
    ToolCall,
    Usage,
)
from wicklight.core import RunResult, run_agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld, mock_tools
from wicklight.trace import RunStatus, TraceWriter, read_trace

WORLD = 'files:\n  "./secret.txt": "classified"\ninbox:\n  - sender: a@b.com\n'


def _run(
    agent_text: str,
    script: str,
    world: MockWorld,
    tmp_path: Path,
    *,
    provider=None,
) -> RunResult:
    agent, config = parse_and_validate(agent_text)
    effective = build_effective_config(config, provided=agent.frontmatter)
    model = (
        provider if provider is not None else FakeProvider(FakeScript.from_yaml(script))
    )
    with TraceWriter("r", root=tmp_path) as writer:
        return asyncio.run(
            run_agent(
                run_id="r",
                instructions=agent.body,
                task="go",
                config=effective,
                provider=model,
                tools=mock_tools(world),
                writer=writer,
                agent_file=agent,
            )
        )


def _events(tmp_path: Path, event_type: str):
    return read_trace(tmp_path / "r.jsonl").by_type(event_type)


def test_permitted_call_runs(tmp_path: Path) -> None:
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\n---\nbody\n"
    )
    script = "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: done\n"
    result = _run(agent, script, MockWorld.from_yaml(WORLD), tmp_path)

    assert result.status is RunStatus.COMPLETED
    executed = _events(tmp_path, "tool_executed")
    assert executed and executed[0].payload.ok is True  # type: ignore[attr-defined]


def test_over_permission_call_is_blocked_with_its_reason(tmp_path: Path) -> None:
    # delete_file is irreversible, but only granted "read".
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  delete_file: read\n---\nbody\n"
    )
    script = (
        "responses:\n"
        "  - tool_calls:\n"
        "      - name: delete_file\n"
        '        arguments: { path: "./secret.txt" }\n'
        "  - text: understood\n"
    )
    world = MockWorld.from_yaml(WORLD)
    result = _run(agent, script, world, tmp_path)

    assert result.status is RunStatus.COMPLETED
    # The irreversible call never ran: the file is still there.
    assert "./secret.txt" in world.files
    # No tool actually executed.
    assert _events(tmp_path, "tool_executed") == []
    # A policy_checked deny explains why, citing the agent-file line.
    (denied,) = _events(tmp_path, "policy_checked")
    assert denied.payload.decision.value == "deny"  # type: ignore[attr-defined]
    assert "needs 'irreversible'" in denied.payload.reason  # type: ignore[attr-defined]
    assert "line" in (denied.payload.source or "")  # type: ignore[attr-defined]


def test_unlisted_tool_is_blocked(tmp_path: Path) -> None:
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\n---\nbody\n"
    )
    script = (
        "responses:\n"
        "  - tool_calls:\n"
        "      - name: send_email\n"
        '        arguments: { to: "x@y.com" }\n'
        "  - text: ok\n"
    )
    world = MockWorld.from_yaml(WORLD)
    result = _run(agent, script, world, tmp_path)

    assert result.status is RunStatus.COMPLETED
    assert world.sent == []
    (denied,) = _events(tmp_path, "policy_checked")
    assert "not listed" in denied.payload.reason  # type: ignore[attr-defined]


def test_runaway_script_stops_at_the_step_limit(tmp_path: Path) -> None:
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\nlimits: { max_steps: 2 }\n---\nbody\n"
    )
    script = "responses:\n" + "".join(
        "  - tool_calls:\n      - name: read_inbox\n" for _ in range(5)
    )
    result = _run(agent, script, MockWorld.from_yaml(WORLD), tmp_path)

    assert result.status is RunStatus.LIMIT
    (hit,) = _events(tmp_path, "limit_hit")
    assert hit.payload.limit == "max_steps"  # type: ignore[attr-defined]


class _CostlyProvider:
    """Reports a cost on every call and always wants another tool call."""

    contract_version = "1.0"
    capabilities = Capabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            tool_calls=[ToolCall(id="c", name="read_inbox")],
            stop_reason=StopReason.TOOL_USE,
            usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.6),
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        if False:  # pragma: no cover - not used in this test
            yield  # type: ignore[unreachable]


def test_max_cost_stops_the_run(tmp_path: Path) -> None:
    # Default max_cost is $1.00; two calls at $0.60 exceed it.
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\n---\nbody\n"
    )
    result = _run(
        agent, "", MockWorld.from_yaml(WORLD), tmp_path, provider=_CostlyProvider()
    )

    assert result.status is RunStatus.LIMIT
    (hit,) = _events(tmp_path, "limit_hit")
    assert hit.payload.limit == "max_cost"  # type: ignore[attr-defined]


def test_timeout_stops_the_run(tmp_path: Path) -> None:
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\nlimits: { timeout: 0 }\n---\nbody\n"
    )
    result = _run(
        agent,
        "responses:\n  - text: never reached\n",
        MockWorld.from_yaml(WORLD),
        tmp_path,
    )

    assert result.status is RunStatus.LIMIT
    (hit,) = _events(tmp_path, "limit_hit")
    assert hit.payload.limit == "timeout"  # type: ignore[attr-defined]
