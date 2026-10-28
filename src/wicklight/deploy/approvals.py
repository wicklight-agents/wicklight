"""File-based approvals, so the host can resolve a deployed run's approvals.

A deployed run has no terminal. When it needs sign-off, :class:`FileApprover`
writes a request file into the shared control directory and waits for the host's
``wicklight approve`` to write a response; if none arrives before the timeout the
call is denied (fail closed). The control directory is a mounted volume, so both
sides see the same files.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from wicklight.core.approval import (
    ApprovalDecision,
    ApprovalRequest,
    Approved,
    Denied,
)

_POLL_SECONDS = 0.3


def approvals_dir(control_dir: str | Path) -> Path:
    """The directory where approval requests and responses live."""
    return Path(control_dir) / "approvals"


@dataclass(frozen=True)
class PendingApproval:
    """A deployed run's approval request awaiting a host decision."""

    call_id: str
    tool: str
    reason: str
    risk: str | None
    run_id: str | None
    requested_at: str


class FileApprover:
    """Approver that waits for a decision file from the host (DTN-257)."""

    name = "deployment"

    def __init__(
        self,
        control_dir: str | Path,
        *,
        run_id: str | None = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self._dir = approvals_dir(control_dir)
        self._run_id = run_id
        self._timeout = timeout_seconds

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        self._dir.mkdir(parents=True, exist_ok=True)
        call_id = request.call_id or uuid4().hex[:12]
        request_file = self._dir / f"{call_id}.request.json"
        response_file = self._dir / f"{call_id}.response.json"
        request_file.write_text(
            json.dumps(
                {
                    "call_id": call_id,
                    "tool": request.tool,
                    "reason": request.reason,
                    "risk": request.risk,
                    "run_id": self._run_id,
                    "requested_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            encoding="utf-8",
        )

        waited = 0.0
        try:
            while waited < self._timeout:
                if response_file.exists():
                    data = json.loads(response_file.read_text(encoding="utf-8"))
                    if data.get("approved"):
                        return Approved()
                    return Denied(str(data.get("note") or "denied by host"))
                await asyncio.sleep(_POLL_SECONDS)
                waited += _POLL_SECONDS
            return Denied("approval timed out")
        finally:
            request_file.unlink(missing_ok=True)
            response_file.unlink(missing_ok=True)


def pending_approvals(control_dir: str | Path) -> list[PendingApproval]:
    """Every request in the control dir that has no response yet (host side)."""
    directory = approvals_dir(control_dir)
    if not directory.is_dir():
        return []
    pending: list[PendingApproval] = []
    for request_file in sorted(directory.glob("*.request.json")):
        call_id = request_file.name.removesuffix(".request.json")
        if (directory / f"{call_id}.response.json").exists():
            continue
        data = json.loads(request_file.read_text(encoding="utf-8"))
        pending.append(
            PendingApproval(
                call_id=call_id,
                tool=str(data.get("tool", "")),
                reason=str(data.get("reason", "")),
                risk=data.get("risk"),
                run_id=data.get("run_id"),
                requested_at=str(data.get("requested_at", "")),
            )
        )
    return pending


def resolve_approval(
    control_dir: str | Path,
    call_id: str,
    *,
    approved: bool,
    note: str = "",
    by: str = "host",
) -> None:
    """Write the host's decision for ``call_id`` (host side)."""
    directory = approvals_dir(control_dir)
    (directory / f"{call_id}.response.json").write_text(
        json.dumps({"approved": approved, "note": note, "by": by}),
        encoding="utf-8",
    )
