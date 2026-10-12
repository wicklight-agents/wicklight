"""The payment-approval demo, end to end (DTN-224).

Exercises the real example files (examples/payments.md + the invoice world and
pay-invoice script) across the three approval paths — approved, denied, waived —
and confirms the spend_limit policy runs before the approval gate.
"""

from __future__ import annotations

from pathlib import Path

from wicklight.testing import AutoApprove, AutoDeny, Scenario
from wicklight.trace import ApprovalRequested, ApprovalResolved, Decision

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PAYMENTS = (EXAMPLES / "payments.md").read_text(encoding="utf-8")
PAY_INVOICE = (EXAMPLES / "scripts" / "pay_invoice.yaml").read_text(encoding="utf-8")
INVOICE = (EXAMPLES / "worlds" / "invoice.yaml").read_text(encoding="utf-8")


def _resolved(events: list) -> list[ApprovalResolved]:  # type: ignore[type-arg]
    return [e for e in events if isinstance(e, ApprovalResolved)]


def test_approved_payment_is_recorded() -> None:
    result = Scenario(
        agent=PAYMENTS, script=PAY_INVOICE, world=INVOICE, approver=AutoApprove()
    ).run()

    result.assert_completed().assert_approved("make_payment")
    result.assert_ran("make_payment")
    assert len(result.world.ledger) == 1
    payment = result.world.ledger[0]
    assert payment.payee == "Acme Corp"
    assert payment.amount_usd == 50.0


def test_denied_payment_leaves_the_ledger_untouched() -> None:
    result = Scenario(
        agent=PAYMENTS,
        script=PAY_INVOICE,
        world=INVOICE,
        approver=AutoDeny("needs the CFO"),
    ).run()

    result.assert_completed().assert_approval_denied("make_payment")
    result.assert_not_ran("make_payment")
    assert result.world.ledger == []  # nothing was paid
    assert _resolved(result.events)[0].payload.note == "needs the CFO"


def test_waived_payment_runs_without_a_prompt_and_is_marked() -> None:
    # A waiver only works when approval isn't explicitly required, so this uses a
    # tailored agent rather than payments.md (which sets approval: required).
    waived_agent = (
        "---\nname: payments-agent\nmodels: { default: fake/x }\n"
        "tools:\n  make_payment: "
        '{ level: irreversible, waive_approval: true, reason: "pre-approved vendor" }\n'
        "---\nPay approved invoices.\n"
    )
    result = Scenario(agent=waived_agent, script=PAY_INVOICE, world=INVOICE).run()

    result.assert_completed().assert_ran("make_payment")
    assert len(result.world.ledger) == 1
    resolved = _resolved(result.events)
    assert len(resolved) == 1
    assert resolved[0].payload.waived is True
    assert resolved[0].payload.note == "pre-approved vendor"
    # A waiver is not a prompt: no approval was ever requested.
    assert not any(isinstance(e, ApprovalRequested) for e in result.events)


def test_spend_limit_blocks_before_approval_is_requested() -> None:
    # $150 is over the $100 cap, so the policy denies it before the gate.
    over_limit = (
        "responses:\n  - tool_calls:\n      - name: make_payment\n"
        '        arguments: { payee: "Acme Corp", amount_usd: 150 }\n  - text: done\n'
    )
    result = Scenario(
        agent=PAYMENTS, script=over_limit, world=INVOICE, approver=AutoApprove()
    ).run()

    result.assert_completed().assert_not_ran("make_payment")
    assert result.world.ledger == []
    # The policy denied it, and the approval gate was never reached.
    policy_denies = [
        e
        for e in result.events
        if e.type == "policy_checked" and e.payload.decision is Decision.DENY
    ]
    assert policy_denies and policy_denies[0].payload.policy == "spend_limit"
    assert not any(isinstance(e, ApprovalRequested) for e in result.events)
