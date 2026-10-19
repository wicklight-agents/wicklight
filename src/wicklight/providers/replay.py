"""A provider that replays model responses recorded in a trace (DTN-236).

Every run records each model request and response to the blob store. The
:class:`ReplayProvider` reads those back and serves the responses in order, so
the core loop can run again with no network and no cost. If the loop sends a
request that differs from the one recorded at that step, replay stops and
reports the first divergence (step, field, recorded vs actual) rather than
silently returning a stale response.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    ProviderError,
    StreamDone,
    TextDelta,
    ToolCallDelta,
)
from wicklight.contracts.version import CONTRACT_VERSION
from wicklight.trace.events import ModelCalled, ModelResponded
from wicklight.trace.reader import Trace, read_trace


class ReplayError(ProviderError):
    """Raised when a replay is exhausted or the request diverges from the record."""


@dataclass(frozen=True)
class _Recorded:
    step: int
    request: ModelRequest | None
    response: ModelResponse


class ReplayProvider:
    """Serves recorded model responses from a trace, in order.

    Capabilities are declared permissively so the capability preflight never
    blocks a replay — the recorded run already passed its own checks.
    """

    contract_version = CONTRACT_VERSION
    capabilities = Capabilities(
        tool_calls=True,
        parallel_tool_calls=True,
        streaming=True,
    )

    def __init__(self, recorded: list[_Recorded]) -> None:
        self._recorded = recorded
        self._index = 0

    @classmethod
    def from_trace(cls, trace: str | Trace) -> ReplayProvider:
        """Build a replay provider from a trace file path or a read Trace."""
        resolved = trace if isinstance(trace, Trace) else read_trace(trace)
        return cls(_recorded_pairs(resolved))

    async def complete(self, request: ModelRequest) -> ModelResponse:
        recorded = self._advance()
        if recorded.request is not None:
            divergence = _first_divergence(recorded.request, request)
            if divergence is not None:
                field, recorded_value, actual_value = divergence
                raise ReplayError(
                    f"replay diverged at step {recorded.step}: {field} "
                    f"(recorded {recorded_value!r}, got {actual_value!r})"
                )
        return recorded.response

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        response = await self.complete(request)
        if response.content:
            yield TextDelta(text=response.content)
        for call in response.tool_calls:
            yield ToolCallDelta(tool_call=call)
        yield StreamDone(stop_reason=response.stop_reason, usage=response.usage)

    def _advance(self) -> _Recorded:
        if self._index >= len(self._recorded):
            raise ReplayError(
                f"replay exhausted: the loop made {self._index + 1} model calls "
                f"but the trace recorded only {len(self._recorded)}"
            )
        recorded = self._recorded[self._index]
        self._index += 1
        return recorded


def _recorded_pairs(trace: Trace) -> list[_Recorded]:
    """Pair each step's recorded request with its response, in trace order."""
    requests: dict[int, ModelRequest] = {}
    for event in trace.events:
        if isinstance(event, ModelCalled) and event.payload.request_ref is not None:
            requests[event.step] = ModelRequest.model_validate_json(
                trace.resolve_blob(event.payload.request_ref)
            )

    recorded: list[_Recorded] = []
    for event in trace.events:
        if not isinstance(event, ModelResponded):
            continue
        ref = event.payload.response_ref
        if ref is None:
            raise ReplayError(
                f"trace step {event.step} has no recorded response; it was "
                f"written before response recording (DTN-236) existed"
            )
        recorded.append(
            _Recorded(
                step=event.step,
                request=requests.get(event.step),
                response=ModelResponse.model_validate_json(trace.resolve_blob(ref)),
            )
        )
    return recorded


def _first_divergence(
    recorded: ModelRequest, actual: ModelRequest
) -> tuple[str, object, object] | None:
    """The first field where two requests differ, as (path, recorded, actual).

    Compared field by field over the known request shape — the messages are the
    part that matters for a faithful replay.
    """
    if recorded.model != actual.model:
        return ("model", recorded.model, actual.model)
    if len(recorded.messages) != len(actual.messages):
        return ("messages.length", len(recorded.messages), len(actual.messages))
    for index, (r, a) in enumerate(
        zip(recorded.messages, actual.messages, strict=True)
    ):
        if r != a:
            return (f"messages[{index}]", r, a)
    if recorded.tools != actual.tools:
        return ("tools", recorded.tools, actual.tools)
    if recorded.max_tokens != actual.max_tokens:
        return ("max_tokens", recorded.max_tokens, actual.max_tokens)
    if recorded.temperature != actual.temperature:
        return ("temperature", recorded.temperature, actual.temperature)
    if recorded.stop != actual.stop:
        return ("stop", recorded.stop, actual.stop)
    return None
