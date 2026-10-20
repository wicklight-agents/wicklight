"""Model-routing conditions: validation and matching (M10).

An agent file can route each model call to a different model based on the
situation:

    models:
      routes:
        - when: { step: planning }        use: anthropic/claude-opus
        - when: { context_tokens: ">100k" } use: google/gemini-pro
        - when: { data: sensitive }       use: local/llama

This module owns what a condition *means*: the allowed keys, how their values
parse, and whether a condition matches a :class:`RouteContext`. The agent-file
schema validates ``when`` through :func:`validate_when` (so a bad condition is a
line-numbered error), and the core router (DTN-243) evaluates routes with
:func:`route_matches`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ConditionError(ValueError):
    """Raised for an unknown condition key or an unparseable value."""


class ConditionKey(str, Enum):
    STEP = "step"
    CONTEXT_TOKENS = "context_tokens"
    COST_SO_FAR = "cost_so_far"
    DATA = "data"


class StepType(str, Enum):
    """The kind of step, as the loop classifies it (DTN-243)."""

    PLANNING = "planning"
    EXECUTION = "execution"


_NUMERIC_KEYS = frozenset({ConditionKey.CONTEXT_TOKENS, ConditionKey.COST_SO_FAR})
_COMPARISON = re.compile(r"^\s*(>=|<=|>|<)\s*([0-9]*\.?[0-9]+)\s*([kKmM]?)\s*$")
_SUFFIXES = {"": 1, "k": 1_000, "m": 1_000_000}


@dataclass(frozen=True)
class Comparison:
    """A parsed numeric comparison like ``> 100000``."""

    op: str
    threshold: float

    def matches(self, value: float) -> bool:
        if self.op == ">":
            return value > self.threshold
        if self.op == ">=":
            return value >= self.threshold
        if self.op == "<":
            return value < self.threshold
        return value <= self.threshold


@dataclass(frozen=True)
class RouteContext:
    """The situation a route is evaluated against, built by the loop."""

    step: StepType
    context_tokens: int
    cost_so_far: float
    sensitive: bool


def parse_comparison(raw: object) -> Comparison:
    """Parse a comparator string such as ``">100k"`` or ``"<=0.5"``."""
    if not isinstance(raw, str):
        raise ConditionError(f"expected a comparison like '>100k', got {raw!r}")
    match = _COMPARISON.match(raw)
    if match is None:
        raise ConditionError(
            f"invalid comparison {raw!r}; use e.g. '>100k', '>=50000', '<0.5'"
        )
    op, number, suffix = match.groups()
    return Comparison(op=op, threshold=float(number) * _SUFFIXES[suffix.lower()])


def validate_when(when: dict[str, Any]) -> None:
    """Validate a route's ``when`` mapping, or raise :class:`ConditionError`."""
    if not when:
        raise ConditionError("a route condition must not be empty")
    valid = ", ".join(key.value for key in ConditionKey)
    for raw_key, value in when.items():
        try:
            key = ConditionKey(raw_key)
        except ValueError as exc:
            raise ConditionError(
                f"unknown route condition {raw_key!r}; use one of: {valid}"
            ) from exc
        if key is ConditionKey.STEP:
            _validate_step(value)
        elif key in _NUMERIC_KEYS:
            parse_comparison(value)
        elif key is ConditionKey.DATA and value != "sensitive":
            raise ConditionError(f"condition data must be 'sensitive', got {value!r}")


def _validate_step(value: object) -> None:
    try:
        StepType(value)
    except ValueError as exc:
        valid = ", ".join(step.value for step in StepType)
        raise ConditionError(
            f"condition step must be one of: {valid}, got {value!r}"
        ) from exc


def route_matches(when: dict[str, Any], ctx: RouteContext) -> bool:
    """Whether a (validated) condition matches the context — all keys must hold."""
    for raw_key, value in when.items():
        key = ConditionKey(raw_key)
        if key is ConditionKey.STEP and ctx.step is not StepType(value):
            return False
        if key is ConditionKey.CONTEXT_TOKENS and not parse_comparison(value).matches(
            ctx.context_tokens
        ):
            return False
        if key is ConditionKey.COST_SO_FAR and not parse_comparison(value).matches(
            ctx.cost_so_far
        ):
            return False
        if key is ConditionKey.DATA and not ctx.sensitive:
            return False
    return True


@dataclass(frozen=True)
class RouteChoice:
    """The outcome of routing a model call."""

    model: str
    #: 0-based index of the matching route, or None when the default was used.
    route_index: int | None
    when: dict[str, Any] | None = None

    @property
    def matched_rule(self) -> str:
        if self.route_index is None:
            return "default"
        when = ", ".join(f"{key}={value}" for key, value in (self.when or {}).items())
        return f"rule {self.route_index + 1} ({when})"


def choose_route(
    default: str, routes: list[tuple[dict[str, Any], str]], ctx: RouteContext
) -> RouteChoice:
    """First-match routing: the first route whose condition holds, else default.

    ``routes`` is a list of ``(when, model)`` pairs in agent-file order.
    """
    for index, (when, model) in enumerate(routes):
        if route_matches(when, ctx):
            return RouteChoice(model=model, route_index=index, when=when)
    return RouteChoice(model=default, route_index=None)


def unreachable_routes(whens: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Find routes shadowed by an earlier, broader rule.

    A route is unreachable if an earlier route's conditions are a subset of its
    own (same key/value pairs): the earlier rule matches whenever this one
    would, so first-match never reaches it. Returns ``(route_index,
    shadowed_by_index)`` pairs (0-based). Sound for the AND/equality semantics;
    it does not reason about overlapping numeric thresholds.
    """
    shadowed: list[tuple[int, int]] = []
    item_sets = [set(when.items()) for when in whens]
    for i, later in enumerate(item_sets):
        for j in range(i):
            if item_sets[j] <= later:
                shadowed.append((i, j))
                break
    return shadowed
