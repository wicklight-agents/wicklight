"""Tests for `wicklight trace show` and the event renderer (DTN-202)."""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from wicklight.cli import app
from wicklight.trace import (
    ApprovalRequested,
    ApprovalRequestedPayload,
    ApprovalResolved,
    ApprovalResolvedPayload,
    Decision,
    ErrorEvent,
    ErrorPayload,
    PolicyChecked,
    PolicyCheckedPayload,
    RunStarted,
    RunStartedPayload,
    read_trace,
)
from wicklight.trace.console import event_style, print_trace

runner = CliRunner()

REPO_ROOT = Path(__file__).parent.parent
SAMPLE = REPO_ROOT / "examples" / "sample.jsonl"
GOLDEN = Path(__file__).parent / "fixtures" / "trace" / "sample_show.txt"

TS = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def _policy(decision: Decision) -> PolicyChecked:
    return PolicyChecked(
        run_id="r",
        step=1,
        timestamp=TS,
        explain="checked",
        payload=PolicyCheckedPayload(tool="t", policy="p", decision=decision),
    )


def test_render_matches_golden_snapshot() -> None:
    buf = io.StringIO()
    console = Console(file=buf, width=100, no_color=True, highlight=False)
    print_trace(console, read_trace(SAMPLE))
    assert buf.getvalue() == GOLDEN.read_text(encoding="utf-8")


def test_event_style_highlights_safety_events() -> None:
    assert event_style(_policy(Decision.DENY)) == "red"
    assert event_style(_policy(Decision.ALLOW)) == "green"
    assert (
        event_style(
            ErrorEvent(
                run_id="r",
                step=1,
                timestamp=TS,
                explain="e",
                payload=ErrorPayload(message="boom"),
            )
        )
        == "red"
    )
    assert (
        event_style(
            ApprovalRequested(
                run_id="r",
                step=1,
                timestamp=TS,
                explain="a",
                payload=ApprovalRequestedPayload(tool="t"),
            )
        )
        == "yellow"
    )
    assert (
        event_style(
            ApprovalResolved(
                run_id="r",
                step=1,
                timestamp=TS,
                explain="a",
                payload=ApprovalResolvedPayload(tool="t", approved=False),
            )
        )
        == "red"
    )
    # A plain event has no special style.
    assert (
        event_style(
            RunStarted(
                run_id="r",
                step=0,
                timestamp=TS,
                explain="s",
                payload=RunStartedPayload(agent="demo"),
            )
        )
        == ""
    )


def test_show_renders_cleanly_and_exits_zero() -> None:
    result = runner.invoke(app, ["trace", "show", str(SAMPLE)])
    assert result.exit_code == 0
    assert "Step 0" in result.output
    assert "run started for agent inbox-summarizer" in result.output
    assert "blocked: send_email by policy email_only_to" in result.output


def test_show_step_filter() -> None:
    result = runner.invoke(app, ["trace", "show", str(SAMPLE), "--step", "4"])
    assert result.exit_code == 0
    assert "tool_executed" in result.output
    assert "run_started" not in result.output


def test_show_type_filter() -> None:
    args = ["trace", "show", str(SAMPLE), "--type", "tool_executed"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0
    assert "tool_executed" in result.output
    assert "model_called" not in result.output


def test_show_json_emits_valid_events() -> None:
    result = runner.invoke(app, ["trace", "show", str(SAMPLE), "--json"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 13
    assert all(json.loads(ln)["type"] for ln in lines)


def test_show_json_respects_filter() -> None:
    result = runner.invoke(
        app, ["trace", "show", str(SAMPLE), "--type", "policy_checked", "--json"]
    )
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    types = [json.loads(ln)["type"] for ln in lines]
    assert types == ["policy_checked", "policy_checked"]


def test_show_missing_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["trace", "show", "does/not/exist.jsonl"])
    assert result.exit_code == 1


def test_trace_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["trace"])
    assert result.exit_code != 0
    assert "Usage" in result.output
