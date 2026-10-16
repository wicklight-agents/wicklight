"""Capability / contract preflight checks (DTN-232).

Each mismatch kind — tool calling, context size, provider not installed,
unsupported/deprecated contract — is exercised against fixture configs, plus
the loop's run-start check that stops with an error event.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from wicklight.agent import Agent
from wicklight.agentfile import build_effective_config, parse_and_validate
from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    ProviderRegistry,
    StopReason,
)
from wicklight.preflight import capability_issues, preflight
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import RunStatus, read_trace


def _config(frontmatter_body: str):
    agent, config = parse_and_validate(frontmatter_body)
    return build_effective_config(config, provided=agent.frontmatter), agent


TOOLED_AGENT = (
    "---\nname: t\nmodels: { default: toyless/x }\n"
    "tools: { read_inbox: read }\n---\nGo.\n"
)


# --- the capability comparison (unit) -----------------------------------------


def test_tool_calling_mismatch() -> None:
    issues = capability_issues(
        "toyless/x",
        Capabilities(streaming=True),  # no tool_calls
        enabled_tools=["read_inbox"],
        estimated_tokens=10,
        source="agent.md line 2",
    )
    assert len(issues) == 1
    assert "does not declare tool calling" in issues[0].message
    assert issues[0].fatal


def test_context_size_mismatch() -> None:
    issues = capability_issues(
        "toyless/x",
        Capabilities(tool_calls=True, max_context_tokens=100),
        enabled_tools=[],
        estimated_tokens=5_000,
        source="agent.md line 2",
    )
    assert len(issues) == 1
    assert "context tokens" in issues[0].message


def test_no_issues_when_capabilities_cover_needs() -> None:
    issues = capability_issues(
        "ok/x",
        Capabilities(tool_calls=True, max_context_tokens=200_000),
        enabled_tools=["read_inbox"],
        estimated_tokens=50,
        source="agent.md line 2",
    )
    assert issues == []


# --- full preflight with an injected registry ---------------------------------


class _StubProvider:
    contract_version = "1.0"
    capabilities = Capabilities(streaming=True)  # no tool_calls

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(stop_reason=StopReason.STOP)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        raise NotImplementedError
        yield  # pragma: no cover


class _FutureProvider(_StubProvider):
    contract_version = "9.0"  # newer than the harness -> unsupported


class _DeprecatedProvider(_StubProvider):
    contract_version = "0.9"  # previous major -> deprecated but still supported
    capabilities = Capabilities(tool_calls=True)


class _EP:
    def __init__(self, name: str, cls: type) -> None:
        self.name = name
        self._cls = cls

    def load(self) -> type:
        return self._cls


def _registry(name: str, cls: type) -> ProviderRegistry:
    return ProviderRegistry.discover(entry_points_=[_EP(name, cls)])  # type: ignore[list-item]


def test_preflight_flags_tool_calling_against_a_real_registry() -> None:
    config, agent = _config(TOOLED_AGENT)
    issues = preflight(config, agent, registry=_registry("toyless", _StubProvider))
    assert [i.message for i in issues if i.fatal]
    assert "does not declare tool calling" in issues[0].message


def test_preflight_provider_not_installed() -> None:
    config, agent = _config(TOOLED_AGENT)
    # An empty registry: the provider is not installed.
    issues = preflight(config, agent, registry=_registry("other", _StubProvider))
    assert len(issues) == 1
    assert "unknown provider 'toyless'" in issues[0].message


def test_unsupported_contract_fails_loud_at_discovery() -> None:
    # An unsupported plugin can't even register — discovery raises, so this is a
    # loud failure, not a quiet preflight issue.
    from wicklight.contracts import ProviderError

    with pytest.raises(ProviderError, match="contract"):
        _registry("toyless", _FutureProvider)


def test_deprecated_contract_is_a_non_fatal_warning() -> None:
    config, agent = _config(TOOLED_AGENT)
    issues = preflight(
        config, agent, registry=_registry("toyless", _DeprecatedProvider)
    )
    # The deprecated provider still declares tool calling, so the only issue is
    # the deprecation warning — and it is non-fatal.
    assert len(issues) == 1
    assert not issues[0].fatal
    assert "previous major" in issues[0].message


# --- the loop runs the same check at run start --------------------------------


class _ShouldNotRunProvider(_StubProvider):
    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise AssertionError("preflight should stop the run before any model call")


def test_run_stops_at_preflight_with_an_error_event() -> None:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-preflight-"))
    (run_dir / "agent.md").write_text(
        "---\nname: t\nmodels: { default: toyless/x }\n"
        "tools: { read_inbox: read }\n---\nGo.\n",
        encoding="utf-8",
    )
    agent = Agent.load(run_dir / "agent.md")
    result = agent.run(
        "go",
        provider=_ShouldNotRunProvider(),  # lacks tool calling
        world=MockWorld(),
        run_id="pf",
        runs_dir=run_dir,
    )
    assert result.status is RunStatus.ERROR
    assert result.steps == 0

    assert result.trace_path is not None
    events = read_trace(result.trace_path).events
    errors = [e for e in events if e.type == "error"]
    assert errors and errors[0].payload.where == "preflight"
    assert "tool calling" in errors[0].payload.message


def test_capable_provider_runs_normally() -> None:
    # A control: the fake provider declares tool calling, so preflight passes.
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-preflight-ok-"))
    (run_dir / "agent.md").write_text(
        "---\nname: t\nmodels: { default: fake/x }\n"
        "tools: { read_inbox: read }\n---\nGo.\n",
        encoding="utf-8",
    )
    agent = Agent.load(run_dir / "agent.md")
    script = "responses:\n  - text: done\n"
    result = agent.run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(script)),
        world=MockWorld(),
        run_id="pf-ok",
        runs_dir=run_dir,
    )
    assert result.completed
