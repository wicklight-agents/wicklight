"""Tests for the trace event models (DTN-199)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from wicklight.trace import (
    TRACE_FORMAT_VERSION,
    ApprovalRequested,
    ApprovalRequestedPayload,
    ApprovalResolved,
    ApprovalResolvedPayload,
    ContextBuilt,
    ContextBuiltPayload,
    Decision,
    ErrorEvent,
    ErrorPayload,
    LimitHit,
    LimitHitPayload,
    ModelCalled,
    ModelCalledPayload,
    ModelResponded,
    ModelRespondedPayload,
    ModelRouted,
    ModelRoutedPayload,
    PolicyChecked,
    PolicyCheckedPayload,
    RunFinished,
    RunFinishedPayload,
    RunStarted,
    RunStartedPayload,
    RunStatus,
    ToolExecuted,
    ToolExecutedPayload,
    ToolProposed,
    ToolProposedPayload,
    TraceEvent,
    dump_trace_event,
    parse_trace_event,
)

TS = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
RUN = "run_abc123"


def _base(step: int, explain: str) -> dict[str, object]:
    return {"run_id": RUN, "step": step, "timestamp": TS, "explain": explain}


# One example of every event type, with a representative `explain` sentence.
EXAMPLES: list[TraceEvent] = [
    RunStarted(
        **_base(0, "run started for agent inbox-summarizer"),
        payload=RunStartedPayload(agent="inbox-summarizer", agent_file="inbox.md"),
    ),
    ContextBuilt(
        **_base(1, "built context with 4 messages"),
        payload=ContextBuiltPayload(message_count=4, content_ref="sha256:abc"),
    ),
    ModelRouted(
        **_base(1, "routed to anthropic/claude-opus by rule step=planning"),
        payload=ModelRoutedPayload(
            model="anthropic/claude-opus", matched_rule="step=planning"
        ),
    ),
    ModelCalled(
        **_base(1, "called anthropic/claude-opus"),
        payload=ModelCalledPayload(model="anthropic/claude-opus", provider="anthropic"),
    ),
    ModelResponded(
        **_base(1, "model responded (stop) using 1200 in / 80 out tokens"),
        payload=ModelRespondedPayload(
            model="anthropic/claude-opus",
            finish_reason="stop",
            input_tokens=1200,
            output_tokens=80,
            cost_usd=0.01,
        ),
    ),
    ToolProposed(
        **_base(2, "model proposed send_email"),
        payload=ToolProposedPayload(
            tool="send_email", call_id="call_1", arguments={"to": "a@b.com"}
        ),
    ),
    PolicyChecked(
        **_base(2, "blocked: send_email by policy email_only_to (inbox.md line 9)"),
        payload=PolicyCheckedPayload(
            tool="send_email",
            policy="email_only_to",
            decision=Decision.DENY,
            reason="recipient not allowed",
            source="inbox.md line 9",
        ),
    ),
    ApprovalRequested(
        **_base(2, "approval requested for send_email"),
        payload=ApprovalRequestedPayload(
            tool="send_email", call_id="call_1", reason="write action"
        ),
    ),
    ApprovalResolved(
        **_base(2, "approval granted for send_email by user"),
        payload=ApprovalResolvedPayload(
            tool="send_email", call_id="call_1", approved=True, by="user"
        ),
    ),
    ToolExecuted(
        **_base(3, "executed send_email in 42ms"),
        payload=ToolExecutedPayload(
            tool="send_email", call_id="call_1", ok=True, duration_ms=42.0
        ),
    ),
    LimitHit(
        **_base(20, "hit limit max_steps (20)"),
        payload=LimitHitPayload(limit="max_steps", limit_value=20, observed=20),
    ),
    ErrorEvent(
        **_base(3, "error: provider timeout while calling the model"),
        payload=ErrorPayload(message="provider timeout", where="model_called"),
    ),
    RunFinished(
        **_base(4, "run finished: completed in 4 steps"),
        payload=RunFinishedPayload(status=RunStatus.COMPLETED, steps=4, cost_usd=0.01),
    ),
]

ALL_TYPES = {
    "run_started",
    "context_built",
    "model_routed",
    "model_called",
    "model_responded",
    "tool_proposed",
    "policy_checked",
    "approval_requested",
    "approval_resolved",
    "tool_executed",
    "limit_hit",
    "error",
    "run_finished",
}


def test_every_event_type_has_an_example() -> None:
    assert {event.type for event in EXAMPLES} == ALL_TYPES


@pytest.mark.parametrize("event", EXAMPLES, ids=lambda e: e.type)
def test_event_round_trips_and_keeps_its_type(event: TraceEvent) -> None:
    dumped = dump_trace_event(event)
    # Common envelope fields are present, including the format version.
    assert dumped["v"] == TRACE_FORMAT_VERSION
    assert dumped["type"] == event.type
    envelope = {"v", "run_id", "step", "timestamp", "type", "payload", "explain"}
    assert set(dumped) >= envelope

    restored = parse_trace_event(dumped)
    assert type(restored) is type(event)  # discriminator yields the concrete type
    assert restored == event
    assert restored.explain


def test_unknown_event_type_is_rejected() -> None:
    bad = dump_trace_event(EXAMPLES[0]) | {"type": "not_a_real_event"}
    with pytest.raises(ValidationError):
        parse_trace_event(bad)


def test_extra_payload_key_is_rejected() -> None:
    bad = dump_trace_event(EXAMPLES[0])
    bad["payload"] = {**bad["payload"], "surprise": 1}
    with pytest.raises(ValidationError):
        parse_trace_event(bad)


def test_version_defaults_when_omitted() -> None:
    event = RunFinished(
        **_base(1, "done"),
        payload=RunFinishedPayload(status=RunStatus.STOPPED, steps=1),
    )
    assert event.v == TRACE_FORMAT_VERSION
