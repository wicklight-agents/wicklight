"""Recording model responses and the ReplayProvider (DTN-236)."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from wicklight.agent import Agent
from wicklight.contracts import Message, ModelRequest, Role
from wicklight.providers import FakeProvider, FakeScript, ReplayError, ReplayProvider
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools: { read_inbox: read }\n---\nSummarize the inbox.\n"
)
SCRIPT = (
    "responses:\n"
    "  - tool_calls:\n      - name: read_inbox\n"
    "  - text: two messages, nothing urgent\n"
)
WORLD = "inbox:\n  - sender: amy@acme.com\n    subject: Hi\n"


def _fresh_world() -> MockWorld:
    return MockWorld.from_yaml(WORLD)


#: Wall-clock fields that legitimately vary run to run, like the timestamp.
_VOLATILE = {"duration_ms"}


def _comparable(events: list[TraceEvent]) -> list[tuple[str, int, str, dict[str, Any]]]:
    # Everything but the volatile envelope fields (run_id, timestamp) and
    # wall-clock timings. Content-addressed blob refs are included: identical
    # content hashes identically, so matching refs prove identical payloads.
    comparable: list[tuple[str, int, str, dict[str, Any]]] = []
    for event in events:
        payload = {
            key: value
            for key, value in event.payload.model_dump().items()
            if key not in _VOLATILE
        }
        comparable.append((event.type, event.step, event.explain, payload))
    return comparable


def _record_run() -> Path:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-record-"))
    (run_dir / "agent.md").write_text(AGENT, encoding="utf-8")
    result = Agent.load(run_dir / "agent.md").run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(SCRIPT)),
        world=_fresh_world(),
        run_id="original",
        runs_dir=run_dir,
    )
    assert result.trace_path is not None
    return result.trace_path


# --- recording ----------------------------------------------------------------


def test_run_records_request_and_response_blobs() -> None:
    trace = read_trace(_record_run())
    called = [e for e in trace.events if e.type == "model_called"]
    responded = [e for e in trace.events if e.type == "model_responded"]
    assert called and all(e.payload.request_ref for e in called)
    assert responded and all(e.payload.response_ref for e in responded)
    # The blobs resolve to valid neutral types.
    request = ModelRequest.model_validate_json(
        trace.resolve_blob(called[0].payload.request_ref)
    )
    assert request.model == "fake/x"  # the loop records the configured model id


# --- replay identity (the done-when) ------------------------------------------


def test_trace_replays_to_an_identical_event_sequence() -> None:
    original = read_trace(_record_run())

    replay_dir = Path(tempfile.mkdtemp(prefix="wicklight-replay-"))
    (replay_dir / "agent.md").write_text(AGENT, encoding="utf-8")
    replayed = Agent.load(replay_dir / "agent.md").run(
        "go",
        provider=ReplayProvider.from_trace(original),
        world=_fresh_world(),
        run_id="replayed",
        runs_dir=replay_dir,
    )
    assert replayed.trace_path is not None

    assert _comparable(original.events) == _comparable(
        read_trace(replayed.trace_path).events
    )


# --- mismatch and exhaustion --------------------------------------------------


def _first_recorded_request(trace) -> ModelRequest:  # type: ignore[no-untyped-def]
    called = next(e for e in trace.events if e.type == "model_called")
    return ModelRequest.model_validate_json(
        trace.resolve_blob(called.payload.request_ref)
    )


def test_mismatch_reports_the_first_divergence() -> None:
    trace = read_trace(_record_run())
    provider = ReplayProvider.from_trace(trace)
    # Take the real recorded request and change only a message — the first (and
    # only) divergence is then that message.
    recorded = _first_recorded_request(trace)
    diverged = recorded.model_copy(
        update={"messages": [Message(role=Role.USER, content="different")]}
    )

    try:
        asyncio.run(provider.complete(diverged))
    except ReplayError as exc:
        assert "diverged at step" in str(exc)
        assert "messages" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a ReplayError")


def test_replay_exhaustion_is_reported() -> None:
    # One recorded response, asked for twice (the first with the real request).
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-exhaust-"))
    (run_dir / "agent.md").write_text(
        "---\nname: t\nmodels: { default: fake/x }\ntools: {}\n---\nGo.\n",
        encoding="utf-8",
    )
    result = Agent.load(run_dir / "agent.md").run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml("responses:\n  - text: done\n")),
        world=MockWorld(),
        run_id="one",
        runs_dir=run_dir,
    )
    assert result.trace_path is not None
    trace = read_trace(result.trace_path)
    provider = ReplayProvider.from_trace(trace)
    recorded = _first_recorded_request(trace)

    async def go() -> None:
        await provider.complete(recorded)  # serves the one recorded response
        await provider.complete(recorded)  # nothing left

    try:
        asyncio.run(go())
    except ReplayError as exc:
        assert "exhausted" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a ReplayError")


def test_trace_without_recorded_responses_is_rejected() -> None:
    # The hand-written sample predates response recording.
    try:
        ReplayProvider.from_trace("examples/sample.jsonl")
    except ReplayError as exc:
        assert "no recorded response" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a ReplayError")
