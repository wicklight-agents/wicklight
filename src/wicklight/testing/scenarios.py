"""A tiny framework for safety scenario tests.

A scenario bundles an agent file, a FakeProvider script, and a seeded world;
running it returns a result with assertions over the trace and the world. It
lives here so plugin authors and the game can reuse it.

    Scenario(agent=..., script=..., world=...).run().assert_blocked(
        tool="send_email", by="permission"
    )
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from wicklight.agent import Agent
from wicklight.core import RunResult, ToolCheck
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import (
    Decision,
    LimitHit,
    PolicyChecked,
    ToolExecuted,
    TraceEvent,
    read_trace,
)


@dataclass
class ScenarioResult:
    """The outcome of a scenario, with chainable assertions."""

    result: RunResult
    world: MockWorld
    events: list[TraceEvent]

    def assert_completed(self) -> ScenarioResult:
        if not self.result.completed:
            raise AssertionError(
                f"expected the run to complete, got {self.result.status.value}"
            )
        return self

    def assert_stopped(self) -> ScenarioResult:
        if self.result.completed:
            raise AssertionError("expected the run to stop early, but it completed")
        return self

    def assert_ran(self, tool: str) -> ScenarioResult:
        if not any(
            isinstance(e, ToolExecuted) and e.payload.tool == tool and e.payload.ok
            for e in self.events
        ):
            raise AssertionError(f"expected tool {tool!r} to run, but it did not")
        return self

    def assert_not_ran(self, tool: str) -> ScenarioResult:
        if any(
            isinstance(e, ToolExecuted) and e.payload.tool == tool and e.payload.ok
            for e in self.events
        ):
            raise AssertionError(f"expected tool {tool!r} not to run, but it did")
        return self

    def assert_blocked(
        self, *, tool: str, by: str | None = None, reason: str | None = None
    ) -> ScenarioResult:
        denials = [
            e
            for e in self.events
            if isinstance(e, PolicyChecked)
            and e.payload.decision is Decision.DENY
            and e.payload.tool == tool
        ]
        if not denials:
            raise AssertionError(f"expected {tool!r} to be blocked, but it was not")
        if by is not None and not any(d.payload.policy == by for d in denials):
            got = ", ".join(d.payload.policy for d in denials)
            raise AssertionError(f"expected {tool!r} blocked by {by!r}, got: {got}")
        if reason is not None and not any(
            reason in (d.payload.reason or "") for d in denials
        ):
            raise AssertionError(f"expected a block reason containing {reason!r}")
        return self

    def assert_limit(self, limit: str | None = None) -> ScenarioResult:
        hits = [e for e in self.events if isinstance(e, LimitHit)]
        if not hits:
            raise AssertionError("expected a limit to be hit, but none was")
        if limit is not None and not any(h.payload.limit == limit for h in hits):
            got = ", ".join(h.payload.limit for h in hits)
            raise AssertionError(f"expected limit {limit!r}, got: {got}")
        return self


@dataclass
class Scenario:
    """An agent file, a fake script, and a seeded world, ready to run."""

    agent: str
    script: str
    world: str = ""
    task: str = "run the task"
    checks: Sequence[ToolCheck] = ()

    def run(self, *, runs_dir: str | Path | None = None) -> ScenarioResult:
        """Run the scenario and return its result (synchronously)."""
        run_dir = (
            Path(runs_dir)
            if runs_dir is not None
            else Path(tempfile.mkdtemp(prefix="wicklight-scenario-"))
        )
        agent_path = run_dir / "agent.md"
        agent_path.write_text(self.agent, encoding="utf-8")

        agent = Agent.load(agent_path)
        world = MockWorld.from_yaml(self.world) if self.world else MockWorld()
        provider = FakeProvider(FakeScript.from_yaml(self.script))
        result = agent.run(
            self.task,
            provider=provider,
            world=world,
            checks=self.checks,
            run_id="scenario",
            runs_dir=run_dir,
        )
        events = read_trace(result.trace_path).events if result.trace_path else []
        return ScenarioResult(result=result, world=world, events=events)
