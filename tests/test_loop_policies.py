"""Policy evaluation in the core loop — allow, deny, order, fail-closed (DTN-217)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

from wicklight.agent import Agent
from wicklight.contracts import (
    ALLOW,
    EmptyConfig,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    deny,
)
from wicklight.core import AutoApprove, ConfiguredPolicy, RunResult
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import Decision, TraceEvent, read_trace

AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  send_email: write\n"
    "  make_payment: irreversible\n---\nDo the task.\n"
)
WORLD = "inbox:\n  - sender: a@b.com\n    subject: Hi\n"


def _run(
    script: str,
    policies: list[ConfiguredPolicy] | None,
    *,
    agent: str = AGENT,
) -> tuple[RunResult, MockWorld, list[TraceEvent]]:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-policy-"))
    (run_dir / "agent.md").write_text(agent, encoding="utf-8")
    loaded = Agent.load(run_dir / "agent.md")
    world = MockWorld.from_yaml(WORLD)
    provider = FakeProvider(FakeScript.from_yaml(script))
    result = loaded.run(
        "task",
        provider=provider,
        world=world,
        policies=policies,
        approver=AutoApprove(),  # focus these tests on policy behavior, not approval
        run_id="t",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, world, events


# --- test policies ------------------------------------------------------------


class _AllowAll:
    name: ClassVar[str] = "allow_all"
    config_model: ClassVar[type[EmptyConfig]] = EmptyConfig

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        return ALLOW


class _DenyTool:
    config_model: ClassVar[type[EmptyConfig]] = EmptyConfig

    def __init__(self, tool: str) -> None:
        self.name = f"deny_{tool}"
        self._tool = tool

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        if call.tool == self._tool:
            return deny(f"{call.tool} is not allowed here")
        return ALLOW


class _Crash:
    name: ClassVar[str] = "crasher"
    config_model: ClassVar[type[EmptyConfig]] = EmptyConfig

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        raise RuntimeError("boom")


_RUN_READ = "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: done\n"
_RUN_SEND = (
    "responses:\n  - tool_calls:\n      - name: send_email\n"
    '        arguments: { to: "x@y.com" }\n  - text: done\n'
)


def _policy_events(events: list[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.type == "policy_checked"]


# --- allow --------------------------------------------------------------------


def test_policy_allow_lets_the_tool_run() -> None:
    policies = [ConfiguredPolicy("allow_all", _AllowAll())]
    result, _, events = _run(_RUN_READ, policies)
    assert result.completed
    assert any(e.type == "tool_executed" and e.payload.ok for e in events)
    allows = [
        e
        for e in _policy_events(events)
        if e.payload.policy == "allow_all" and e.payload.decision is Decision.ALLOW
    ]
    assert allows, "expected an allow policy_checked event"


# --- deny + source citation ---------------------------------------------------


def test_policy_deny_blocks_and_cites_its_source() -> None:
    policies = [
        ConfiguredPolicy("deny_send_email", _DenyTool("send_email"), "agent.md line 7")
    ]
    result, world, events = _run(_RUN_SEND, policies)
    assert result.completed  # the run continues; the model is told it was blocked
    assert world.sent == []  # the tool never executed
    denies = [e for e in _policy_events(events) if e.payload.decision is Decision.DENY]
    assert len(denies) == 1
    deny_event = denies[0]
    assert deny_event.payload.policy == "deny_send_email"
    assert deny_event.payload.source == "agent.md line 7"
    assert "not allowed" in (deny_event.payload.reason or "")
    assert "(agent.md line 7)" in deny_event.explain


# --- multiple policies: order and short-circuit -------------------------------


def test_multiple_policies_run_in_order_and_stop_at_the_first_deny() -> None:
    policies = [
        ConfiguredPolicy("allow_all", _AllowAll()),
        ConfiguredPolicy("deny_send_email", _DenyTool("send_email")),
        ConfiguredPolicy("never_runs", _AllowAll()),
    ]
    _, world, events = _run(_RUN_SEND, policies)
    assert world.sent == []
    seen = [e.payload.policy for e in _policy_events(events)]
    # allow_all allowed, deny_send_email denied, never_runs never evaluated.
    assert seen == ["allow_all", "deny_send_email"]


# --- a crashing policy fails closed -------------------------------------------


def test_crashing_policy_fails_closed() -> None:
    policies = [ConfiguredPolicy("crasher", _Crash())]
    result, _, events = _run(_RUN_READ, policies)
    assert result.completed
    # The tool was blocked (never executed ok)...
    assert not any(e.type == "tool_executed" and e.payload.ok for e in events)
    # ...recorded both as an error and as a deny.
    assert any(e.type == "error" and "crasher" in e.explain for e in events)
    denies = [e for e in _policy_events(events) if e.payload.decision is Decision.DENY]
    assert denies and denies[0].payload.policy == "crasher"


# --- end to end: the spend_limit built-in catches split payments --------------

_THREE_PAYMENTS = (
    "responses:\n"
    + (
        "  - tool_calls:\n      - name: make_payment\n"
        '        arguments: { payee: "acme", amount_usd: 40 }\n'
    )
    * 3
    + "  - text: done\n"
)


def test_spend_limit_blocks_the_payment_that_crosses_the_run_cap() -> None:
    # Configured from the agent file so discovery + source citation are exercised.
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  make_payment: irreversible\n"
        "policies:\n  - spend_limit: { max_usd: 100 }\n---\nPay invoices.\n"
    )
    result, world, events = _run(_THREE_PAYMENTS, None, agent=agent)
    assert result.completed
    # $40 + $40 go through; the third ($40, total $120) is over the $100 run cap.
    assert [p.amount_usd for p in world.ledger] == [40.0, 40.0]
    denies = [e for e in _policy_events(events) if e.payload.decision is Decision.DENY]
    assert len(denies) == 1
    assert denies[0].payload.policy == "spend_limit"
    assert "per-run limit" in (denies[0].payload.reason or "")
