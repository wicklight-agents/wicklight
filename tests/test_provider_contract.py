"""Tests for the Provider contract and entry-point discovery (DTN-205)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest

from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    Provider,
    ProviderError,
    ProviderRegistry,
    Role,
    StopReason,
    StreamDone,
    TextDelta,
    Usage,
    check_contract_version,
)
from wicklight.contracts.models import Message


class GoodProvider:
    """A minimal conforming provider for tests."""

    contract_version = "1.0"
    capabilities = Capabilities(streaming=True, max_context_tokens=200_000)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content=f"echo:{request.model}",
            stop_reason=StopReason.STOP,
            usage=Usage(input_tokens=1, output_tokens=1),
        )

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        yield TextDelta(text="hi")
        yield StreamDone(stop_reason=StopReason.STOP)


class FutureProvider(GoodProvider):
    contract_version = "2.0"  # newer major than the harness supports


@dataclass
class FakeEntryPoint:
    name: str
    obj: object

    def load(self) -> object:
        return self.obj


def _registry(**plugins: object) -> ProviderRegistry:
    eps = [FakeEntryPoint(name, obj) for name, obj in plugins.items()]
    return ProviderRegistry.discover(entry_points_=eps)


def test_discovers_a_plugin_class_and_resolves_model_id() -> None:
    registry = _registry(anthropic=GoodProvider)
    assert registry.names() == ["anthropic"]

    provider, model = registry.resolve("anthropic/claude-sonnet")
    assert model == "claude-sonnet"
    assert isinstance(provider, Provider)  # structurally conforms
    assert provider.capabilities.streaming is True


def test_discovers_a_plugin_instance() -> None:
    instance = GoodProvider()
    registry = _registry(anthropic=instance)
    provider, _ = registry.resolve("anthropic/claude-sonnet")
    assert provider is instance


def test_resolved_provider_completes_and_streams() -> None:
    provider, model = _registry(anthropic=GoodProvider).resolve("anthropic/x")
    request = ModelRequest(
        model=model, messages=[Message(role=Role.USER, content="hi")]
    )

    response = asyncio.run(provider.complete(request))
    assert response.content == "echo:x"

    async def collect() -> list[str]:
        return [event.type async for event in provider.stream(request)]

    assert asyncio.run(collect()) == ["text_delta", "done"]


def test_unknown_provider_lists_available() -> None:
    registry = _registry(anthropic=GoodProvider)
    with pytest.raises(ProviderError, match="unknown provider 'openai'"):
        registry.resolve("openai/gpt-5")


def test_malformed_model_id_is_rejected() -> None:
    registry = _registry(anthropic=GoodProvider)
    with pytest.raises(ProviderError, match="provider/model"):
        registry.resolve("no-slash")


def test_unsupported_major_version_fails_at_load() -> None:
    with pytest.raises(ProviderError, match="newer than this harness"):
        _registry(future=FutureProvider)


def test_discover_finds_registered_fake_provider() -> None:
    # The FakeProvider (DTN-206) is registered under the `fake` entry point.
    assert "fake" in ProviderRegistry.discover().names()


@pytest.mark.parametrize("version", ["1.0", "1.9", "0.9"])
def test_supported_contract_versions(version: str) -> None:
    check_contract_version(version)  # does not raise


@pytest.mark.parametrize("version", ["2.0", "abc"])
def test_unsupported_contract_versions(version: str) -> None:
    with pytest.raises(ProviderError):
        check_contract_version(version)


def test_capabilities_defaults_and_strictness() -> None:
    caps = Capabilities()
    assert caps.parallel_tool_calls is False
    assert caps.streaming is False
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError on extra key
        Capabilities.model_validate({"nope": True})
