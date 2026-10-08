"""Neutral model types owned by the harness, independent of any provider.

A provider plugin translates between one model API and these types; the harness
never speaks a vendor's wire format directly. Keeping the types neutral is what
lets an agent file run unchanged across providers, and what lets the trace
record model calls in one stable shape.

Every type is a Pydantic model that round-trips to JSON, so model requests and
responses can be stored in a trace. The types are part of the provider contract
(see :data:`wicklight.contracts.CONTRACT_VERSION`).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

_STRICT = ConfigDict(extra="forbid")


class Role(str, Enum):
    """Who authored a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(str, Enum):
    """Why the model stopped generating."""

    STOP = "stop"  # natural end of the turn
    TOOL_USE = "tool_use"  # the model wants to call one or more tools
    LENGTH = "length"  # hit the token limit
    ERROR = "error"  # the provider reported an error


class Message(BaseModel):
    """One message in a conversation.

    ``trusted`` marks whether the content is part of the harness's own
    instructions (trusted) or external data such as a tool result (untrusted).
    Untrusted content is never treated as instructions by the core.
    """

    model_config = _STRICT

    role: Role
    content: str = ""
    trusted: bool = True
    # For tool-result messages: which tool call this answers, and its name.
    tool_call_id: str | None = None
    name: str | None = None


class ToolDefinition(BaseModel):
    """A tool offered to the model: a name, a description, and an input schema."""

    model_config = _STRICT

    name: str
    description: str = ""
    # JSON Schema describing the tool's arguments.
    parameters: dict[str, Any] = {}


class ToolCall(BaseModel):
    """A tool invocation the model requested."""

    model_config = _STRICT

    id: str
    name: str
    arguments: dict[str, Any] = {}


class Usage(BaseModel):
    """Token counts and an optional cost estimate for a model call."""

    model_config = _STRICT

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class ModelRequest(BaseModel):
    """A neutral request to a model: messages, tools, and generation limits."""

    model_config = _STRICT

    model: str
    messages: list[Message]
    tools: list[ToolDefinition] = []
    max_tokens: int | None = None
    temperature: float | None = None
    stop: list[str] = []


class ModelResponse(BaseModel):
    """A neutral response from a model."""

    model_config = _STRICT

    content: str = ""
    tool_calls: list[ToolCall] = []
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)


# --- Streaming events ---------------------------------------------------------


class TextDelta(BaseModel):
    """A chunk of streamed assistant text."""

    model_config = _STRICT

    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolCallDelta(BaseModel):
    """A fully-formed tool call emitted during streaming."""

    model_config = _STRICT

    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall


class StreamDone(BaseModel):
    """The final streaming event, carrying the stop reason and usage."""

    model_config = _STRICT

    type: Literal["done"] = "done"
    stop_reason: StopReason
    usage: Usage = Field(default_factory=Usage)


#: A streaming event: text delta, tool call, or done — discriminated on ``type``.
ModelEvent = Annotated[
    TextDelta | ToolCallDelta | StreamDone, Field(discriminator="type")
]

model_event_adapter: TypeAdapter[ModelEvent] = TypeAdapter(ModelEvent)


def parse_model_event(data: dict[str, Any]) -> ModelEvent:
    """Parse one streaming-event dict into its concrete type."""
    return model_event_adapter.validate_python(data)


def dump_model_event(event: ModelEvent) -> dict[str, Any]:
    """Serialize a streaming event to a JSON-ready dict."""
    return model_event_adapter.dump_python(event, mode="json")
