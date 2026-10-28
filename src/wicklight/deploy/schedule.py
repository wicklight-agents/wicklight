"""A small cron matcher for deploy-file schedules (DTN-256).

Just enough of standard 5-field cron (minute hour day-of-month month
day-of-week) to drive the supervisor's scheduler at minute granularity:
``*``, single values, comma lists, ``a-b`` ranges, and ``*/step`` (or
``a-b/step``). Day-of-week is Sunday=0 (7 also means Sunday). Kept in-repo and
tested rather than adding a dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# The search window for the next fire time: a little over a year of minutes.
_MAX_LOOKAHEAD_MINUTES = 366 * 24 * 60


def cron_matches(expr: str, when: datetime) -> bool:
    """Whether ``when`` (to the minute) satisfies the 5-field cron ``expr``."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"expected a 5-field cron expression, got {expr!r}")
    minute, hour, dom, month, dow = fields

    if not _matches(minute, when.minute, 0, 59):
        return False
    if not _matches(hour, when.hour, 0, 23):
        return False
    if not _matches(month, when.month, 1, 12):
        return False

    cron_dow = (when.weekday() + 1) % 7  # Python Mon=0..Sun=6 → cron Sun=0..Sat=6
    dom_ok = _matches(dom, when.day, 1, 31)
    dow_ok = _matches(dow, cron_dow, 0, 7) or (cron_dow == 0 and _matches(dow, 7, 0, 7))
    # Standard cron: when both day-of-month and day-of-week are restricted, a
    # day matches if EITHER does; otherwise both must.
    if dom.strip() != "*" and dow.strip() != "*":
        return dom_ok or dow_ok
    return dom_ok and dow_ok


def next_fire(expr: str, after: datetime) -> datetime | None:
    """The first minute strictly after ``after`` that matches ``expr``."""
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(_MAX_LOOKAHEAD_MINUTES):
        if cron_matches(expr, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def _matches(spec: str, value: int, low: int, high: int) -> bool:
    for part in spec.split(","):
        step = 1
        rng = part
        if "/" in part:
            rng, _, step_text = part.partition("/")
            step = int(step_text)
        if rng == "*":
            start, end = low, high
        elif "-" in rng:
            start_text, _, end_text = rng.partition("-")
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(rng)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False
