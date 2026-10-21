"""Where the viewer gets its runs: a mapping from run id to trace file.

The viewer never runs an agent; it only reads trace files that already exist.
A :class:`RunSource` resolves a run id to its :class:`~wicklight.trace.Trace`
and produces a short summary for the run list. Two constructors cover the
current needs: :meth:`RunSource.from_path` for a single trace file (what
``wicklight view <path>`` uses) and :meth:`RunSource.from_dir` for a directory
of traces (the ``runs/`` listing, DTN-250).

A run id is just the trace file's stem (``run_123.jsonl`` → ``run_123``), which
matches how the blob directory is named, so ids are stable and human-readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from wicklight.trace import RunStatus, Trace, read_trace
from wicklight.trace.events import (
    Decision,
    PolicyChecked,
    RunFinished,
    RunStarted,
)

_TRACE_SUFFIXES = (".jsonl.gz", ".jsonl")


def _no_models() -> list[str]:
    """Typed default factory for the models list (keeps pyright strict happy)."""
    return []


def run_id_for(path: Path) -> str:
    """The run id for a trace file — its name without a trace suffix."""
    name = path.name
    for suffix in _TRACE_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return path.stem


@dataclass(frozen=True)
class RunSummary:
    """A one-line description of a run for the run list."""

    run_id: str
    agent: str | None
    status: str | None
    steps: int | None
    cost_usd: float | None
    models: list[str] = field(default_factory=_no_models)
    blocks: int = 0
    approvals: int = 0
    started_at: str | None = None
    dry_run: bool = False
    counterfactual: bool = False

    def to_json(self) -> dict[str, object]:
        """A JSON-serializable view for the API."""
        return {
            "run_id": self.run_id,
            "agent": self.agent,
            "status": self.status,
            "steps": self.steps,
            "cost_usd": self.cost_usd,
            "models": self.models,
            "blocks": self.blocks,
            "approvals": self.approvals,
            "started_at": self.started_at,
            "dry_run": self.dry_run,
            "counterfactual": self.counterfactual,
        }


def summarize(run_id: str, trace: Trace) -> RunSummary:
    """Derive a :class:`RunSummary` from a run's events."""
    agent: str | None = None
    started_at: str | None = None
    dry_run = False
    counterfactual = False
    status: str | None = None
    steps: int | None = None
    cost_usd: float | None = None
    models: list[str] = []
    blocks = 0
    approvals = 0

    for event in trace.events:
        if isinstance(event, RunStarted):
            agent = event.payload.agent
            started_at = event.timestamp.isoformat()
            dry_run = event.payload.dry_run
            counterfactual = event.payload.counterfactual
        elif isinstance(event, RunFinished):
            status = event.payload.status.value
            steps = event.payload.steps
            cost_usd = event.payload.cost_usd
        elif isinstance(event, PolicyChecked):
            if event.payload.decision is Decision.DENY:
                blocks += 1
        elif event.type == "model_routed":
            model = getattr(event.payload, "model", None)
            if isinstance(model, str) and model not in models:
                models.append(model)
        elif event.type == "approval_resolved":
            if getattr(event.payload, "approved", False):
                approvals += 1

    # A run still in progress has no run_finished; report what we know.
    if status is None and trace.events:
        status = RunStatus.STOPPED.value if steps is None else status

    return RunSummary(
        run_id=run_id,
        agent=agent,
        status=status,
        steps=steps,
        cost_usd=cost_usd,
        models=models,
        blocks=blocks,
        approvals=approvals,
        started_at=started_at,
        dry_run=dry_run,
        counterfactual=counterfactual,
    )


class RunNotFoundError(LookupError):
    """Raised when a run id is not served by this source."""


class RunSource:
    """Resolves run ids to trace files the viewer can read."""

    def __init__(self, paths: dict[str, Path]) -> None:
        # run_id -> trace file path
        self._paths = dict(paths)

    @classmethod
    def from_path(cls, path: str | Path) -> RunSource:
        """A source serving a single trace file."""
        trace_path = Path(path)
        if not trace_path.exists():
            raise FileNotFoundError(f"trace not found: {trace_path}")
        return cls({run_id_for(trace_path): trace_path})

    @classmethod
    def from_dir(cls, runs_dir: str | Path) -> RunSource:
        """A source serving every trace file in a directory."""
        root = Path(runs_dir)
        paths: dict[str, Path] = {}
        if root.is_dir():
            for entry in root.iterdir():
                if entry.is_file() and entry.name.endswith(_TRACE_SUFFIXES):
                    paths[run_id_for(entry)] = entry
        return cls(paths)

    def run_ids(self) -> list[str]:
        """The run ids this source serves."""
        return list(self._paths)

    def path_for(self, run_id: str) -> Path:
        """The trace file for ``run_id``, or raise :class:`RunNotFoundError`."""
        try:
            return self._paths[run_id]
        except KeyError as exc:
            raise RunNotFoundError(run_id) from exc

    def trace_for(self, run_id: str) -> Trace:
        """Read and return the trace for ``run_id``."""
        return read_trace(self.path_for(run_id))

    def list_runs(self) -> list[RunSummary]:
        """Summarize every run, newest first by start time."""
        summaries = [
            summarize(run_id, read_trace(path)) for run_id, path in self._paths.items()
        ]
        summaries.sort(key=lambda summary: summary.started_at or "", reverse=True)
        return summaries
