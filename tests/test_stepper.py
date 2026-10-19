"""The replay stepper and `wicklight replay` command (DTN-237)."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from wicklight.cli import app
from wicklight.trace import read_trace
from wicklight.trace.stepper import (
    ReplayStepper,
    is_approval,
    is_block,
    is_error,
    run_stepper,
)

runner = CliRunner()
SAMPLE = Path(__file__).parent.parent / "examples" / "sample.jsonl"


def _events():
    return read_trace(SAMPLE).events


# --- pure navigation ----------------------------------------------------------


def test_next_and_prev_respect_bounds() -> None:
    stepper = ReplayStepper(_events())
    assert stepper.index == 0
    assert not stepper.prev()  # already at the start
    assert stepper.next()
    assert stepper.index == 1
    # Walk to the end; next() returns False at the last event.
    while stepper.next():
        pass
    assert stepper.index == stepper.total - 1
    assert not stepper.next()


def test_jump_to_step() -> None:
    stepper = ReplayStepper(_events())
    assert stepper.jump_to_step(3)
    assert stepper.current() is not None and stepper.current().step == 3
    assert not stepper.jump_to_step(999)  # no such step


def test_jump_to_next_block_and_error() -> None:
    # sample.jsonl has an error at step 1 and a policy deny (block) at step 3.
    stepper = ReplayStepper(_events())
    assert stepper.jump_to_next(is_error)
    assert is_error(stepper.current())  # type: ignore[arg-type]

    stepper = ReplayStepper(_events())
    assert stepper.jump_to_next(is_block)
    current = stepper.current()
    assert current is not None and is_block(current)
    assert current.step == 3

    # sample.jsonl also has an approval at step 4.
    stepper = ReplayStepper(_events())
    assert stepper.jump_to_next(is_approval)
    current = stepper.current()
    assert current is not None and is_approval(current)


# --- interactive loop (injected reader + captured console) --------------------


def _scripted(commands: list[str]) -> Callable[[str], str]:
    it = iter(commands)

    def read(_prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    return read


def _capture() -> Console:
    return Console(file=io.StringIO(), width=100, no_color=True)


def test_run_stepper_steps_and_quits() -> None:
    console = _capture()
    stepper = ReplayStepper(_events())
    # Jump to the block, then quit.
    run_stepper(stepper, console, _scripted(["b", "q"]))
    output = console.file.getvalue()  # type: ignore[attr-defined]
    assert "policy_checked" in output
    assert "blocked" in output
    # Stopped at the deny step.
    assert stepper.current() is not None and is_block(stepper.current())  # type: ignore[arg-type]


def test_run_stepper_handles_unknown_command() -> None:
    console = _capture()
    run_stepper(ReplayStepper(_events()), console, _scripted(["wat", "q"]))
    assert "unknown command" in console.file.getvalue()  # type: ignore[attr-defined]


def test_run_stepper_eof_exits() -> None:
    console = _capture()
    # No commands: the first read raises EOFError and the loop exits cleanly.
    run_stepper(ReplayStepper(_events()), console, _scripted([]))
    assert "run_started" in console.file.getvalue()  # type: ignore[attr-defined]


# --- the command --------------------------------------------------------------


def test_replay_all_prints_the_whole_trace() -> None:
    result = runner.invoke(app, ["replay", str(SAMPLE), "--all"])
    assert result.exit_code == 0
    assert "run_started" in result.output
    assert "policy_checked" in result.output


def test_replay_missing_trace_exits_nonzero() -> None:
    result = runner.invoke(app, ["replay", "does/not/exist.jsonl", "--all"])
    assert result.exit_code == 1
