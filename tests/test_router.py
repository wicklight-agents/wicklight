"""First-match router in the core loop, with routing events (DTN-243)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

# One response per provider so we can tell which model answered by its text.
PLAN = FakeScript.from_yaml("responses:\n  - text: from planner\n")
EXEC = FakeScript.from_yaml("responses:\n  - text: from executor\n")


def _run(agent_text: str, providers: dict[str, FakeProvider], *, task: str = "go"):
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-router-"))
    (run_dir / "agent.md").write_text(agent_text, encoding="utf-8")
    result = Agent.load(run_dir / "agent.md").run(
        task,
        providers=providers,
        world=MockWorld(),
        run_id="r",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _routed(events: list[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.type == "model_routed"]


# --- step-based routing -------------------------------------------------------


def test_step_route_picks_the_planning_model_on_the_first_call() -> None:
    # Planning model answers first; a second model would answer later steps, but
    # this agent finishes in one step (a plain text reply).
    agent = (
        "---\nname: t\nmodels:\n  default: exec/m\n"
        "  routes:\n    - when: { step: planning }\n      use: plan/m\n"
        "tools: {}\n---\nGo.\n"
    )
    result, events = _run(
        agent, {"exec/m": FakeProvider(EXEC), "plan/m": FakeProvider(PLAN)}
    )
    assert result.output == "from planner"  # the planning route won step 1
    routed = _routed(events)
    assert routed[0].payload.model == "plan/m"
    assert "rule 1 (step=planning)" in routed[0].payload.matched_rule
    assert routed[0].payload.source and "line" in routed[0].payload.source


def test_default_is_used_when_no_route_matches() -> None:
    agent = (
        "---\nname: t\nmodels:\n  default: exec/m\n"
        "  routes:\n    - when: { data: sensitive }\n      use: local/m\n"
        "tools: {}\n---\nGo.\n"
    )
    result, events = _run(
        agent, {"exec/m": FakeProvider(EXEC), "local/m": FakeProvider(PLAN)}
    )
    assert result.output == "from executor"  # data not sensitive -> default
    assert _routed(events)[0].payload.model == "exec/m"
    assert _routed(events)[0].payload.matched_rule == "default"


# --- context_tokens routing ---------------------------------------------------


def test_context_tokens_route_matches_on_a_large_context() -> None:
    # A tiny threshold so the ordinary context trips it.
    agent = (
        "---\nname: t\nmodels:\n  default: small/m\n"
        '  routes:\n    - when: { context_tokens: ">1" }\n      use: big/m\n'
        "tools: {}\n---\nThis instruction is comfortably longer than one token.\n"
    )
    result, events = _run(
        agent, {"small/m": FakeProvider(EXEC), "big/m": FakeProvider(PLAN)}
    )
    assert _routed(events)[0].payload.model == "big/m"
    assert result.output == "from planner"


# --- a missing routed provider fails clearly ----------------------------------


def test_missing_routed_provider_stops_with_an_error() -> None:
    agent = (
        "---\nname: t\nmodels:\n  default: exec/m\n"
        "  routes:\n    - when: { step: planning }\n      use: ghost/m\n"
        "tools: {}\n---\nGo.\n"
    )
    # Only the default provider is supplied; ghost/m is unresolved, so the call
    # (with no fallback to fall back to) stops the run with a clear error.
    result, events = _run(agent, {"exec/m": FakeProvider(EXEC)})
    assert result.stopped
    errors = [e for e in events if e.type == "error" and e.payload.where == "fallback"]
    assert errors and "ghost/m" in errors[-1].payload.message
