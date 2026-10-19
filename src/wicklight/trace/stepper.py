"""Step through a past run event by event (DTN-237).

``ReplayStepper`` holds a cursor over a trace's events with pure navigation —
next, previous, jump to a step, jump to the next block/approval/error. It reads
nothing and runs nothing, so stepping a trace has no model calls and no tool
side effects. ``run_stepper`` drives it as an interactive terminal loop; the
reader and console are injected so the loop is testable without a real TTY.
"""

from __future__ import annotations

from collections.abc import Callable

from rich.console import Console

from wicklight.trace.console import render_event
from wicklight.trace.events import (
    ApprovalRequested,
    ApprovalResolved,
    Decision,
    ErrorEvent,
    PolicyChecked,
    TraceEvent,
)

HELP = "commands: [n]ext · [p]rev · <step#> · [b]lock · [a]pproval · [e]rror · [q]uit"


def is_block(event: TraceEvent) -> bool:
    return isinstance(event, PolicyChecked) and event.payload.decision is Decision.DENY


def is_approval(event: TraceEvent) -> bool:
    return isinstance(event, (ApprovalRequested, ApprovalResolved))


def is_error(event: TraceEvent) -> bool:
    return isinstance(event, ErrorEvent)


class ReplayStepper:
    """A cursor over a trace's events, with pure navigation moves."""

    def __init__(self, events: list[TraceEvent]) -> None:
        self._events = events
        self._index = 0

    @property
    def index(self) -> int:
        return self._index

    @property
    def total(self) -> int:
        return len(self._events)

    def current(self) -> TraceEvent | None:
        return self._events[self._index] if self._events else None

    def next(self) -> bool:
        if self._index < len(self._events) - 1:
            self._index += 1
            return True
        return False

    def prev(self) -> bool:
        if self._index > 0:
            self._index -= 1
            return True
        return False

    def jump_to_step(self, step: int) -> bool:
        """Move to the first event recorded at ``step``."""
        for i, event in enumerate(self._events):
            if event.step == step:
                self._index = i
                return True
        return False

    def jump_to_next(self, predicate: Callable[[TraceEvent], bool]) -> bool:
        """Move to the next event after the cursor that matches ``predicate``."""
        for i in range(self._index + 1, len(self._events)):
            if predicate(self._events[i]):
                self._index = i
                return True
        return False


def run_stepper(
    stepper: ReplayStepper,
    console: Console,
    readline: Callable[[str], str],
) -> None:
    """Drive the stepper as an interactive loop until the user quits (or EOF)."""
    if stepper.current() is None:
        console.print("(empty trace)")
        return

    _show(stepper, console)
    console.print(f"[dim]{HELP}[/]")
    while True:
        try:
            command = readline("replay> ").strip().lower()
        except EOFError:
            return
        if command in {"q", "quit"}:
            return
        moved = _dispatch(stepper, command)
        if moved is None:
            console.print(f"unknown command: {command!r}")
            console.print(f"[dim]{HELP}[/]")
            continue
        if not moved:
            console.print("[dim](no matching event)[/]")
        _show(stepper, console)


def _dispatch(stepper: ReplayStepper, command: str) -> bool | None:
    """Apply a command; return whether the cursor moved, or None if unknown."""
    if command in {"", "n", "next"}:
        return stepper.next()
    if command in {"p", "prev", "previous"}:
        return stepper.prev()
    if command in {"b", "block"}:
        return stepper.jump_to_next(is_block)
    if command in {"a", "approval"}:
        return stepper.jump_to_next(is_approval)
    if command in {"e", "error"}:
        return stepper.jump_to_next(is_error)
    if command.isdigit():
        return stepper.jump_to_step(int(command))
    return None


def _show(stepper: ReplayStepper, console: Console) -> None:
    event = stepper.current()
    if event is None:
        return
    console.print(f"[dim][{stepper.index + 1}/{stepper.total}] step {event.step}[/]")
    console.print(render_event(event))
