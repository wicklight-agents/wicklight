"""The interactive terminal approver (DTN-222).

The real approver reads from the terminal; these tests inject a fake reader and
an explicit interactivity flag so the approve/deny/timeout paths are exercised
without a real TTY.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence

from wicklight.core import ApprovalRequest, Approved, Denied, TerminalApprover

REQUEST = ApprovalRequest(
    tool="make_payment",
    reason="tool 'make_payment' is irreversible",
    arguments={"payee": "acme", "amount_usd": 50},
    risk="irreversible",
)


def _reader(answers: Sequence[str]) -> Callable[[str], str]:
    it = iter(answers)

    def read(_prompt: str) -> str:
        return next(it)

    return read


def test_non_interactive_denies_without_prompting() -> None:
    approver = TerminalApprover(interactive=False)
    decision = asyncio.run(approver.request(REQUEST))
    assert isinstance(decision, Denied)
    assert "non-interactive" in decision.note


def test_yes_approves() -> None:
    approver = TerminalApprover(interactive=True, reader=_reader(["y"]))
    assert isinstance(asyncio.run(approver.request(REQUEST)), Approved)


def test_default_empty_answer_denies() -> None:
    # Just pressing enter is a deny (the prompt is [y/N]).
    approver = TerminalApprover(interactive=True, reader=_reader(["", ""]))
    decision = asyncio.run(approver.request(REQUEST))
    assert isinstance(decision, Denied)
    assert decision.note == "denied at the terminal"


def test_deny_carries_the_note_back() -> None:
    approver = TerminalApprover(interactive=True, reader=_reader(["n", "too risky"]))
    decision = asyncio.run(approver.request(REQUEST))
    assert isinstance(decision, Denied)
    assert decision.note == "too risky"


def test_timeout_defaults_to_deny() -> None:
    def slow(_prompt: str) -> str:
        time.sleep(1.0)
        return "y"

    approver = TerminalApprover(interactive=True, reader=slow, timeout=0.05)
    decision = asyncio.run(approver.request(REQUEST))
    assert isinstance(decision, Denied)
    assert "timed out" in decision.note
