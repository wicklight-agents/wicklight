"""Tests for the public Agent API (DTN-213)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wicklight import Agent, RunResult
from wicklight.agentfile import AgentFileValidationError
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import RunStatus, read_trace

AGENT_TEXT = """\
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

SCRIPT = """\
responses:
  - text: "Reading the inbox."
    tool_calls:
      - name: read_inbox
  - text: "Replying."
    tool_calls:
      - name: send_email
        arguments: { to: "amy@mycompany.com", subject: "Re", body: "Yes" }
  - text: "Done."
"""

WORLD = "inbox:\n  - sender: amy@mycompany.com\n    subject: Hi\n"


@pytest.fixture
def agent(tmp_path: Path) -> Agent:
    path = tmp_path / "agent.md"
    path.write_text(AGENT_TEXT, encoding="utf-8")
    return Agent.load(path)


def _fake() -> FakeProvider:
    return FakeProvider(FakeScript.from_yaml(SCRIPT))


def test_load_validates_and_exposes_name(agent: Agent) -> None:
    assert agent.name == "inbox-summarizer"


def test_load_raises_friendly_error_on_bad_file(tmp_path: Path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text("---\nname: x\n---\nbody\n", encoding="utf-8")  # missing models
    with pytest.raises(AgentFileValidationError):
        Agent.load(bad)


def _assert_scenario(result: RunResult, world: MockWorld) -> None:
    assert isinstance(result, RunResult)
    assert result.status is RunStatus.COMPLETED
    assert result.completed and not result.stopped
    assert result.output == "Done."
    assert world.sent and world.sent[0].to == "amy@mycompany.com"
    # The trace was written and is readable.
    assert result.trace_path is not None and result.trace_path.exists()
    assert read_trace(result.trace_path).by_type("run_finished")


def test_arun_runs_the_scenario(agent: Agent, tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD)
    result = asyncio.run(
        agent.arun("summarize", provider=_fake(), world=world, runs_dir=tmp_path)
    )
    _assert_scenario(result, world)


def test_run_sync_runs_the_same_scenario(agent: Agent, tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD)
    result = agent.run("summarize", provider=_fake(), world=world, runs_dir=tmp_path)
    _assert_scenario(result, world)


def test_run_works_inside_a_running_loop(agent: Agent, tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD)

    async def notebook_cell() -> RunResult:
        # Calling the *sync* run() while a loop is already running (as in a
        # notebook) must still work.
        return agent.run("summarize", provider=_fake(), world=world, runs_dir=tmp_path)

    result = asyncio.run(notebook_cell())
    _assert_scenario(result, world)


def test_tools_override_is_used(agent: Agent, tmp_path: Path) -> None:
    world = MockWorld.from_yaml(WORLD)
    from wicklight.tools import mock_tools

    result = agent.run(
        "summarize", provider=_fake(), tools=mock_tools(world), runs_dir=tmp_path
    )
    assert result.completed
    assert world.sent  # the overridden tools ran against the world
