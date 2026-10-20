"""Routing schema, conditions, and `check` validation (DTN-242)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from wicklight.agentfile import AgentFileValidationError, parse_and_validate
from wicklight.cli import app
from wicklight.routing import (
    ConditionError,
    RouteContext,
    StepType,
    parse_comparison,
    route_matches,
    unreachable_routes,
    validate_when,
)

runner = CliRunner()


# --- condition parsing & validation -------------------------------------------


def test_parse_comparison_handles_suffixes_and_ops() -> None:
    assert parse_comparison(">100k").matches(100_001)
    assert not parse_comparison(">100k").matches(100_000)
    assert parse_comparison(">=50000").matches(50_000)
    assert parse_comparison("<0.5").matches(0.25)
    assert parse_comparison("<=1m").matches(1_000_000)


def test_parse_comparison_rejects_garbage() -> None:
    for bad in ["100k", "~5", ">", "abc", 5]:
        with pytest.raises(ConditionError):
            parse_comparison(bad)


def test_validate_when_accepts_known_conditions() -> None:
    validate_when({"step": "planning"})
    validate_when({"context_tokens": ">100k"})
    validate_when({"cost_so_far": ">=0.5"})
    validate_when({"data": "sensitive"})
    validate_when({"step": "execution", "data": "sensitive"})  # AND of two


def test_validate_when_rejects_unknown_and_bad_values() -> None:
    with pytest.raises(ConditionError, match="unknown route condition 'stpe'"):
        validate_when({"stpe": "planning"})
    with pytest.raises(ConditionError, match="step must be one of"):
        validate_when({"step": "thinking"})
    with pytest.raises(ConditionError, match="data must be 'sensitive'"):
        validate_when({"data": "public"})
    with pytest.raises(ConditionError, match="must not be empty"):
        validate_when({})


# --- matching -----------------------------------------------------------------


def _ctx(**kw: object) -> RouteContext:
    base: dict[str, object] = {
        "step": StepType.EXECUTION,
        "context_tokens": 0,
        "cost_so_far": 0.0,
        "sensitive": False,
    }
    base.update(kw)
    return RouteContext(**base)  # type: ignore[arg-type]


def test_route_matches_each_condition() -> None:
    assert route_matches({"step": "planning"}, _ctx(step=StepType.PLANNING))
    assert not route_matches({"step": "planning"}, _ctx(step=StepType.EXECUTION))
    assert route_matches({"context_tokens": ">100k"}, _ctx(context_tokens=150_000))
    assert route_matches({"cost_so_far": ">0.1"}, _ctx(cost_so_far=0.2))
    assert route_matches({"data": "sensitive"}, _ctx(sensitive=True))
    assert not route_matches({"data": "sensitive"}, _ctx(sensitive=False))
    # AND: both must hold.
    both = {"step": "planning", "data": "sensitive"}
    assert route_matches(both, _ctx(step=StepType.PLANNING, sensitive=True))
    assert not route_matches(both, _ctx(step=StepType.PLANNING, sensitive=False))


def test_unreachable_routes_detects_shadowing() -> None:
    whens = [
        {"step": "planning"},
        {"step": "planning", "data": "sensitive"},  # shadowed by route 0
        {"data": "sensitive"},  # reachable
    ]
    assert unreachable_routes(whens) == [(1, 0)]


# --- schema validation surfaces as a line-numbered error ----------------------


def test_bad_condition_is_a_line_numbered_error() -> None:
    text = (
        "---\nname: t\nmodels:\n  default: fake/x\n  routes:\n"
        "    - when: { nope: planning }\n      use: fake/x\n"
        "tools: { read_inbox: read }\n---\nbody\n"
    )
    with pytest.raises(AgentFileValidationError) as excinfo:
        parse_and_validate(text, filename="r.md")
    message = excinfo.value.issues[0].message
    assert "r.md line 6" in message
    assert "unknown route condition 'nope'" in message


# --- check: model resolution, route printing, unreachable warning -------------


def _write(tmp: Path, body: str) -> Path:
    path = tmp / "routed.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_check_prints_routes_in_order_and_flags_problems() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-route-"))
    path = _write(
        tmp,
        "---\nname: routed\nmodels:\n  default: fake/x\n  routes:\n"
        "    - when: { step: planning }\n      use: fake/x\n"
        "    - when: { step: planning, data: sensitive }\n      use: fake/x\n"
        "  fallback: [nope/model]\n"
        "tools: { read_inbox: read }\n---\nbody\n",
    )
    result = runner.invoke(app, ["check", str(path)])
    assert result.exit_code == 1  # unknown fallback provider is fatal
    assert "routes (first match wins):" in result.output
    assert "1. when step=planning → fake/x" in result.output
    assert "unknown provider 'nope'" in result.output
    assert "route 2 is unreachable" in result.output


def test_check_valid_routing_passes() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-route-ok-"))
    path = _write(
        tmp,
        "---\nname: routed\nmodels:\n  default: fake/x\n  routes:\n"
        "    - when: { data: sensitive }\n      use: local/llama3\n"
        "  fallback: [fake/x]\n"
        "tools: { read_inbox: read }\n---\nbody\n",
    )
    result = runner.invoke(app, ["check", str(path)])
    assert result.exit_code == 0
    assert "routing:\n  ok" in result.output
