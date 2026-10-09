"""Tests for the core agent loop (DTN-211)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from wicklight.agentfile import build_effective_config, parse_and_validate
from wicklight.core import CheckOutcome, ProposedCall, RunResult, run_agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld, mock_tools
from wicklight.trace import RunStatus, TraceWriter, read_trace

AGENT = """\
---
name: inbox-summarizer
models:
  default: fake/demo
tools:
  read_inbox: read
  send_email: { level: write }
limits: { max_steps: 10 }
---
You summarize the inbox and reply.
"""

WORLD_SEED = """\
inbox:
  - sender: amy@mycompany.com
    subject: "Lunch?"
    body: "Are you free Friday?"
"""


def _config(agent_text: str = AGENT):
    agent, config = parse_and_validate(agent_text)
    return agent, build_effective_config(config, provided=agent.frontmatter)


def _run(
    script: str, world: MockWorld, tmp_path: Path, *, run_id="r", checks=()
) -> RunResult:
    agent, config = _config()
    provider = FakeProvider(FakeScript.from_yaml(script))
    with TraceWriter(run_id, root=tmp_path) as writer:
        return asyncio.run(
            run_agent(
                run_id=run_id,
                instructions=agent.body,
                task="summarize my inbox",
                config=config,
                provider=provider,
                tools=mock_tools(world),
                writer=writer,
                checks=checks,
            )
        )


# A three-step run: read the inbox, send a reply, then finish with a summary.
MULTISTEP = """\
responses:
  - text: "Let me read the inbox."
    tool_calls:
      - name: read_inbox
  - text: "I'll reply to Amy."
    tool_calls:
      - name: send_email
        arguments: { to: "amy@mycompany.com", subject: "Re: Lunch?", body: "Yes!" }
  - text: "Done: replied to 1 email."
"""


def test_multistep_run_completes_and_mutates_the_world(tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD_SEED)
    result = _run(MULTISTEP, world, tmp_path)

    assert result.status is RunStatus.COMPLETED
    assert result.output == "Done: replied to 1 email."
    assert result.steps == 3
    # The send_email tool actually ran against the world.
    assert len(world.sent) == 1
    assert world.sent[0].to == "amy@mycompany.com"


def test_multistep_run_produces_a_complete_valid_trace(tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD_SEED)
    _run(MULTISTEP, world, tmp_path)

    trace = read_trace(tmp_path / "r.jsonl")
    assert trace.issues == []
    types = [e.type for e in trace.events]
    assert types[0] == "run_started"
    assert types[-1] == "run_finished"
    assert [e.payload.tool for e in trace.by_type("tool_proposed")] == [  # type: ignore[attr-defined]
        "read_inbox",
        "send_email",
    ]
    executed = trace.by_type("tool_executed")
    assert all(e.payload.ok for e in executed)  # type: ignore[attr-defined]
    finished = trace.by_type("run_finished")[0]
    assert finished.payload.status.value == "completed"  # type: ignore[attr-defined]


def test_tool_failure_is_fed_back_not_fatal(tmp_path: Path) -> None:
    script = """\
responses:
  - tool_calls:
      - name: read_file
        arguments: { path: "./missing" }
  - text: "That file does not exist."
"""
    world = MockWorld.from_yaml(WORLD_SEED)
    result = _run(script, world, tmp_path)

    assert result.status is RunStatus.COMPLETED
    assert result.output == "That file does not exist."
    executed = read_trace(tmp_path / "r.jsonl").by_type("tool_executed")
    assert executed[0].payload.ok is False  # type: ignore[attr-defined]


def test_provider_error_stops_the_run_with_an_error_event(tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD_SEED)
    result = _run("responses:\n  - error: provider exploded\n", world, tmp_path)

    assert result.status is RunStatus.ERROR
    trace = read_trace(tmp_path / "r.jsonl")
    assert [e.type for e in trace.by_type("error")]  # an error event was recorded
    assert trace.by_type("run_finished")[0].payload.status.value == "error"  # type: ignore[attr-defined]


def test_step_limit_stops_the_run(tmp_path: Path) -> None:
    agent_text = AGENT.replace("max_steps: 10", "max_steps: 2")
    agent, config = parse_and_validate(agent_text)
    effective = build_effective_config(config, provided=agent.frontmatter)
    # A script that always calls a tool, so only the step limit can stop it.
    script = "responses:\n" + "".join(
        "  - tool_calls:\n      - name: read_inbox\n" for _ in range(5)
    )
    world = MockWorld.from_yaml(WORLD_SEED)
    with TraceWriter("r", root=tmp_path) as writer:
        result = asyncio.run(
            run_agent(
                run_id="r",
                instructions=agent.body,
                task="go",
                config=effective,
                provider=FakeProvider(FakeScript.from_yaml(script)),
                tools=mock_tools(world),
                writer=writer,
            )
        )
    assert result.status is RunStatus.LIMIT
    assert read_trace(tmp_path / "r.jsonl").by_type("limit_hit")


def test_check_pipeline_can_deny_a_tool_call(tmp_path: Path) -> None:
    async def deny_all(proposed: ProposedCall) -> CheckOutcome:
        return CheckOutcome(allowed=False, reason="not allowed in this test")

    script = """\
responses:
  - tool_calls:
      - name: send_email
        arguments: { to: "amy@mycompany.com" }
  - text: "ok, I won't send it."
"""
    world = MockWorld.from_yaml(WORLD_SEED)
    result = _run(script, world, tmp_path, checks=[deny_all])

    assert result.status is RunStatus.COMPLETED
    # The denied tool never ran: the world is unchanged.
    assert world.sent == []
