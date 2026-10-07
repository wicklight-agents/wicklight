"""The committed sample trace: validation, coverage, and round-trip (DTN-203)."""

from __future__ import annotations

from pathlib import Path

from wicklight.trace import (
    TraceWriter,
    dump_trace_event,
    parse_trace_event,
    read_trace,
)

SAMPLE = Path(__file__).parent.parent / "examples" / "sample.jsonl"

# Every event type the harness can emit (DTN-199).
ALL_EVENT_TYPES = {
    "run_started",
    "context_built",
    "model_routed",
    "model_called",
    "model_responded",
    "tool_proposed",
    "policy_checked",
    "approval_requested",
    "approval_resolved",
    "tool_executed",
    "limit_hit",
    "error",
    "run_finished",
}


def test_sample_validates_with_no_issues() -> None:
    trace = read_trace(SAMPLE)
    assert trace.issues == []
    assert trace.events  # non-empty


def test_sample_covers_every_event_type() -> None:
    trace = read_trace(SAMPLE)
    assert {event.type for event in trace.events} == ALL_EVENT_TYPES


def test_sample_tells_the_expected_story() -> None:
    trace = read_trace(SAMPLE)
    # A policy block of a prompt-injection attempt...
    denials = [
        e for e in trace.by_type("policy_checked") if e.payload.decision.value == "deny"
    ]
    assert len(denials) == 1
    assert "attacker@evil.com" in denials[0].explain
    # ...an approval that was granted...
    resolved = trace.by_type("approval_resolved")
    assert resolved and resolved[0].payload.approved
    # ...and a run that ended by hitting a limit.
    finished = trace.by_type("run_finished")
    assert finished and finished[0].payload.status.value == "limit"


def test_every_event_round_trips_through_dump_and_parse() -> None:
    for event in read_trace(SAMPLE).events:
        assert parse_trace_event(dump_trace_event(event)) == event


def test_sample_round_trips_through_writer_and_reader(tmp_path: Path) -> None:
    original = read_trace(SAMPLE).events
    with TraceWriter("rt", root=tmp_path) as writer:
        for event in original:
            writer.write_event(event)
    assert read_trace(tmp_path / "rt.jsonl").events == original
