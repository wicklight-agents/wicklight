"""The Anthropic Messages API provider adapter.

Registered as ``anthropic/<model>`` through the ``wicklight.providers`` entry
point. It translates the harness's neutral model types to and from the Messages
API and maps HTTP failures to neutral :class:`ProviderError` kinds (DTN-228).
It is deliberately small and readable: it doubles as the worked example for
plugin authors.

The API key is read from ``ANTHROPIC_API_KEY`` lazily, on the first real call
(DTN-227), so merely constructing the provider — as entry-point discovery does —
needs no key. Tests inject a replay ``transport`` (recorded cassettes, DTN-226)
and an explicit key, so they run offline.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from wicklight.contracts import (
    Capabilities,
    Message,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorKind,
    Role,
    StopReason,
    StreamDone,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolDefinition,
    Usage,
)
from wicklight.contracts.version import CONTRACT_VERSION
from wicklight.providers.credentials import resolve_key

DEFAULT_BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"
_MESSAGES_PATH = "/v1/messages"
#: Used when an agent file sets no max_tokens — the Messages API requires one.
DEFAULT_MAX_TOKENS = 1024

# Best-effort USD price per 1M tokens (input, output), for a cost estimate only.
# Matched by substring on the model id; may drift from current pricing.
_PRICING: dict[str, tuple[float, float]] = {
    "opus": (15.0, 75.0),
    "sonnet": (3.0, 15.0),
    "haiku": (0.80, 4.0),
}

_STOP_REASONS: dict[str, StopReason] = {
    "end_turn": StopReason.STOP,
    "stop_sequence": StopReason.STOP,
    "tool_use": StopReason.TOOL_USE,
    "max_tokens": StopReason.LENGTH,
}

# Anthropic error `type` → neutral kind. Status code is the fallback.
_ERROR_TYPES: dict[str, ProviderErrorKind] = {
    "authentication_error": ProviderErrorKind.AUTH,
    "permission_error": ProviderErrorKind.AUTH,
    "rate_limit_error": ProviderErrorKind.RATE_LIMIT,
    "overloaded_error": ProviderErrorKind.OVERLOADED,
    "invalid_request_error": ProviderErrorKind.INVALID_REQUEST,
    "not_found_error": ProviderErrorKind.INVALID_REQUEST,
    "api_error": ProviderErrorKind.UNKNOWN,
}
_ERROR_STATUS: dict[int, ProviderErrorKind] = {
    400: ProviderErrorKind.INVALID_REQUEST,
    401: ProviderErrorKind.AUTH,
    403: ProviderErrorKind.AUTH,
    404: ProviderErrorKind.INVALID_REQUEST,
    408: ProviderErrorKind.TIMEOUT,
    413: ProviderErrorKind.CONTEXT_TOO_LONG,
    429: ProviderErrorKind.RATE_LIMIT,
    503: ProviderErrorKind.OVERLOADED,
    504: ProviderErrorKind.TIMEOUT,
    529: ProviderErrorKind.OVERLOADED,
}


class AnthropicProvider:
    """A :class:`~wicklight.contracts.Provider` for the Anthropic Messages API."""

    contract_version = CONTRACT_VERSION
    capabilities = Capabilities(
        parallel_tool_calls=True,
        streaming=True,
        max_context_tokens=200_000,
    )

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._transport = transport
        self._timeout = timeout
        self._max_tokens = max_tokens

    async def complete(self, request: ModelRequest) -> ModelResponse:
        body = _request_body(request, self._max_tokens, stream=False)
        async with self._client() as client:
            try:
                response = await client.post(_MESSAGES_PATH, json=body)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"anthropic request timed out: {exc}",
                    kind=ProviderErrorKind.TIMEOUT,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(f"anthropic request failed: {exc}") from exc
            if response.status_code >= 400:
                raise _error_from_response(response)
            return _to_response(response.json(), request.model)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        body = _request_body(request, self._max_tokens, stream=True)
        async with (
            self._client() as client,
            client.stream("POST", _MESSAGES_PATH, json=body) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise _error_from_response(response)
            async for event in _parse_sse(response, request.model):
                yield event

    # --- internals ------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        key = self._api_key or resolve_key("anthropic")
        headers = {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            transport=self._transport,
            timeout=self._timeout,
        )


# --- request translation (neutral -> Messages API) ---------------------------


def _request_body(
    request: ModelRequest, default_max_tokens: int, *, stream: bool
) -> dict[str, Any]:
    system = "\n\n".join(
        m.content for m in request.messages if m.role is Role.SYSTEM and m.content
    )
    body: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens or default_max_tokens,
        "messages": [
            _message_block(m) for m in request.messages if m.role is not Role.SYSTEM
        ],
        "stream": stream,
    }
    if system:
        body["system"] = system
    if request.tools:
        body["tools"] = [_tool_block(t) for t in request.tools]
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.stop:
        body["stop_sequences"] = request.stop
    return body


def _message_block(message: Message) -> dict[str, Any]:
    if message.role is Role.TOOL:
        # A tool result is a user-turn tool_result block; its content keeps the
        # untrusted "data, not instructions" envelope the core applied (DTN-219).
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id or "",
                    "content": message.content,
                }
            ],
        }
    role = "assistant" if message.role is Role.ASSISTANT else "user"
    return {"role": role, "content": [{"type": "text", "text": message.content}]}


def _tool_block(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.parameters or {"type": "object", "properties": {}},
    }


# --- response translation (Messages API -> neutral) ---------------------------


def _to_response(data: dict[str, Any], model: str) -> ModelResponse:
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    content = cast("list[dict[str, Any]]", data.get("content", []))
    for block in content:
        if block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=str(block.get("id", "")),
                    name=str(block.get("name", "")),
                    arguments=cast("dict[str, Any]", block.get("input", {})),
                )
            )
    return ModelResponse(
        content="".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=_STOP_REASONS.get(
            str(data.get("stop_reason", "")), StopReason.STOP
        ),
        usage=_usage(cast("dict[str, Any]", data.get("usage", {})), model),
    )


def _usage(raw: dict[str, Any], model: str) -> Usage:
    input_tokens = int(raw.get("input_tokens", 0))
    output_tokens = int(raw.get("output_tokens", 0))
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=_estimate_cost(model, input_tokens, output_tokens),
    )


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    for key, (in_price, out_price) in _PRICING.items():
        if key in model:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return None


# --- error mapping ------------------------------------------------------------


def _error_from_response(response: httpx.Response) -> ProviderError:
    status = response.status_code
    error_type = ""
    message = ""
    try:
        raw = response.json()
        body = cast("dict[str, Any]", raw) if isinstance(raw, dict) else {}
        error = cast("dict[str, Any]", body.get("error", {}))
        error_type = str(error.get("type", ""))
        message = str(error.get("message", ""))
    except (ValueError, AttributeError):
        message = response.text

    kind = _ERROR_TYPES.get(error_type) or _ERROR_STATUS.get(
        status, ProviderErrorKind.UNKNOWN
    )
    # A too-long prompt arrives as an invalid_request; promote it to the clearer
    # context-length kind so the suggested fix is right.
    if kind is ProviderErrorKind.INVALID_REQUEST and _looks_like_context(message):
        kind = ProviderErrorKind.CONTEXT_TOO_LONG

    detail = message or f"HTTP {status}"
    return ProviderError(f"anthropic error ({status}): {detail}", kind=kind)


def _looks_like_context(message: str) -> bool:
    lowered = message.lower()
    return "too long" in lowered or "context" in lowered or "max_tokens" in lowered


# --- streaming SSE parsing ----------------------------------------------------


def _obj(value: Any) -> dict[str, Any]:
    """Coerce an opaque JSON value to a dict for safe chained access."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


