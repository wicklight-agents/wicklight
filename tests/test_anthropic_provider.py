"""The Anthropic adapter against recorded fixtures (DTN-229).

The done-when: the adapter passes the full provider conformance kit with no
network — each scenario replays a hand-written cassette of the Messages API
shape. Plus focused tests for translation and error mapping.
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
from wicklight.providers import AnthropicProvider
from wicklight.providers.anthropic import _request_body
from wicklight.testing import (
    ConformanceCase,
    ProviderScenario,
    replay_transport,
    run_provider_conformance,
)

CASSETTES = Path(__file__).parent / "cassettes" / "anthropic"
_SCENARIO_CASSETTES = {
    ProviderScenario.PLAIN: "plain.json",
    ProviderScenario.SINGLE_TOOL: "single_tool.json",
    ProviderScenario.PARALLEL_TOOLS: "parallel_tools.json",
    ProviderScenario.STREAMING: "streaming.json",
    ProviderScenario.ERROR: "error.json",
}


def _request() -> ModelRequest:
    return ModelRequest(
        model="claude-sonnet-4-6",
        messages=[Message(role=Role.USER, content="hi")],
    )


def _factory(scenario: ProviderScenario) -> ConformanceCase:
    transport = replay_transport(CASSETTES / _SCENARIO_CASSETTES[scenario])
    provider = AnthropicProvider(api_key="test-key", transport=transport)
    return ConformanceCase(provider, _request())


def test_anthropic_passes_the_full_conformance_kit() -> None:
    report = asyncio.run(run_provider_conformance(_factory))
    assert report.passed(), report.summary()
    assert report.contract_version == "1.0"
    statuses = {r.name: r.status for r in report.results}
    # Both capability-gated checks actually ran (the adapter declares them).
    assert statuses["parallel_tool_calls"] == "pass"
    assert statuses["streaming"] == "pass"


# --- translation details ------------------------------------------------------


def test_complete_maps_text_tool_calls_and_usage() -> None:
    provider = AnthropicProvider(
        api_key="k", transport=replay_transport(CASSETTES / "single_tool.json")
    )
    response = asyncio.run(provider.complete(_request()))
    assert response.content == "Let me check the inbox."
    assert response.stop_reason is StopReason.TOOL_USE
    assert [c.name for c in response.tool_calls] == ["read_inbox"]
    assert response.usage.input_tokens == 40
    assert response.usage.output_tokens == 18
    # sonnet pricing is known, so a cost estimate is produced.
    assert response.usage.cost_usd is not None and response.usage.cost_usd > 0


def test_streaming_yields_text_then_done() -> None:
    provider = AnthropicProvider(
        api_key="k", transport=replay_transport(CASSETTES / "streaming.json")
    )

    async def collect() -> list[object]:
        return [e async for e in provider.stream(_request())]

    events = asyncio.run(collect())
    text = "".join(e.text for e in events if isinstance(e, TextDelta))
    assert text == "streamed hello world"
    assert isinstance(events[-1], StreamDone)
    assert events[-1].stop_reason is StopReason.STOP


def test_request_body_translation() -> None:
    request = ModelRequest(
        model="claude-sonnet-4-6",
        messages=[
            Message(role=Role.SYSTEM, content="be terse"),
            Message(role=Role.USER, content="hello"),
            Message(role=Role.TOOL, content="RESULT", tool_call_id="toolu_1", name="t"),
        ],
        max_tokens=256,
    )
    body = _request_body(request, 1024, stream=False)
    assert body["system"] == "be terse"  # system lifted out of messages
    assert body["max_tokens"] == 256
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "user"]  # system removed; tool -> user tool_result
    tool_result = body["messages"][1]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert tool_result["tool_use_id"] == "toolu_1"
    assert tool_result["content"] == "RESULT"  # untrusted envelope preserved verbatim


# --- error mapping ------------------------------------------------------------


def test_http_error_maps_to_provider_error_kind() -> None:
    provider = AnthropicProvider(
        api_key="k", transport=replay_transport(CASSETTES / "error.json")
    )
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.kind is ProviderErrorKind.INVALID_REQUEST


@pytest.mark.parametrize(
    ("status", "error_type", "expected"),
    [
        (429, "rate_limit_error", ProviderErrorKind.RATE_LIMIT),
        (529, "overloaded_error", ProviderErrorKind.OVERLOADED),
        (401, "authentication_error", ProviderErrorKind.AUTH),
        (400, "invalid_request_error", ProviderErrorKind.INVALID_REQUEST),
    ],
)
def test_error_kind_matrix(
    status: int, error_type: str, expected: ProviderErrorKind
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={"type": "error", "error": {"type": error_type, "message": "x"}},
        )

    provider = AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.kind is expected


def test_retryable_rate_limit_from_the_adapter() -> None:
    # A rate-limit error from the adapter is retryable, so the core's retry
    # policy (DTN-228) will back off on it.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "type": "error",
                "error": {"type": "rate_limit_error", "message": "slow down"},
            },
        )

    provider = AnthropicProvider(api_key="k", transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderError) as excinfo:
        asyncio.run(provider.complete(_request()))
    assert excinfo.value.retryable
