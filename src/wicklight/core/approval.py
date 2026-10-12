"""The approval gate: a human (or a stand-in) signs off before a risky call.

Approval is the final stage of the check pipeline — after permissions and
policies pass, a call that needs approval pauses the loop until an
:class:`Approver` decides. An approver is a pure decision maker: given an
:class:`ApprovalRequest` it returns :class:`Approved` or :class:`Denied`; it
cannot run tools or change arguments.

Built-in approvers cover tests and headless runs: :class:`AutoApprove`,
:class:`AutoDeny`, and :class:`ScriptedApprover`. :class:`TerminalApprover` is
the interactive one used by ``wicklight run``. When no approver is configured,
the gate fails closed (:data:`REQUIRE_APPROVER`): a call that needs approval is
denied rather than run unapproved.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class ApprovalError(Exception):
    """Raised for approver misuse (e.g. a scripted approver running dry)."""


def _empty_arguments() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class ApprovalRequest:
    """A tool call awaiting sign-off, with why approval is needed."""

    tool: str
    reason: str
    arguments: Mapping[str, Any] = field(default_factory=_empty_arguments)
    call_id: str | None = None
    #: The tool's declared risk (read/write/irreversible), for display.
    risk: str | None = None


@dataclass(frozen=True)
class Approved:
    """The call may proceed."""


@dataclass(frozen=True)
class Denied:
    """The call is refused, optionally with a note explaining why."""

    note: str = ""


#: An approver's verdict on a request.
ApprovalDecision = Approved | Denied


@runtime_checkable
class Approver(Protocol):
    """Decides whether a call that needs approval may proceed.

    ``name`` identifies who or what decided, for the ``approval_resolved`` event.
    ``request`` is async so interactive approvers (a terminal prompt, a webhook)
    fit the same interface as the instant test approvers.
    """

    @property
    def name(self) -> str: ...

    async def request(self, request: ApprovalRequest) -> ApprovalDecision: ...


class AutoApprove:
    """Approves everything. For tests and trusted headless runs only."""

    name = "auto-approve"

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        return Approved()


class AutoDeny:
    """Denies everything, with a fixed note."""

    name = "auto-deny"

    def __init__(self, note: str = "denied") -> None:
        self._note = note

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        return Denied(self._note)


class ScriptedApprover:
    """Replays a fixed sequence of decisions, one per request, in order.

    Each entry is a bool (``True`` approves). When the script runs out, the
    approver fails closed — further requests are denied — so a test that under-
    specifies its decisions blocks rather than silently approving.
    """

    name = "scripted"

    def __init__(self, decisions: Sequence[bool]) -> None:
        self._decisions = list(decisions)
        self._index = 0

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        if self._index >= len(self._decisions):
            return Denied("no scripted decision left")
        approve = self._decisions[self._index]
        self._index += 1
        return Approved() if approve else Denied("denied by script")


class _RequireApprover:
    """The fail-closed default: nothing is approved without a real approver."""

    name = "none"

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        return Denied("approval required but no approver is configured")


#: Used by the loop when no approver is supplied: deny approval-required calls.
REQUIRE_APPROVER: Approver = _RequireApprover()


class TerminalApprover:
    """The v1 human approver: a terminal prompt, default deny.

    Shows the tool, its arguments, risk, and why approval is needed, then asks
    ``Approve? [y/N]`` (default deny). A denial can carry an optional note back
    to the model. The prompt has a timeout that also defaults to deny, so an
    unattended run can't hang forever. A non-interactive run (no TTY) denies
    immediately and says why, rather than blocking on a prompt that can't appear.
    """

    name = "terminal"

    def __init__(
        self,
        *,
        timeout: float | None = 300.0,
        reader: Callable[[str], str] | None = None,
        interactive: bool | None = None,
    ) -> None:
        self._timeout = timeout
        self._reader = reader if reader is not None else input
        self._interactive = interactive

    def _is_interactive(self) -> bool:
        if self._interactive is not None:
            return self._interactive
        return sys.stdin.isatty() and sys.stdout.isatty()

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        if not self._is_interactive():
            return Denied(
                f"non-interactive run: cannot prompt to approve {request.tool!r}"
            )

        self._render(request)
        try:
            answer = await asyncio.wait_for(
                asyncio.to_thread(self._reader, "Approve? [y/N] "), self._timeout
            )
        except asyncio.TimeoutError:
            return Denied(f"approval timed out after {self._timeout:g}s")

        if answer.strip().lower() in {"y", "yes"}:
            return Approved()
        note = self._reader("Reason (optional): ").strip()
        return Denied(note or "denied at the terminal")

    def _render(self, request: ApprovalRequest) -> None:
        from rich.console import Console
        from rich.panel import Panel

        args = (
            json.dumps(dict(request.arguments), indent=2, default=str)
            if request.arguments
            else "(none)"
        )
        body = (
            f"tool: {request.tool}\n"
            f"risk: {request.risk or 'unknown'}\n"
            f"why:  {request.reason}\n"
            f"arguments:\n{args}"
        )
        Console().print(Panel(body, title="Approval required", border_style="yellow"))