async def _parse_sse(response: httpx.Response, model: str) -> AsyncIterator[ModelEvent]:
    """Map Anthropic's server-sent events to neutral :class:`ModelEvent`s."""
    tool_blocks: dict[int, dict[str, Any]] = {}
    stop_reason = StopReason.STOP
    input_tokens = 0
    output_tokens = 0

    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload:
            continue
        event = cast("dict[str, Any]", json.loads(payload))
        kind = event.get("type")

        if kind == "message_start":
            usage = _obj(_obj(event.get("message")).get("usage"))
            input_tokens = int(usage.get("input_tokens", 0))
        elif kind == "content_block_start":
            block = _obj(event.get("content_block"))
            if block.get("type") == "tool_use":
                tool_blocks[int(event.get("index", 0))] = {
                    "id": str(block.get("id", "")),
                    "name": str(block.get("name", "")),
                    "json": "",
                }
        elif kind == "content_block_delta":
            delta = _obj(event.get("delta"))
            if delta.get("type") == "text_delta":
                yield TextDelta(text=str(delta.get("text", "")))
            elif delta.get("type") == "input_json_delta":
                pending = tool_blocks.get(int(event.get("index", 0)))
                if pending is not None:
                    pending["json"] += str(delta.get("partial_json", ""))
        elif kind == "content_block_stop":
            pending = tool_blocks.pop(int(event.get("index", 0)), None)
            if pending is not None:
                yield ToolCallDelta(tool_call=_finish_tool_call(pending))
        elif kind == "message_delta":
            stop_reason = _STOP_REASONS.get(
                str(_obj(event.get("delta")).get("stop_reason", "")), StopReason.STOP
            )
            output_tokens = int(
                _obj(event.get("usage")).get("output_tokens", output_tokens)
            )

    yield StreamDone(
        stop_reason=stop_reason,
        usage=_usage(
            {"input_tokens": input_tokens, "output_tokens": output_tokens}, model
        ),
    )


def _finish_tool_call(block: dict[str, Any]) -> ToolCall:
    raw = str(block["json"]).strip()
    arguments = cast("dict[str, Any]", json.loads(raw)) if raw else {}
    return ToolCall(id=str(block["id"]), name=str(block["name"]), arguments=arguments)
