"""The curated example agents (DTN-260).

Every example passes ``wicklight check``, and every example runs on the fake
provider — no key, no network — with its safety lesson visible in the trace.
These guard the examples as a release-quality catalog; the injection and routing
scenarios also have their own dedicated tests.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from wicklight.agent import Agent
from wicklight.agentfile import check_agent_path
from wicklight.core import AutoApprove
from wicklight.deploy import parse_and_validate_deploy
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

EXAMPLES = Path(__file__).parent.parent / "examples"


# --- every example passes check -----------------------------------------------


@pytest.mark.parametrize(
    "name", ["inbox", "files", "payments", "routed", "inbox_local"]
)
def test_example_agent_passes_check(name: str) -> None:
    config = check_agent_path(EXAMPLES / f"{name}.md")
    assert config.name


def test_deploy_example_passes_check() -> None:
    text = (EXAMPLES / "deploy.yaml").read_text(encoding="utf-8")
    _file, config = parse_and_validate_deploy(text, filename="deploy.yaml")
    assert config.name == "inbox-summarizer"
    # Its referenced agent file is valid too.
    assert check_agent_path(EXAMPLES / config.agent).name


# --- every example runs on the fake provider, lesson visible ------------------


def _run(agent_name: str, script: str, world: str, tmp_path: Path):
    """Run an example on the fake provider, binding it to every routed model."""
    agent = Agent.load(EXAMPLES / f"{agent_name}.md")
    fake = FakeProvider(FakeScript.from_path(EXAMPLES / "scripts" / script))
    result = agent.run(
        "do the task",
        providers=dict.fromkeys(agent.model_ids, fake),
        world=MockWorld.from_yaml((EXAMPLES / "worlds" / world).read_text()),
        approver=AutoApprove(),  # isolate the lesson from the approval prompt
        run_id="ex",
        runs_dir=tmp_path,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _denied(events: list[TraceEvent], policy: str) -> bool:
    return any(
        e.type == "policy_checked"
        and e.payload.decision.value == "deny"
        and e.payload.policy == policy
        for e in events
    )


def _routed_to(events: list[TraceEvent], model: str) -> bool:
    return any(e.type == "model_routed" and e.payload.model == model for e in events)


# (agent, script, world, lesson assertion)
_CASES: list[tuple[str, str, str, str, Callable[[list[TraceEvent]], bool]]] = [
    (
        "inbox-injection",
        "inbox",
        "injection.yaml",
        "injection.yaml",
        lambda ev: _denied(ev, "email_only_to"),  # the attacker send is blocked
    ),
    (
        "payments-spend-limit",
        "payments",
        "pay_over_limit.yaml",
        "invoice.yaml",
        lambda ev: _denied(ev, "spend_limit"),  # the over-cap payment is denied
    ),
    (
        "files-path-allowlist",
        "files",
        "read_files.yaml",
        "files.yaml",
        lambda ev: _denied(ev, "paths_within"),  # the out-of-folder read is blocked
    ),
    (
        "routed-sensitive-local",
        "routed",
        "routed.yaml",
        "routed.yaml",
        lambda ev: _routed_to(ev, "local/llama3.1"),  # sensitive -> local model
    ),
]


@pytest.mark.parametrize(
    ("case_id", "agent", "script", "world", "lesson"),
    _CASES,
    ids=[c[0] for c in _CASES],
)
def test_example_runs_on_fake_and_shows_its_lesson(
    case_id: str,
    agent: str,
    script: str,
    world: str,
    lesson: Callable[[list[TraceEvent]], bool],
    tmp_path: Path,
) -> None:
    _result, events = _run(agent, script, world, tmp_path)
    assert any(e.type == "run_started" for e in events)
    assert lesson(events), f"{case_id}: expected lesson not visible in the trace"
