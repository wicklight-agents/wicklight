"""Tests for the append-only JSONL trace writer and blob store (DTN-200)."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from wicklight.trace import (
    RunFinished,
    RunFinishedPayload,
    RunStarted,
    RunStartedPayload,
    RunStatus,
    TraceEvent,
    TraceWriter,
    parse_trace_event,
)

TS = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def _event(step: int, explain: str = "ok") -> RunStarted:
    return RunStarted(
        run_id="r",
        step=step,
        timestamp=TS,
        explain=explain,
        payload=RunStartedPayload(agent="demo"),
    )


def _read_events(path: Path) -> list[TraceEvent]:
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [parse_trace_event(json.loads(ln)) for ln in lines]


def test_default_and_configurable_paths(tmp_path: Path) -> None:
    writer = TraceWriter("run1", root=tmp_path)
    assert writer.path == tmp_path / "run1.jsonl"
    assert writer.blobs_dir == tmp_path / "run1" / "blobs"
    writer.close()


def test_events_round_trip(tmp_path: Path) -> None:
    events: list[TraceEvent] = [
        _event(0, "started"),
        RunFinished(
            run_id="r",
            step=1,
            timestamp=TS,
            explain="done",
            payload=RunFinishedPayload(status=RunStatus.COMPLETED, steps=1),
        ),
    ]
    with TraceWriter("r", root=tmp_path) as writer:
        for event in events:
            writer.write_event(event)

    assert _read_events(tmp_path / "r.jsonl") == events


def test_writer_appends_and_never_truncates(tmp_path: Path) -> None:
    with TraceWriter("r", root=tmp_path) as writer:
        writer.write_event(_event(0))
    # A second writer for the same run appends; it does not truncate.
    with TraceWriter("r", root=tmp_path) as writer:
        writer.write_event(_event(1))

    events = _read_events(tmp_path / "r.jsonl")
    assert [e.step for e in events] == [0, 1]


def test_blob_store_is_content_addressed_and_deduplicated(tmp_path: Path) -> None:
    writer = TraceWriter("r", root=tmp_path)
    first = writer.store_blob("a large model context")
    again = writer.store_blob("a large model context")
    other = writer.store_blob("different content")
    writer.close()

    assert first == again != other
    assert first == hashlib.sha256(b"a large model context").hexdigest()
    # Identical content stored once: exactly two blob files.
    blobs = sorted(p.name for p in (tmp_path / "r" / "blobs").iterdir())
    assert blobs == sorted({first, other})
    assert (tmp_path / "r" / "blobs" / first).read_bytes() == b"a large model context"


def test_redaction_hook_scrubs_events_and_blobs(tmp_path: Path) -> None:
    def redact(text: str) -> str:
        return text.replace("sk-SECRET", "***")

    with TraceWriter("r", root=tmp_path, redactor=redact) as writer:
        writer.write_event(_event(0, explain="used key sk-SECRET to call model"))
        digest = writer.store_blob("authorization: Bearer sk-SECRET")

    raw = (tmp_path / "r.jsonl").read_text(encoding="utf-8")
    assert "sk-SECRET" not in raw
    assert "***" in raw
    # The blob is addressed by the hash of its redacted bytes.
    blob = (tmp_path / "r" / "blobs" / digest).read_bytes()
    assert b"sk-SECRET" not in blob
    assert digest == hashlib.sha256(b"authorization: Bearer ***").hexdigest()


# Script run in a subprocess that writes N events (each flushed+fsynced) then
# hard-kills itself, to prove events written before a crash survive.
_CRASH_SCRIPT = """
import os, signal, sys
from datetime import datetime, timezone
from wicklight.trace import TraceWriter, RunStarted, RunStartedPayload

root = sys.argv[1]
ts = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
w = TraceWriter("crash", root=root)
for i in range(3):
    w.write_event(RunStarted(
        run_id="crash", step=i, timestamp=ts, explain=f"event {i}",
        payload=RunStartedPayload(agent="demo"),
    ))
os.kill(os.getpid(), signal.SIGKILL)  # no flush/close on the way out
"""


def test_events_before_a_crash_are_readable(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _CRASH_SCRIPT, str(tmp_path)],
        capture_output=True,
    )
    # The process killed itself with SIGKILL (-9); it never exited cleanly.
    assert result.returncode == -9

    events = _read_events(tmp_path / "crash.jsonl")
    assert [e.step for e in events] == [0, 1, 2]
    assert all(e.type == "run_started" for e in events)
