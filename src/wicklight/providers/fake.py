"""A scripted provider for deterministic tests and demos.

``FakeProvider`` replays a YAML script of model responses in order — text, tool
calls, errors, and optional delays — through both ``complete`` and ``stream``.
It never calls a network. It fails loudly, naming the script step, when the
agent asks for more responses than the script has, or when a step's tool call is
not followed by a tool result in the next request. It is registered under the
``fake`` provider name, so agent files can use ``fake/<model>`` ids.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML

from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    ProviderError,
    Role,
    StopReason,
    StreamDone,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    Usage,
)
from wicklight.contracts.version import CONTRACT_VERSION

_STRICT = ConfigDict(extra="forbid")
_STREAM_CHUNK = 8  # characters per streamed text delta


class FakeScriptError(ProviderError):
    """Raised when the agent's calls don't match the fake script."""


class ScriptedToolCall(BaseModel):
    model_config = _STRICT

    name: str
    arguments: dict[str, Any] = {}
    id: str | None = None


class ScriptedResponse(BaseModel):
    """One scripted model response."""

    model_config = _STRICT

    text: str = ""
    tool_calls: list[ScriptedToolCall] = []
    error: str | None = None
    delay: float = 0.0
    stop_reason: StopReason | None = None


class FakeScript(BaseModel):
    """An ordered list of responses the FakeProvider replays."""

    model_config = _STRICT

    responses: list[ScriptedResponse]

    @classmethod
    def from_yaml(cls, text: str) -> FakeScript:
        yaml: Any = YAML(typ="safe")
        return cls.model_validate(yaml.load(text))

    @classmethod
    def from_path(cls, path: str | Path) -> FakeScript:
        return cls.from_yaml(Path(path).read_text(encoding="utf-8"))


class FakeProvider:
    """A provider that replays a :class:`FakeScript`."""

    contract_version = CONTRACT_VERSION
    capabilities = Capabilities(streaming=True, parallel_tool_calls=True)

    def __init__(self, script: FakeScript | None = None) -> None:
        self._script = script
        self._index = 0
        self._awaiting_tool_result = False
        self._awaiting_step = 0

    async def complete(self, request: ModelRequest) -> ModelResponse:
        step = self._advance(request)
        await self._delay(step)
        self._raise_if_error(step)
        return self._response(step, request)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        step = self._advance(request)
        await self._delay(step)
        self._raise_if_error(step)
        for start in range(0, len(step.text), _STREAM_CHUNK):
            yield TextDelta(text=step.text[start : start + _STREAM_CHUNK])
        for call in self._tool_calls(step):
            yield ToolCallDelta(tool_call=call)
        yield StreamDone(stop_reason=self._stop(step), usage=self._usage(step, request))

    # --- internals ------------------------------------------------------------

    def _advance(self, request: ModelRequest) -> ScriptedResponse:
        script = self._require_script()
        self._check_pending_tool_result(request)
        if self._index >= len(script.responses):
            raise FakeScriptError(
                f"fake script exhausted: the agent made {self._index + 1} model "
                f"calls but the script has only {len(script.responses)} responses"
            )
        step = script.responses[self._index]
        self._index += 1
        self._awaiting_tool_result = bool(step.tool_calls)
        self._awaiting_step = self._index
        return step

    def _check_pending_tool_result(self, request: ModelRequest) -> None:
        if self._awaiting_tool_result and not any(
            message.role is Role.TOOL for message in request.messages
        ):
            raise FakeScriptError(
                f"fake script step {self._awaiting_step} emitted tool calls, but "
                f"the next model request carries no tool result"
            )

    def _require_script(self) -> FakeScript:
        if self._script is None:
            env_path = os.environ.get("WICKLIGHT_FAKE_SCRIPT")
            if not env_path:
                raise FakeScriptError(
                    "no fake script configured; construct FakeProvider(script=...) "
                    "or set WICKLIGHT_FAKE_SCRIPT to a script path"
                )
            self._script = FakeScript.from_path(env_path)
        return self._script

    def _raise_if_error(self, step: ScriptedResponse) -> None:
        if step.error is not None:
            raise ProviderError(
                f"fake provider error (script step {self._index}): {step.error}"
            )

    def _response(self, step: ScriptedResponse, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            content=step.text,
            tool_calls=self._tool_calls(step),
            stop_reason=self._stop(step),
            usage=self._usage(step, request),
        )

    def _tool_calls(self, step: ScriptedResponse) -> list[ToolCall]:
        return [
            ToolCall(
                id=call.id or f"call_{self._index}_{position}",
                name=call.name,
                arguments=call.arguments,
            )
            for position, call in enumerate(step.tool_calls)
        ]

    def _stop(self, step: ScriptedResponse) -> StopReason:
        if step.stop_reason is not None:
            return step.stop_reason
        return StopReason.TOOL_USE if step.tool_calls else StopReason.STOP

    def _usage(self, step: ScriptedResponse, request: ModelRequest) -> Usage:
        input_tokens = sum(len(message.content.split()) for message in request.messages)
        return Usage(input_tokens=input_tokens, output_tokens=len(step.text.split()))

    async def _delay(self, step: ScriptedResponse) -> None:
        if step.delay > 0:
            await asyncio.sleep(step.delay)
