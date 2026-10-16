"""The OpenAI-compatible adapter (Ollama/vLLM) against fixtures (DTN-231).

Reuses the OpenAI translation, so these tests focus on what differs: the
configurable base URL, no required key, and the conservative capability set.
Conformance runs offline against cassettes recorded in the Ollama shape.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wicklight.contracts import Message, ModelRequest, Role
from wicklight.providers import OpenAICompatibleProvider
from wicklight.providers.openai_compatible import DEFAULT_BASE_URL
from wicklight.testing import (
    ConformanceCase,
    ProviderScenario,
    replay_transport,
    run_provider_conformance,
)

CASSETTES = Path(__file__).parent / "cassettes" / "local"
# Parallel tool calls aren't declared, so that scenario is skipped by the kit;
# fall back to plain for any scenario without a dedicated cassette.
_SCENARIO_CASSETTES = {
    ProviderScenario.PLAIN: "plain.json",
    ProviderScenario.SINGLE_TOOL: "single_tool.json",
    ProviderScenario.STREAMING: "streaming.json",
    ProviderScenario.ERROR: "error.json",
}


def _request() -> ModelRequest:
    return ModelRequest(
        model="llama3.1", messages=[Message(role=Role.USER, content="hi")]
    )


def _factory(scenario: ProviderScenario) -> ConformanceCase:
    cassette = _SCENARIO_CASSETTES.get(scenario, "plain.json")
    provider = OpenAICompatibleProvider(
        transport=replay_transport(CASSETTES / cassette)
    )
    return ConformanceCase(provider, _request())


def test_compatible_passes_conformance_offline() -> None:
    report = asyncio.run(run_provider_conformance(_factory))
    assert report.passed(), report.summary()
    statuses = {r.name: r.status for r in report.results}
    # Conservative capabilities: streaming runs, parallel tool calls is skipped.
    assert statuses["streaming"] == "pass"
    assert statuses["parallel_tool_calls"] == "skip"


def test_plain_completion_against_a_local_model() -> None:
    provider = OpenAICompatibleProvider(
        transport=replay_transport(CASSETTES / "plain.json")
    )
    response = asyncio.run(provider.complete(_request()))
    assert response.content == "Hi there, running locally!"
    # llama3.1 has no pricing entry, so no cost is estimated.
    assert response.usage.cost_usd is None


def test_no_key_required() -> None:
    # Constructing and calling needs no ANTHROPIC/OPENAI key — requires_key off.
    provider = OpenAICompatibleProvider(
        transport=replay_transport(CASSETTES / "plain.json")
    )
    asyncio.run(provider.complete(_request()))  # would raise if a key were demanded


def test_base_url_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert OpenAICompatibleProvider()._base_url == DEFAULT_BASE_URL

    monkeypatch.setenv("OPENAI_BASE_URL", "http://vllm.internal:8000/v1")
    assert OpenAICompatibleProvider()._base_url == "http://vllm.internal:8000/v1"

    # An explicit base_url wins over the environment.
    provider = OpenAICompatibleProvider(base_url="http://host:1234/v1")
    assert provider._base_url == "http://host:1234/v1"


def test_endpoint_url_joins_without_double_v1() -> None:
    # base_url carries /v1; the path is just the chat-completions tail, so the
    # cassette URL (http://localhost:11434/v1/chat/completions) matches.
    provider = OpenAICompatibleProvider(
        transport=replay_transport(CASSETTES / "single_tool.json")
    )
    response = asyncio.run(provider.complete(_request()))
    assert [c.name for c in response.tool_calls] == ["read_inbox"]
