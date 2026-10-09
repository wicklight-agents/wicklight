"""Tests for the `wicklight run` command and interruption (DTN-214)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from typer.testing import CliRunner

from wicklight.agent import Agent
from wicklight.cli import app
from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
)
from wicklight.tools import MockWorld
from wicklight.trace import RunStatus, read_trace

runner = CliRunner()

REPO = Path(__file__).parent.parent
INBOX = REPO / "examples" / "inbox.md"
SCRIPT = REPO / "examples" / "scripts" / "summarize.yaml"
WORLD = REPO / "examples" / "worlds" / "inbox.yaml"


def test_run_demo_streams_live_and_writes_a_valid_trace(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            str(INBOX),
            "summarize my inbox",
            "--fake",
            str(SCRIPT),
            "--world",
            str(WORLD),
            "--trace",
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    # --trace streamed each step live.
    assert "Step 0" in result.output
    assert "run_started" in result.output
    assert "tool_proposed" in result.output
    assert "read_inbox" in result.output
    assert "run_finished" in result.output

    # A single valid trace was written.
    traces = list(tmp_path.glob("*.jsonl"))
    assert len(traces) == 1
    assert read_trace(traces[0]).issues == []


def test_run_without_trace_shows_output_only(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            str(INBOX),
            "summarize",
            "--fake",
            str(SCRIPT),
            "--world",
            str(WORLD),
            "--runs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    # No live step events without --trace, but the final output and path show.
    assert "Step 0" not in result.output
    assert "trace:" in result.output


def test_run_missing_agent_file_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["run", "does/not/exist.md", "go", "--runs-dir", str(tmp_path)]
    )
    assert result.exit_code == 1


class _InterruptingProvider:
    """Simulates Ctrl+C landing during a model call."""

    contract_version = "1.0"
    capabilities = Capabilities()

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise KeyboardInterrupt

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        if False:  # pragma: no cover - not used
            yield  # type: ignore[unreachable]


def test_interrupt_records_a_clean_run_finished(tmp_path: Path) -> None:
    agent = Agent.load(INBOX)
    world = MockWorld.from_yaml(WORLD.read_text(encoding="utf-8"))
    result = agent.run(
        "go", provider=_InterruptingProvider(), world=world, runs_dir=tmp_path
    )

    assert result.status is RunStatus.STOPPED
    finished = read_trace(result.trace_path).by_type("run_finished")  # type: ignore[arg-type]
    assert finished
    assert "interrupted" in finished[0].explain
