"""The OpenAI Chat Completions provider adapter.

Registered as ``openai/<model>`` through the ``wicklight.providers`` entry
point. The translation functions (:func:`request_body`, :func:`to_response`,
:func:`parse_sse`, :func:`error_from_response`) are module-level and provider-
neutral so the OpenAI-compatible adapter (DTN-231: Ollama, vLLM, …) can reuse
them against a different base URL.

The API key is read from ``OPENAI_API_KEY`` lazily, on the first real call
(DTN-227). Tests inject a replay ``transport`` (cassettes, DTN-226) and an
explicit key, so they run offline.
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

DEFAULT_BASE_URL = "https://api.openai.com"
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"

# Best-effort USD price per 1M tokens (input, output), most specific first.
_PRICING: tuple[tuple[str, float, float], ...] = (
    ("gpt-4o-mini", 0.15, 0.60),
    ("gpt-4o", 2.50, 10.0),
    ("gpt-4-turbo", 10.0, 30.0),
    ("gpt-4", 30.0, 60.0),
    ("gpt-3.5", 0.50, 1.50),
)

_FINISH_REASONS: dict[str, StopReason] = {
    "stop": StopReason.STOP,
    "tool_calls": StopReason.TOOL_USE,
    "function_call": StopReason.TOOL_USE,
    "length": StopReason.LENGTH,
    "content_filter": StopReason.STOP,
}

_ERROR_STATUS: dict[int, ProviderErrorKind] = {
    400: ProviderErrorKind.INVALID_REQUEST,
    401: ProviderErrorKind.AUTH,
    403: ProviderErrorKind.AUTH,
    404: ProviderErrorKind.INVALID_REQUEST,
    408: ProviderErrorKind.TIMEOUT,
    413: ProviderErrorKind.CONTEXT_TOO_LONG,
    429: ProviderErrorKind.RATE_LIMIT,
    500: ProviderErrorKind.UNKNOWN,
    503: ProviderErrorKind.OVERLOADED,
    504: ProviderErrorKind.TIMEOUT,
}


class OpenAIProvider:
    """A :class:`~wicklight.contracts.Provider` for the OpenAI Chat API.

    Subclassable for OpenAI-compatible servers: override ``provider_name`` (the
    credential lookup key) and pass a different ``base_url``. A provider with no
    key sets ``requires_key=False``.
    """

    contract_version = CONTRACT_VERSION
    capabilities = Capabilities(
        parallel_tool_calls=True,
        streaming=True,
        structured_output=True,
        max_context_tokens=128_000,
    )
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
        requires_key: bool = True,
        chat_path: str = CHAT_COMPLETIONS_PATH,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url
        self._transport = transport
        self._timeout = timeout
        self._requires_key = requires_key
        self._chat_path = chat_path

    async def complete(self, request: ModelRequest) -> ModelResponse:
        body = request_body(request, stream=False)
        async with self._client() as client:
            try:
                response = await client.post(self._chat_path, json=body)
            except httpx.TimeoutException as exc:
                raise ProviderError(
                    f"{self.provider_name} request timed out: {exc}",
                    kind=ProviderErrorKind.TIMEOUT,
                ) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(
                    f"{self.provider_name} request failed: {exc}"
                ) from exc
            if response.status_code >= 400:
                raise error_from_response(response, self.provider_name)
            return to_response(response.json(), request.model)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        body = request_body(request, stream=True)
        async with (
            self._client() as client,
            client.stream("POST", self._chat_path, json=body) as response,
        ):
            if response.status_code >= 400:
                await response.aread()
                raise error_from_response(response, self.provider_name)
            async for event in parse_sse(response, request.model):
                yield event

    # --- internals ------------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        headers = {"content-type": "application/json"}
        if self._requires_key:
            key = self._api_key or resolve_key(self.provider_name)
            headers["authorization"] = f"Bearer {key}"
        elif self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            transport=self._transport,
            timeout=self._timeout,
        )


# --- request translation (neutral -> Chat Completions) -----------------------


def request_body(request: ModelRequest, *, stream: bool) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": request.model,
        "messages": [_message(m) for m in request.messages],
    }
    if request.tools:
        body["tools"] = [_tool(t) for t in request.tools]
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if request.stop:
        body["stop"] = request.stop
    if stream:
        body["stream"] = True
        # Ask for a usage summary on the final streamed chunk.
        body["stream_options"] = {"include_usage": True}
    return body


def _message(message: Message) -> dict[str, Any]:
    if message.role is Role.TOOL:
        # A tool result keeps the untrusted "data, not instructions" envelope
        # the core applied (DTN-219).
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "",
            "content": message.content,
        }
    return {"role": message.role.value, "content": message.content}


def _tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters or {"type": "object", "properties": {}},
        },
    }


# --- response translation (Chat Completions -> neutral) ----------------------


def to_response(data: dict[str, Any], model: str) -> ModelResponse:
    choices = cast("list[dict[str, Any]]", data.get("choices", []))
    choice = choices[0] if choices else {}
    message = _obj(choice.get("message"))

    tool_calls: list[ToolCall] = []
    for raw in cast("list[dict[str, Any]]", message.get("tool_calls", [])):
        function = _obj(raw.get("function"))
        tool_calls.append(
            ToolCall(
                id=str(raw.get("id", "")),
                name=str(function.get("name", "")),
                arguments=_parse_arguments(str(function.get("arguments", ""))),
            )
        )

    return ModelResponse(
        content=str(message.get("content") or ""),
        tool_calls=tool_calls,
        stop_reason=_FINISH_REASONS.get(
            str(choice.get("finish_reason", "")), StopReason.STOP
        ),
        usage=_usage(_obj(data.get("usage")), model),
    )


def _usage(raw: dict[str, Any], model: str) -> Usage:
    input_tokens = int(raw.get("prompt_tokens", 0))
    output_tokens = int(raw.get("completion_tokens", 0))
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=_estimate_cost(model, input_tokens, output_tokens),
    )


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    for key, in_price, out_price in _PRICING:
        if key in model:
            return (input_tokens * in_price + output_tokens * out_price) / 1_000_000
    return None


def _parse_arguments(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        return cast("dict[str, Any]", json.loads(text))
    except json.JSONDecodeError:
        return {}


# --- error mapping ------------------------------------------------------------


def error_from_response(response: httpx.Response, provider_name: str) -> ProviderError:
    status = response.status_code
    message = ""
    try:
        error = _obj(_obj(response.json()).get("error"))
        message = str(error.get("message", ""))
    except (ValueError, AttributeError):
        message = response.text

    kind = _ERROR_STATUS.get(status, ProviderErrorKind.UNKNOWN)
    if _looks_like_context(message):
        kind = ProviderErrorKind.CONTEXT_TOO_LONG

    detail = message or f"HTTP {status}"
    return ProviderError(f"{provider_name} error ({status}): {detail}", kind=kind)


def _looks_like_context(message: str) -> bool:
    lowered = message.lower()
    return "context length" in lowered or "context_length_exceeded" in lowered


# --- streaming SSE parsing ----------------------------------------------------


async def parse_sse(response: httpx.Response, model: str) -> AsyncIterator[ModelEvent]:
    """Map OpenAI streamed chunks to neutral :class:`ModelEvent`s."""
    # Tool calls accumulate across deltas, keyed by their position (index).
    tool_calls: dict[int, dict[str, Any]] = {}
    stop_reason = StopReason.STOP
    usage_raw: dict[str, Any] = {}

    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        chunk = cast("dict[str, Any]", json.loads(payload))

        usage = chunk.get("usage")
        if isinstance(usage, dict):
            usage_raw = cast("dict[str, Any]", usage)

        choices = cast("list[dict[str, Any]]", chunk.get("choices", []))
        if not choices:
            continue
        choice = choices[0]
        delta = _obj(choice.get("delta"))

        content = delta.get("content")
        if isinstance(content, str) and content:
            yield TextDelta(text=content)

        for raw in cast("list[dict[str, Any]]", delta.get("tool_calls", [])):
            _accumulate_tool_call(tool_calls, raw)

        finish = choice.get("finish_reason")
        if finish:
            stop_reason = _FINISH_REASONS.get(str(finish), StopReason.STOP)

    for index in sorted(tool_calls):
        yield ToolCallDelta(tool_call=_finish_tool_call(tool_calls[index]))
    yield StreamDone(stop_reason=stop_reason, usage=_usage(usage_raw, model))


def _accumulate_tool_call(
    tool_calls: dict[int, dict[str, Any]], raw: dict[str, Any]
) -> None:
    index = int(raw.get("index", 0))
    entry = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if raw.get("id"):
        entry["id"] = str(raw["id"])
    function = _obj(raw.get("function"))
    if function.get("name"):
        entry["name"] = str(function["name"])
    if function.get("arguments"):
        entry["arguments"] += str(function["arguments"])


def _finish_tool_call(entry: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=str(entry["id"]),
        name=str(entry["name"]),
        arguments=_parse_arguments(str(entry["arguments"])),
    )


def _obj(value: Any) -> dict[str, Any]:
    """Coerce an opaque JSON value to a dict for safe chained access."""
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}
