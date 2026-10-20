"""Trace event models — the typed vocabulary of a run.

Every action in a run is recorded as one event. Events share a small envelope
(``run_id``, ``step``, ``timestamp``, ``type``, ``payload``, ``explain``) and
carry a format version so the format can evolve. The envelope plus the typed
payloads form a discriminated union keyed on ``type``, so a reader gets the
right concrete event type back from a line of JSONL.

See ``docs/trace-events.md`` for a description and an ``explain`` example of
each event type.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

#: Trace format version, written on every event so each JSONL line is
#: self-describing. Bumped when the event schema changes incompatibly.
TRACE_FORMAT_VERSION = 1

_STRICT = ConfigDict(extra="forbid")


class Decision(str, Enum):
    """The outcome of a policy check."""

    ALLOW = "allow"
    DENY = "deny"


class RunStatus(str, Enum):
    """How a run ended."""

    COMPLETED = "completed"
    STOPPED = "stopped"
    LIMIT = "limit"
    ERROR = "error"


# --- Event payloads -----------------------------------------------------------


class _Payload(BaseModel):
    model_config = _STRICT


class RunStartedPayload(_Payload):
    agent: str
    agent_file: str | None = None
    # True for a dry run (DTN-240): tools are stubbed and never executed.
    dry_run: bool = False
    # True for a counterfactual replay against a changed agent file (DTN-238):
    # recorded model decisions re-checked under new rules, nothing executed.
    counterfactual: bool = False


class ContextBuiltPayload(_Payload):
    message_count: int
    # Indices of the messages that are untrusted (tool results and the model's
    # own turns). Recorded so `explain` (M9) can show which spans are data.
    untrusted: list[int] = []
    # Content-addressed reference to the full context, stored once in the blob
    # store (DTN-200) to keep the trace small and readable.
    content_ref: str | None = None


class ModelRoutedPayload(_Payload):
    model: str
    matched_rule: str | None = None
    # The agent-file line of the matching route, e.g. "agent.md line 6" (DTN-243).
    source: str | None = None
    # Models that matched but were excluded because the run is sensitive and they
    # aren't allowed for sensitive data (DTN-245).
    excluded: list[str] = []


class ModelCalledPayload(_Payload):
    model: str
    provider: str | None = None
    request_ref: str | None = None


class ModelRespondedPayload(_Payload):
    model: str
    finish_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    response_ref: str | None = None


class ToolProposedPayload(_Payload):
    tool: str
    call_id: str | None = None
    arguments: dict[str, Any] = {}


class PolicyCheckedPayload(_Payload):
    tool: str
    policy: str
    decision: Decision
    reason: str | None = None
    # Where the rule came from, e.g. "agent.md line 9".
    source: str | None = None


class ApprovalRequestedPayload(_Payload):
    tool: str
    call_id: str | None = None
    reason: str | None = None


class ApprovalResolvedPayload(_Payload):
    tool: str
    call_id: str | None = None
    approved: bool
    by: str | None = None
    note: str | None = None
    duration_ms: float | None = None
    # True when approval was waived by the agent file rather than granted by an
    # approver. The note carries the written waiver reason.
    waived: bool = False


class ToolExecutedPayload(_Payload):
    tool: str
    call_id: str | None = None
    ok: bool
    result_ref: str | None = None
    duration_ms: float | None = None
    # True when the tool was stubbed in a dry run (DTN-240): it passed every
    # check but was not actually executed.
    dry_run: bool = False
    # True when this result is sensitive and latched the run into sensitive mode
    # (DTN-245), restricting the rest of the run to sensitivity-allowed models.
    sensitive: bool = False


class LimitHitPayload(_Payload):
    limit: str
    limit_value: float | None = None
    observed: float | None = None


class ErrorPayload(_Payload):
    message: str
    where: str | None = None
    recoverable: bool = False
    # For provider errors (DTN-228): the neutral error kind, and — on a retry —
    # the attempt number and how long the core waited before retrying. A
    # terminal error may carry a suggested fix.
    kind: str | None = None
    attempt: int | None = None
    wait_seconds: float | None = None
    suggestion: str | None = None


class RunFinishedPayload(_Payload):
    status: RunStatus
    steps: int
    cost_usd: float | None = None


# --- Event envelope -----------------------------------------------------------


class _EventBase(BaseModel):
    model_config = _STRICT

    v: int = TRACE_FORMAT_VERSION
    run_id: str
    step: int
    timestamp: datetime
    explain: str


class RunStarted(_EventBase):
    type: Literal["run_started"] = "run_started"
    payload: RunStartedPayload


class ContextBuilt(_EventBase):
    type: Literal["context_built"] = "context_built"
    payload: ContextBuiltPayload


class ModelRouted(_EventBase):
    type: Literal["model_routed"] = "model_routed"
    payload: ModelRoutedPayload


class ModelCalled(_EventBase):
    type: Literal["model_called"] = "model_called"
    payload: ModelCalledPayload


class ModelResponded(_EventBase):
    type: Literal["model_responded"] = "model_responded"
    payload: ModelRespondedPayload


class ToolProposed(_EventBase):
    type: Literal["tool_proposed"] = "tool_proposed"
    payload: ToolProposedPayload


class PolicyChecked(_EventBase):
    type: Literal["policy_checked"] = "policy_checked"
    payload: PolicyCheckedPayload


class ApprovalRequested(_EventBase):
    type: Literal["approval_requested"] = "approval_requested"
    payload: ApprovalRequestedPayload


class ApprovalResolved(_EventBase):
    type: Literal["approval_resolved"] = "approval_resolved"
    payload: ApprovalResolvedPayload


class ToolExecuted(_EventBase):
    type: Literal["tool_executed"] = "tool_executed"
    payload: ToolExecutedPayload


class LimitHit(_EventBase):
    type: Literal["limit_hit"] = "limit_hit"
    payload: LimitHitPayload


class ErrorEvent(_EventBase):
    type: Literal["error"] = "error"
    payload: ErrorPayload


class RunFinished(_EventBase):
    type: Literal["run_finished"] = "run_finished"
    payload: RunFinishedPayload


#: The discriminated union of every event type, keyed on ``type``.
TraceEvent = Annotated[
    RunStarted
    | ContextBuilt
    | ModelRouted
    | ModelCalled
    | ModelResponded
    | ToolProposed
    | PolicyChecked
    | ApprovalRequested
    | ApprovalResolved
    | ToolExecuted
    | LimitHit
    | ErrorEvent
    | RunFinished,
    Field(discriminator="type"),
]

trace_event_adapter: TypeAdapter[TraceEvent] = TypeAdapter(TraceEvent)


def parse_trace_event(data: dict[str, Any]) -> TraceEvent:
    """Parse one event dict into its concrete type via the ``type`` discriminator."""
    return trace_event_adapter.validate_python(data)


def dump_trace_event(event: TraceEvent) -> dict[str, Any]:
    """Serialize an event to a JSON-ready dict (one JSONL line's worth)."""
    return trace_event_adapter.dump_python(event, mode="json")
