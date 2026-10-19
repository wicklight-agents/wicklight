"""`wicklight run --dry-run`: stub tools, show what would run (DTN-240)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
from wicklight.core import AutoApprove
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PAY_SCRIPT = (
    "responses:\n  - tool_calls:\n      - name: make_payment\n"
    '        arguments: { payee: "Acme", amount_usd: 50 }\n  - text: done\n'
)


def _dry_run_payment() -> tuple[MockWorld, list[TraceEvent], Path]:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-dry-"))
    agent = Agent.load(EXAMPLES / "payments.md")
    world = MockWorld()  # empty ledger
    result = agent.run(
        "pay the invoice",
        provider=FakeProvider(FakeScript.from_yaml(PAY_SCRIPT)),
        world=world,
        approver=AutoApprove(),  # a what-if: assume approval granted
        dry_run=True,
        run_id="dry",
        runs_dir=run_dir,
    )
    assert result.trace_path is not None
    return world, read_trace(result.trace_path).events, result.trace_path


# --- the done-when ------------------------------------------------------------


def test_dry_run_shows_would_be_payment_and_leaves_ledger_unchanged() -> None:
    world, events, _ = _dry_run_payment()

    # The payment passed its checks and was recorded as "would have run"...
    executed = [e for e in events if e.type == "tool_executed"]
    assert len(executed) == 1
    assert executed[0].payload.tool == "make_payment"
    assert executed[0].payload.dry_run is True
    assert "would have run" in executed[0].explain

    # ...its check results are visible...
    policy = [e for e in events if e.type == "policy_checked"]
    assert any(e.payload.policy == "spend_limit" for e in policy)

    # ...and nothing actually happened: the ledger is untouched.
    assert world.ledger == []


def test_run_is_marked_as_a_dry_run_in_the_trace() -> None:
    _, events, _ = _dry_run_payment()
    started = [e for e in events if e.type == "run_started"]
    assert started and started[0].payload.dry_run is True


# --- checks still block in a dry run ------------------------------------------


def test_policy_still_blocks_in_a_dry_run() -> None:
    # $150 is over the spend_limit; the policy must still block it, even though
    # nothing would execute anyway.
    over = (
        "responses:\n  - tool_calls:\n      - name: make_payment\n"
        '        arguments: { payee: "Acme", amount_usd: 150 }\n  - text: done\n'
    )
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-dry-block-"))
    agent = Agent.load(EXAMPLES / "payments.md")
    result = agent.run(
        "pay",
        provider=FakeProvider(FakeScript.from_yaml(over)),
        world=MockWorld(),
        approver=AutoApprove(),
        dry_run=True,
        run_id="dryblock",
        runs_dir=run_dir,
    )
    assert result.trace_path is not None
    events = read_trace(result.trace_path).events
    denied = [
        e for e in events if e.type == "policy_checked" and "blocked" in e.explain
    ]
    assert denied and denied[0].payload.policy == "spend_limit"
    # Nothing ran: no dry-run tool_executed either (it was blocked before that).
    assert not any(e.type == "tool_executed" and e.payload.dry_run for e in events)


def test_stub_result_lets_the_model_continue() -> None:
    # read_inbox is stubbed; the model gets the placeholder and still finishes.
    agent_text = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools: { read_inbox: read }\n---\nSummarize.\n"
    )
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-dry-stub-"))
    (run_dir / "agent.md").write_text(agent_text, encoding="utf-8")
    script = (
        "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: all done\n"
    )
    result = Agent.load(run_dir / "agent.md").run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(script)),
        world=MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n"),
        dry_run=True,
        run_id="drystub",
        runs_dir=run_dir,
    )
    assert result.completed
    assert result.output == "all done"
