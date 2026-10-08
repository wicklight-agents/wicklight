"""Tests for the neutral model types (DTN-204)."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from wicklight.contracts import (
    CONTRACT_VERSION,
    Message,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    Role,
    StopReason,
    StreamDone,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolDefinition,
    Usage,
    dump_model_event,
    parse_model_event,
)


def _round_trip(model: BaseModel) -> BaseModel:
    return type(model).model_validate(model.model_dump(mode="json"))


def test_message_defaults_to_trusted() -> None:
    msg = Message(role=Role.USER, content="hi")
    assert msg.trusted is True
    # A tool result carries untrusted external data.
    tool_msg = Message(
        role=Role.TOOL,
        content="42 rows",
        trusted=False,
        tool_call_id="c1",
        name="query",
    )
    assert tool_msg.trusted is False


def test_usage_total_tokens() -> None:
    usage = Usage(input_tokens=1200, output_tokens=80, cost_usd=0.01)
    assert usage.total_tokens == 1280


EXAMPLES: list[BaseModel] = [
    Message(role=Role.SYSTEM, content="You are helpful."),
    Message(role=Role.TOOL, content="result", trusted=False, tool_call_id="c1"),
    ToolDefinition(
        name="send_email",
        description="Send an email",
        parameters={"type": "object", "properties": {"to": {"type": "string"}}},
    ),
    ToolCall(id="c1", name="send_email", arguments={"to": "a@b.com"}),
    Usage(input_tokens=10, output_tokens=5, cost_usd=0.001),
    ModelRequest(
        model="anthropic/claude-sonnet",
        messages=[Message(role=Role.USER, content="hi")],
        tools=[ToolDefinition(name="t")],
        max_tokens=1024,
        temperature=0.2,
        stop=["\n\n"],
    ),
    ModelResponse(
        content="hello",
        tool_calls=[ToolCall(id="c1", name="t")],
        stop_reason=StopReason.TOOL_USE,
        usage=Usage(input_tokens=3, output_tokens=2),
    ),
]


@pytest.mark.parametrize("model", EXAMPLES, ids=lambda m: type(m).__name__)
def test_models_round_trip_to_json(model: BaseModel) -> None:
    assert _round_trip(model) == model


STREAM_EVENTS: list[ModelEvent] = [
    TextDelta(text="Hel"),
    ToolCallDelta(tool_call=ToolCall(id="c1", name="send_email")),
    StreamDone(
        stop_reason=StopReason.STOP, usage=Usage(input_tokens=3, output_tokens=2)
    ),
]


@pytest.mark.parametrize("event", STREAM_EVENTS, ids=lambda e: e.type)
def test_stream_events_round_trip_and_keep_type(event: ModelEvent) -> None:
    dumped = dump_model_event(event)
    restored = parse_model_event(dumped)
    assert type(restored) is type(event)
    assert restored == event


def test_unknown_stream_event_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_model_event({"type": "nope"})


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Message.model_validate({"role": "user", "content": "hi", "surprise": 1})


def test_contract_version_is_semver_like() -> None:
    assert CONTRACT_VERSION.count(".") >= 1
    assert all(part.isdigit() for part in CONTRACT_VERSION.split("."))
