"""The fixed agent loop and safety enforcement.

The loop, permission checks, untrusted-content tagging, the approval gate,
limits, and trace writing live here and cannot be replaced by a plugin. This
is the only place tool calls happen, so safety checks can never be skipped.
"""

from __future__ import annotations

from wicklight.core.approval import (
    REQUIRE_APPROVER,
    ApprovalDecision,
    ApprovalError,
    ApprovalRequest,
    Approved,
    Approver,
    AutoApprove,
    AutoDeny,
    Denied,
    ScriptedApprover,
    TerminalApprover,
)
from wicklight.core.loop import (
    CheckOutcome,
    ConfiguredPolicy,
    ProposedCall,
    RunResult,
    ToolCheck,
    TraceLog,
    run_agent,
)

__all__ = [
    "REQUIRE_APPROVER",
    "ApprovalDecision",
    "ApprovalError",
    "ApprovalRequest",
    "Approved",
    "Approver",
    "AutoApprove",
    "AutoDeny",
    "CheckOutcome",
    "ConfiguredPolicy",
    "Denied",
    "ProposedCall",
    "RunResult",
    "ScriptedApprover",
    "TerminalApprover",
    "ToolCheck",
    "TraceLog",
    "run_agent",
]
