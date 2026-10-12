"""Irreversible-tool defaults and per-tool waivers (DTN-223)."""

from __future__ import annotations

import pytest

from wicklight.agentfile import AgentFileValidationError, parse_and_validate
from wicklight.testing import AutoDeny, Scenario
from wicklight.trace import ApprovalRequested, ApprovalResolved

ONE_PAYMENT = (
    "responses:\n  - tool_calls:\n      - name: make_payment\n"
    '        arguments: { payee: "acme", amount_usd: 50 }\n  - text: done\n'
)


def _agent(make_payment_spec: str) -> str:
    return (
        "---\nname: t\nmodels: { default: fake/x }\n"
        f"tools:\n  make_payment: {make_payment_spec}\n---\nPay invoices.\n"
    )


# --- the default: irreversible needs approval; a waiver lifts it --------------


def test_irreversible_without_a_waiver_cannot_run_unapproved() -> None:
    # No approver and no waiver: the irreversible call is denied, not run.
    result = Scenario(agent=_agent("irreversible"), script=ONE_PAYMENT).run()
    result.assert_approval_denied("make_payment").assert_not_ran("make_payment")
    assert result.world.ledger == []


def test_waived_call_runs_without_an_approver_and_is_marked() -> None:
    spec = '{ level: irreversible, waive_approval: true, reason: "trusted transfers" }'
    result = Scenario(agent=_agent(spec), script=ONE_PAYMENT).run()

    result.assert_completed().assert_ran("make_payment")
    assert len(result.world.ledger) == 1  # the waiver let it through

    # The waiver is recorded in the trace, with its reason, and no human asked.
    resolved = [e for e in result.events if isinstance(e, ApprovalResolved)]
    assert len(resolved) == 1
    assert resolved[0].payload.waived is True
    assert resolved[0].payload.note == "trusted transfers"
    assert resolved[0].payload.by == "waiver"
    assert not any(isinstance(e, ApprovalRequested) for e in result.events)


# --- a waiver must carry a reason; check rejects a reasonless one -------------


def test_waiver_without_a_reason_is_rejected() -> None:
    text = _agent("{ level: irreversible, waive_approval: true }")
    with pytest.raises(AgentFileValidationError) as excinfo:
        parse_and_validate(text)
    assert "reason" in str(excinfo.value)


# --- an explicit approval: required is gated regardless of a waiver -----------


def test_explicit_approval_required_beats_a_waiver() -> None:
    spec = (
        "{ level: irreversible, approval: required, "
        'waive_approval: true, reason: "ignored" }'
    )
    result = Scenario(agent=_agent(spec), script=ONE_PAYMENT, approver=AutoDeny()).run()
    # The explicit requirement wins: the call is gated and denied, not waived.
    result.assert_approval_denied("make_payment").assert_not_ran("make_payment")
    assert not any(
        isinstance(e, ApprovalResolved) and e.payload.waived for e in result.events
    )
