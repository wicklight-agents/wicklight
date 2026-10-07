"""Validating trace reader — turn a JSONL trace back into typed events.

Reading is forgiving on purpose: a trace is often read while or just after a
run, possibly after a crash. Every line is validated; a bad line is reported
with its line number and reason but does not discard the events around it, and a
truncated final line (a half-written line from a crash) is a warning, not an
error. Gzipped traces (``.jsonl.gz``) are read transparently. Blob references
are resolved lazily, with a clear error if a referenced blob is missing.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from wicklight.trace.events import TraceEvent, parse_trace_event


class TraceReadError(Exception):
    """Raised for unrecoverable read problems (missing file or blob)."""


@dataclass(frozen=True)
class TraceIssue:
    """A problem found while reading a trace line."""

    line: int
    message: str
    severity: Literal["error", "warning"]


@dataclass(frozen=True)
class Trace:
    """A read trace: the valid events, any issues, and blob resolution."""

    events: list[TraceEvent]
    issues: list[TraceIssue]
    path: Path
    blobs_dir: Path

    def by_type(self, event_type: str) -> list[TraceEvent]:
        """Events whose ``type`` equals ``event_type``."""
        return [event for event in self.events if event.type == event_type]

    def by_step(self, step: int) -> list[TraceEvent]:
        """Events recorded at ``step``."""
        return [event for event in self.events if event.step == step]

    def resolve_blob(self, ref: str) -> str:
        """Read a referenced blob's content, or raise if it is missing."""
        blob_path = self.blobs_dir / ref
        try:
            return blob_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise TraceReadError(f"referenced blob is missing: {blob_path}") from exc


def read_trace(path: str | Path) -> Trace:
    """Read and validate a trace file into a :class:`Trace`."""
    path = Path(path)
    if not path.exists():
        raise TraceReadError(f"trace not found: {path}")

    events: list[TraceEvent] = []
    issues: list[TraceIssue] = []
    with _open_text(path) as handle:
        raw_lines = handle.readlines()

    for number, raw in enumerate(raw_lines, start=1):
        has_newline = raw.endswith("\n")
        line = raw.rstrip("\n")
        if not line.strip():
            continue
        is_last = number == len(raw_lines)
        try:
            event = parse_trace_event(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as exc:
            detail = _brief(exc)
            # A final line with no trailing newline is a half-written line from a
            # crash — warn and stop rather than treating it as corruption.
            if is_last and not has_newline:
                message = f"ignored truncated final line: {detail}"
                issues.append(TraceIssue(number, message, "warning"))
                break
            issues.append(TraceIssue(number, f"invalid trace line: {detail}", "error"))
            continue
        events.append(event)

    return Trace(events=events, issues=issues, path=path, blobs_dir=_blobs_dir(path))


def _open_text(path: Path) -> TextIOWrapper:
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _blobs_dir(path: Path) -> Path:
    name = path.name
    for suffix in (".gz", ".jsonl"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return path.parent / name / "blobs"


def _brief(exc: json.JSONDecodeError | ValidationError) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        return f"{loc}: {first['msg']}" if loc else first["msg"]
    return str(exc)
