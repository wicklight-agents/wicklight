"""Tests for the validating trace reader (DTN-201)."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from wicklight.trace import (
    RunFinished,
    RunFinishedPayload,
    RunStarted,
    RunStartedPayload,
    RunStatus,
    ToolProposed,
    ToolProposedPayload,
    TraceEvent,
    TraceReadError,
    TraceWriter,
    dump_trace_event,
    read_trace,
)

TS = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def _started(step: int) -> RunStarted:
    return RunStarted(
        run_id="r",
        step=step,
        timestamp=TS,
        explain=f"step {step}",
        payload=RunStartedPayload(agent="demo"),
    )


def _line(event: TraceEvent) -> str:
    return json.dumps(dump_trace_event(event), ensure_ascii=False)


def test_reads_a_valid_trace(tmp_path: Path) -> None:
    events: list[TraceEvent] = [
        _started(0),
        ToolProposed(
            run_id="r",
            step=1,
            timestamp=TS,
            explain="proposed send_email",
            payload=ToolProposedPayload(tool="send_email"),
        ),
        RunFinished(
            run_id="r",
            step=2,
            timestamp=TS,
            explain="done",
            payload=RunFinishedPayload(status=RunStatus.COMPLETED, steps=2),
        ),
    ]
    with TraceWriter("r", root=tmp_path) as writer:
        for event in events:
            writer.write_event(event)

    trace = read_trace(tmp_path / "r.jsonl")
    assert trace.events == events
    assert trace.issues == []


def test_reads_gzipped_trace(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl.gz"
    events = [_started(0), _started(1)]
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for event in events:
            handle.write(_line(event) + "\n")

    trace = read_trace(path)
    assert [e.step for e in trace.events] == [0, 1]
    assert trace.issues == []
    # Blob dir is derived correctly even through the .jsonl.gz suffix.
    assert trace.blobs_dir == tmp_path / "r" / "blobs"


def test_corrupt_middle_line_keeps_surrounding_events(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    path.write_text(
        _line(_started(0)) + "\n" + "{not valid json\n" + _line(_started(2)) + "\n",
        encoding="utf-8",
    )
    trace = read_trace(path)

    # Events before and after the bad line are kept; the bad line is reported.
    assert [e.step for e in trace.events] == [0, 2]
    assert len(trace.issues) == 1
    assert trace.issues[0].line == 2
    assert trace.issues[0].severity == "error"


def test_truncated_final_line_is_a_warning(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    # Two complete lines, then a half-written final line with no trailing newline.
    path.write_text(
        _line(_started(0)) + "\n" + _line(_started(1)) + "\n" + '{"v": 1, "run_id"',
        encoding="utf-8",
    )
    trace = read_trace(path)

    assert [e.step for e in trace.events] == [0, 1]
    assert len(trace.issues) == 1
    assert trace.issues[0].line == 3
    assert trace.issues[0].severity == "warning"


def test_resolves_blobs_and_reports_missing(tmp_path: Path) -> None:
    writer = TraceWriter("r", root=tmp_path)
    ref = writer.store_blob("a large model context")
    writer.close()

    trace = read_trace(tmp_path / "r.jsonl")
    assert trace.resolve_blob(ref) == "a large model context"
    with pytest.raises(TraceReadError, match="missing"):
        trace.resolve_blob("0" * 64)


def test_missing_trace_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TraceReadError, match="not found"):
        read_trace(tmp_path / "nope.jsonl")


def test_filter_helpers(tmp_path: Path) -> None:
    path = tmp_path / "r.jsonl"
    events: list[TraceEvent] = [
        _started(0),
        ToolProposed(
            run_id="r",
            step=1,
            timestamp=TS,
            explain="p",
            payload=ToolProposedPayload(tool="t"),
        ),
        ToolProposed(
            run_id="r",
            step=1,
            timestamp=TS,
            explain="p2",
            payload=ToolProposedPayload(tool="t2"),
        ),
    ]
    path.write_text("".join(_line(e) + "\n" for e in events), encoding="utf-8")
    trace = read_trace(path)

    assert [e.step for e in trace.by_type("tool_proposed")] == [1, 1]
    assert [e.type for e in trace.by_step(0)] == ["run_started"]
