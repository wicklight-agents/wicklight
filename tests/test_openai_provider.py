"""The OpenAI adapter against recorded fixtures (DTN-230).

Done-when: passes the full provider conformance kit offline, replaying
hand-written cassettes of the Chat Completions shape. Plus focused tests for
translation (tool-call argument strings, tool-result messages) and errors.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from wicklight.contracts import (
    Message,
    ModelRequest,
    ProviderErrorKind,
    Role,
    StopReason,
    StreamDone,
    TextDelta,
)
from wicklight.contracts.provider import ProviderError
from wicklight.providers import OpenAIProvider
from wicklight.providers.openai import request_body
from wicklight.testing import (
    ConformanceCase,
    ProviderScenario,
    replay_transport,
    run_provider_conformance,
)

CASSETTES = Path(__file__).parent / "cassettes" / "openai"
_SCENARIO_CASSETTES = {
    ProviderScenario.PLAIN: "plain.json",
    ProviderScenario.SINGLE_TOOL: "single_tool.json",
    ProviderScenario.PARALLEL_TOOLS: "parallel_tools.json",
    ProviderScenario.STREAMING: "streaming.json",
    ProviderScenario.ERROR: "error.json",
}


def _request() -> ModelRequest:
    return ModelRequest(
        model="gpt-4o", messages=[Message(role=Role.USER, content="hi")]
    )


def _factory(scenario: ProviderScenario) -> ConformanceCase:
    transport = replay_transport(CASSETTES / _SCENARIO_CASSETTES[scenario])
    return ConformanceCase(
        OpenAIProvider(api_key="test-key", transport=transport), _request()
    )


def test_openai_passes_the_full_conformance_kit() -> None:
    report = asyncio.run(run_provider_conformance(_factory))
    assert report.passed(), report.summary()
    statuses = {r.name: r.status for r in report.results}
    assert statuses["parallel_tool_calls"] == "pass"
    assert statuses["streaming"] == "pass"


# --- translation details ------------------------------------------------------


def test_tool_call_arguments_string_is_parsed_to_a_dict() -> None:
    provider = OpenAIProvider(
        api_key="k", transport=replay_transport(CASSETTES / "parallel_tools.json")
    )
    response = asyncio.run(provider.complete(_request()))
    assert response.stop_reason is StopReason.TOOL_USE
    calls = {c.name: c.arguments for c in response.tool_calls}
    assert calls == {"a": {"x": 1}, "b": {"y": 2}}  # JSON strings -> dicts


def test_null_content_becomes_empty_string() -> None:
    provider = OpenAIProvider(
        api_key="k", transport=replay_transport(CASSETTES / "single_tool.json")
    )
    response = asyncio.run(provider.complete(_request()))
    assert response.content == ""  # message.content was null
    assert response.usage.input_tokens == 42
    assert response.usage.cost_usd is not None and response.usage.cost_usd > 0


def test_streaming_text_then_tool_free_done() -> None:
    provider = OpenAIProvider(
        api_key="k", transport=replay_transport(CASSETTES / "streaming.json")
    )

    async def collect() -> list[object]:
        return [e async for e in provider.stream(_request())]

    events = asyncio.run(collect())
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "streamed hello world"
    assert isinstance(events[-1], StreamDone)
    assert events[-1].usage.output_tokens == 5  # usage-only final chunk


def test_request_body_translation() -> None:
    request = ModelRequest(
        model="gpt-4o",
        messages=[
            Message(role=Role.SYSTEM, content="be terse"),
            Message(role=Role.USER, content="hello"),
            Message(role=Role.TOOL, content="RESULT", tool_call_id="call_1"),
        ],
    )
    body = request_body(request, stream=False)
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "tool"]  # system stays in messages
    tool_msg = body["messages"][2]
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "RESULT"  # untrusted envelope preserved verbatim
    assert "stream" not in body


def test_streaming_request_asks_for_usage() -> None:
    body = request_body(_request(), stream=True)
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}


# --- error mapping ------------------------------------------------------------


def test_http_error_maps_to_kind() -> None:
    provider = OpenAIProvider(
        api_key="k", transport=replay_transport(CASSETTES / "error.json")
    )
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.kind is ProviderErrorKind.INVALID_REQUEST


def test_context_length_error_is_promoted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "This model's maximum context length is 128000 tokens",
                    "type": "invalid_request_error",
                }
            },
        )

    provider = OpenAIProvider(api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.kind is ProviderErrorKind.CONTEXT_TOO_LONG


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, ProviderErrorKind.RATE_LIMIT),
        (401, ProviderErrorKind.AUTH),
        (503, ProviderErrorKind.OVERLOADED),
        (500, ProviderErrorKind.UNKNOWN),
    ],
)
def test_error_status_matrix(status: int, expected: ProviderErrorKind) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "x"}})

    provider = OpenAIProvider(api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.kind is expected
