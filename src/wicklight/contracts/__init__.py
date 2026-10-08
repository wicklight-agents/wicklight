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
from wicklight.contracts.provider import (
    PROVIDER_ENTRY_POINT_GROUP,
    Capabilities,
    Provider,
    ProviderError,
    ProviderInfo,
    ProviderRegistry,
    check_contract_version,
    classify_contract_version,
    describe_providers,
)
from wicklight.contracts.version import CONTRACT_VERSION

__all__ = [
    "CONTRACT_VERSION",
    "PROVIDER_ENTRY_POINT_GROUP",
    "Capabilities",
    "Message",
    "ModelEvent",
    "ModelRequest",
    "ModelResponse",
    "Provider",
    "ProviderError",
    "ProviderInfo",
    "ProviderRegistry",
    "Role",
    "StopReason",
    "StreamDone",
    "TextDelta",
    "ToolCall",
    "ToolCallDelta",
    "ToolDefinition",
    "Usage",
    "check_contract_version",
    "classify_contract_version",
    "describe_providers",
    "dump_model_event",
    "model_event_adapter",
    "parse_model_event",
]
