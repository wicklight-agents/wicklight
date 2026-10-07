"""Append-only JSONL trace writer with a content-addressed blob store.

The writer appends one JSON line per event and flushes it to disk immediately,
so a crash or kill switch never loses an earlier step. It never truncates or
rewrites an existing file.

Large payloads (full model contexts, big tool outputs) are not inlined. The
caller stores them with :meth:`TraceWriter.store_blob`, which writes the content
once to ``runs/<run_id>/blobs/<sha256>`` (identical content is stored once) and
returns the hash to put in an event's ``*_ref`` field. ``store_blob`` fully
persists the blob before returning, so if the caller stores a blob and then
writes the event that references it, a crash can never leave a dangling
reference.

A redaction hook runs over every line and every blob before it touches disk, so
secrets can never be written. The default hook is a no-op; the real secret
patterns are supplied later (DTN-227).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from types import TracebackType

from wicklight.trace.events import TraceEvent, dump_trace_event

#: A hook that rewrites outgoing text to strip secrets. Must be idempotent.
Redactor = Callable[[str], str]

#: Suggested size (bytes) above which a payload belongs in the blob store rather
#: than inline. The decision to externalize is the caller's; this is a default.
DEFAULT_BLOB_THRESHOLD = 4096


def _identity(text: str) -> str:
    return text


class TraceWriter:
    """Writes a run's events to ``<root>/<run_id>.jsonl``, append-only."""

    def __init__(
        self,
        run_id: str,
        *,
        root: str | Path = "runs",
        redactor: Redactor | None = None,
    ) -> None:
        self.run_id = run_id
        self.root = Path(root)
        self.path = self.root / f"{run_id}.jsonl"
        self.blobs_dir = self.root / run_id / "blobs"
        self._redactor: Redactor = redactor or _identity

        self.root.mkdir(parents=True, exist_ok=True)
        # Append mode never truncates an existing trace.
        self._file = self.path.open("a", encoding="utf-8")

    def write_event(self, event: TraceEvent) -> None:
        """Append one event as a JSON line and flush it durably to disk."""
        line = json.dumps(dump_trace_event(event), ensure_ascii=False)
        line = self._redactor(line)
        if "\n" in line:
            raise ValueError("a trace event must serialize to a single line")
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def store_blob(self, content: str) -> str:
        """Store ``content`` once, returning its sha256 hash for an event ``*_ref``.

        The blob is fully written and fsynced before this returns, and identical
        content is stored only once.
        """
        data = self._redactor(content).encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        blob_path = self.blobs_dir / digest
        if not blob_path.exists():
            self.blobs_dir.mkdir(parents=True, exist_ok=True)
            _write_atomically(blob_path, data)
        return digest

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> TraceWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _write_atomically(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via a temp file + fsync + atomic rename."""
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)
