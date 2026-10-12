"""The approval gate and the built-in test approvers (DTN-221)."""

from __future__ import annotations

from wicklight.testing import AutoApprove, AutoDeny, Scenario, ScriptedApprover
from wicklight.trace import ApprovalResolved

# make_payment is irreversible, so it requires approval by default.
PAY_AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools:\n  make_payment: irreversible\n---\nPay invoices.\n"
)
ONE_PAYMENT = (
    "responses:\n  - tool_calls:\n      - name: make_payment\n"
    '        arguments: { payee: "acme", amount_usd: 50 }\n  - text: done\n'
)
TWO_PAYMENTS = (
    "responses:\n"
    + (
        "  - tool_calls:\n      - name: make_payment\n"
        '        arguments: { payee: "acme", amount_usd: 50 }\n'
    )
    * 2
    + "  - text: done\n"
)


def test_auto_approve_lets_the_call_run() -> None:
    result = Scenario(agent=PAY_AGENT, script=ONE_PAYMENT, approver=AutoApprove()).run()
    result.assert_completed().assert_approved("make_payment").assert_ran("make_payment")
    assert len(result.world.ledger) == 1


def test_auto_deny_blocks_the_call() -> None:
    result = Scenario(
        agent=PAY_AGENT, script=ONE_PAYMENT, approver=AutoDeny("needs a human")
    ).run()
    result.assert_completed().assert_approval_denied("make_payment")
    result.assert_not_ran("make_payment")
    assert result.world.ledger == []  # nothing paid


def test_denial_note_reaches_the_model() -> None:
    result = Scenario(
        agent=PAY_AGENT, script=ONE_PAYMENT, approver=AutoDeny("needs a human")
    ).run()
    resolved = [
        e
        for e in result.events
        if isinstance(e, ApprovalResolved) and not e.payload.approved
    ]
    assert resolved and resolved[0].payload.note == "needs a human"


def test_scripted_approver_approves_then_denies() -> None:
    # First payment approved, second denied — the running order matters.
    result = Scenario(
        agent=PAY_AGENT, script=TWO_PAYMENTS, approver=ScriptedApprover([True, False])
    ).run()
    result.assert_approved("make_payment").assert_approval_denied("make_payment")
    assert len(result.world.ledger) == 1  # only the approved one went through


def test_no_approver_fails_closed() -> None:
    # No approver configured: an approval-required call is denied, not run.
    result = Scenario(agent=PAY_AGENT, script=ONE_PAYMENT).run()
    result.assert_completed().assert_approval_denied("make_payment")
    result.assert_not_ran("make_payment")


def test_resolved_event_records_who_and_how_long() -> None:
    result = Scenario(agent=PAY_AGENT, script=ONE_PAYMENT, approver=AutoApprove()).run()
    resolved = [e for e in result.events if isinstance(e, ApprovalResolved)]
    assert len(resolved) == 1
    payload = resolved[0].payload
    assert payload.by == "auto-approve"
    assert payload.approved is True
    assert payload.duration_ms is not None and payload.duration_ms >= 0


def test_explicit_approval_required_on_a_write_tool() -> None:
    # Approval is not only for irreversible tools: an explicit `approval: required`
    # on a write tool is gated too.
    agent = (
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools:\n  send_email: { level: write, approval: required }\n"
        "---\nReply.\n"
    )
    script = (
        "responses:\n  - tool_calls:\n      - name: send_email\n"
        '        arguments: { to: "amy@mycompany.com" }\n  - text: done\n'
    )
    result = Scenario(agent=agent, script=script, approver=AutoDeny()).run()
    result.assert_approval_denied("send_email").assert_not_ran("send_email")
