"""Tests for the scripted FakeProvider (DTN-206)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from wicklight.contracts import (
    Message,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderRegistry,
    Role,
    StopReason,
)
from wicklight.providers import FakeProvider, FakeScript, FakeScriptError

REPO_ROOT = Path(__file__).parent.parent
SUMMARIZE = REPO_ROOT / "examples" / "scripts" / "summarize.yaml"


def _request(*messages: Message, model: str = "fake/summarize") -> ModelRequest:
    return ModelRequest(model=model, messages=list(messages))


def _user(text: str) -> Message:
    return Message(role=Role.USER, content=text)


def _tool_result(text: str = "5 emails") -> Message:
    return Message(role=Role.TOOL, content=text, trusted=False, tool_call_id="c1")


def _complete(provider: FakeProvider, request: ModelRequest) -> ModelResponse:
    return asyncio.run(provider.complete(request))


def test_replays_summarize_script_in_order() -> None:
    provider = FakeProvider(FakeScript.from_path(SUMMARIZE))

    first = _complete(provider, _request(_user("summarize my inbox")))
    assert first.stop_reason is StopReason.TOOL_USE
    assert [c.name for c in first.tool_calls] == ["read_inbox"]

    # Provide the tool result, then the second scripted response is the summary.
    second = _complete(provider, _request(_user("summarize"), _tool_result()))
    assert second.stop_reason is StopReason.STOP
    assert "5 emails" in second.content
    assert second.tool_calls == []


def test_exhausted_script_fails_loudly() -> None:
    provider = FakeProvider(FakeScript.from_path(SUMMARIZE))
    _complete(provider, _request(_user("go")))
    _complete(provider, _request(_user("go"), _tool_result()))
    with pytest.raises(FakeScriptError, match="exhausted"):
        _complete(provider, _request(_user("go"), _tool_result()))


def test_missing_tool_result_names_the_step() -> None:
    provider = FakeProvider(FakeScript.from_path(SUMMARIZE))
    _complete(provider, _request(_user("go")))  # step 1 emits a tool call
    # Next request has no tool result -> loud, step-naming error.
    with pytest.raises(FakeScriptError, match="step 1 emitted tool calls"):
        _complete(provider, _request(_user("still going")))


def test_scripted_error_raises_provider_error() -> None:
    script = FakeScript.from_yaml("responses:\n  - error: boom\n")
    provider = FakeProvider(script)
    with pytest.raises(ProviderError, match=r"fake provider error .*step 1.*: boom"):
        _complete(provider, _request(_user("go")))


def test_no_script_configured_fails_loudly() -> None:
    with pytest.raises(FakeScriptError, match="no fake script configured"):
        _complete(FakeProvider(), _request(_user("go")))


def test_stream_reconstructs_text_then_done() -> None:
    script = FakeScript.from_yaml('responses:\n  - text: "hello world from the fake"\n')
    provider = FakeProvider(script)

    async def drain() -> tuple[str, list[str]]:
        text = ""
        types: list[str] = []
        stream: AsyncIterator[ModelEvent] = provider.stream(_request(_user("hi")))
        async for event in stream:
            types.append(event.type)
            if event.type == "text_delta":
                text += event.text
        return text, types

    text, types = asyncio.run(drain())
    assert text == "hello world from the fake"
    assert types[-1] == "done"
    assert types[:-1] == ["text_delta"] * (len(types) - 1)


def test_invalid_script_is_rejected() -> None:
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError on extra key
        FakeScript.from_yaml("responses:\n  - text: hi\n    bogus: 1\n")


def test_registered_and_resolvable_as_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WICKLIGHT_FAKE_SCRIPT", str(SUMMARIZE))
    provider, model = ProviderRegistry.discover().resolve("fake/summarize")
    assert model == "summarize"
    # The discovered provider reads its script from the env var and replays it.
    response = _complete(provider, _request(_user("go")))  # type: ignore[arg-type]
    assert response.tool_calls[0].name == "read_inbox"
