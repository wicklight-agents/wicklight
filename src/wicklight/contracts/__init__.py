"""The three strict, versioned contracts and the harness's neutral types.

Provider, Tool, and Policy are the only extension points. Each has typed
inputs/outputs owned by the harness, a declared contract version and
capabilities checked at load time, and a conformance kit every plugin passes.
"""

from __future__ import annotations

from wicklight.contracts.models import (
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
    model_event_adapter,
    parse_model_event,
)

#: Version of the provider/tool/policy contract these neutral types belong to.
#: Follows semantic versioning; the previous major is supported for 6 months
#: after a new one ships.
CONTRACT_VERSION = "1.0"

__all__ = [
    "CONTRACT_VERSION",
    "Message",
    "ModelEvent",
    "ModelRequest",
    "ModelResponse",
    "Role",
    "StopReason",
    "StreamDone",
    "TextDelta",
    "ToolCall",
    "ToolCallDelta",
    "ToolDefinition",
    "Usage",
    "dump_model_event",
    "model_event_adapter",
    "parse_model_event",
]
