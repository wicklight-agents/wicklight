"""Tests for the provider conformance kit (DTN-207)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from wicklight import _pytest_plugin as pytest_plugin
from wicklight.contracts import (
    Capabilities,
    Message,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    Role,
    StopReason,
    TextDelta,
)
from wicklight.providers import FakeProvider, FakeScript
from wicklight.testing import ConformanceCase, Scenario, run_provider_conformance

_SCRIPTS = {
    Scenario.PLAIN: "responses:\n  - text: hello\n",
    Scenario.SINGLE_TOOL: "responses:\n  - tool_calls:\n      - name: read_inbox\n",
    Scenario.PARALLEL_TOOLS: (
        "responses:\n  - tool_calls:\n      - name: a\n      - name: b\n"
    ),
    Scenario.STREAMING: "responses:\n  - text: streamed hello world\n",
    Scenario.ERROR: "responses:\n  - error: boom\n",
}


def _request() -> ModelRequest:
    return ModelRequest(
        model="fake/x", messages=[Message(role=Role.USER, content="hi")]
    )


def _fake_factory(scenario: Scenario) -> ConformanceCase:
    provider = FakeProvider(FakeScript.from_yaml(_SCRIPTS[scenario]))
    return ConformanceCase(provider, _request())


def test_fake_provider_passes_the_full_kit() -> None:
    report = asyncio.run(run_provider_conformance(_fake_factory))
    assert report.passed(), report.summary()
    assert report.contract_version == "1.0"
    # Both capability-gated checks actually ran (FakeProvider declares them).
    statuses = {r.name: r.status for r in report.results}
    assert statuses["parallel_tool_calls"] == "pass"
    assert statuses["streaming"] == "pass"


class QuietProvider(FakeProvider):
    """Declares neither streaming nor parallel tool calls."""

    capabilities = Capabilities()


def test_capability_gated_checks_are_skipped_when_not_declared() -> None:
    def factory(scenario: Scenario) -> ConformanceCase:
        provider = QuietProvider(FakeScript.from_yaml(_SCRIPTS[scenario]))
        return ConformanceCase(provider, _request())

    report = asyncio.run(run_provider_conformance(factory))
    assert report.passed(), report.summary()
    statuses = {r.name: r.status for r in report.results}
    assert statuses["parallel_tool_calls"] == "skip"
    assert statuses["streaming"] == "skip"


class BrokenProvider:
    """Violates the contract in several ways on purpose."""

    contract_version = "1.0"
    capabilities = Capabilities(streaming=True, parallel_tool_calls=True)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        # Never emits tool calls and never raises — wrong for tool/error scenarios.
        return ModelResponse(content="x", stop_reason=StopReason.STOP)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        yield TextDelta(text="x")  # never yields a done event


def test_broken_provider_fails_with_clear_messages() -> None:
    def factory(scenario: Scenario) -> ConformanceCase:
        return ConformanceCase(BrokenProvider(), _request())

    report = asyncio.run(run_provider_conformance(factory))
    assert not report.passed()
    failed = {r.name for r in report.failures}
    assert failed == {
        "single_tool_call",
        "parallel_tool_calls",
        "streaming",
        "error_mapping",
    }
    # Messages are specific and the version is reported.
    messages = {r.name: r.message for r in report.failures}
    assert "at least one tool call" in messages["single_tool_call"]
    assert "done event" in messages["streaming"]

    with pytest.raises(AssertionError, match="failed 4 conformance check"):
        report.assert_passed()


def test_pytest_plugin_registers_option_and_marker() -> None:
    added: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class StubParser:
        def addoption(self, *args: object, **kwargs: object) -> None:
            added.append((args, kwargs))

    pytest_plugin.pytest_addoption(StubParser())  # type: ignore[arg-type]
    assert any("--wicklight-provider" in args for args, _ in added)

    lines: list[tuple[str, str]] = []

    class StubConfig:
        def addinivalue_line(self, name: str, line: str) -> None:
            lines.append((name, line))

    pytest_plugin.pytest_configure(StubConfig())  # type: ignore[arg-type]
    assert any(name == "markers" and "conformance" in line for name, line in lines)
