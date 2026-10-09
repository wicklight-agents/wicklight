"""Terminal rendering of trace events with Rich.

``render_event`` turns a single event into a colored line, so the same renderer
powers ``wicklight trace show`` and, later, live ``run --trace`` output (M5) —
it is built to render events one at a time. ``print_trace`` renders a whole
trace step by step, with blocked actions, approvals, and errors color-coded.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.console import Console
from rich.text import Text

from wicklight.trace.events import (
    ApprovalRequested,
    ApprovalResolved,
    Decision,
    ErrorEvent,
    LimitHit,
    PolicyChecked,
    TraceEvent,
)
from wicklight.trace.reader import Trace


def event_style(event: TraceEvent) -> str:
    """The Rich style for an event, highlighting the safety-relevant ones."""
    if isinstance(event, ErrorEvent):
        return "red"
    if isinstance(event, LimitHit):
        return "yellow"
    if isinstance(event, PolicyChecked):
        return "red" if event.payload.decision is Decision.DENY else "green"
    if isinstance(event, ApprovalRequested):
        return "yellow"
    if isinstance(event, ApprovalResolved):
        return "green" if event.payload.approved else "red"
    return ""


def render_event(event: TraceEvent) -> Text:
    """Render one event as a single colored line: ``<type>  <explain>``."""
    style = event_style(event)
    line = Text("  ")
    line.append(f"{event.type:<19}", style=style or "bold")
    line.append(event.explain, style=style)
    return line


def filter_events(
    events: Iterable[TraceEvent],
    *,
    step: int | None = None,
    event_type: str | None = None,
) -> list[TraceEvent]:
    """Filter events by step and/or event type."""
    result = list(events)
    if step is not None:
        result = [event for event in result if event.step == step]
    if event_type is not None:
        result = [event for event in result if event.type == event_type]
    return result


class StepPrinter:
    """Prints events one at a time with a step header, for live `run --trace`.

    Stateful so it only prints a ``Step N`` header when the step changes, giving
    the same grouped look as :func:`print_trace` as events stream in.
    """

    def __init__(self, console: Console) -> None:
        self._console = console
        self._step: int | None = None

    def __call__(self, event: TraceEvent) -> None:
        if event.step != self._step:
            self._step = event.step
            self._console.print(f"Step {event.step}", style="bold")
        self._console.print(render_event(event))


def print_trace(
    console: Console,
    trace: Trace,
    *,
    step: int | None = None,
    event_type: str | None = None,
) -> None:
    """Print a trace step by step, then any read issues."""
    events = filter_events(trace.events, step=step, event_type=event_type)
    current_step: int | None = None
    for event in events:
        if event.step != current_step:
            current_step = event.step
            console.print(f"Step {event.step}", style="bold")
        console.print(render_event(event))

    if trace.issues:
        console.print("issues:", style="bold")
        for issue in trace.issues:
            style = "yellow" if issue.severity == "warning" else "red"
            text = f"  {issue.severity}: line {issue.line}: {issue.message}"
            console.print(Text(text, style=style))
