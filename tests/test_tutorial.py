"""The capstone tutorial's meal-planner project runs as documented (DTN-273).

Loads the tutorial's own tools and agent file and replays each scripted scenario
on the fake provider, asserting the lesson each chapter teaches is visible in the
trace. These guard the tutorial against rot: if the prose and the code drift, a
test fails.
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path
from typing import Any

from wicklight.agent import Agent
from wicklight.agentfile import check_agent_path
from wicklight.core import AutoApprove
from wicklight.deploy import parse_and_validate_deploy
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import TraceEvent, read_trace

TUTORIAL = Path(__file__).parent.parent / "examples" / "tutorial"


def _tools() -> dict[str, Any]:
    """Load the tutorial's tools.py the way its runner does."""
    spec = importlib.util.spec_from_file_location(
        "tutorial_tools", TUTORIAL / "tools.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.meal_planner_tools()


def _run(script: str) -> tuple[Any, list[TraceEvent]]:
    agent = Agent.load(TUTORIAL / "planner.md")
    fake = FakeProvider(FakeScript.from_path(TUTORIAL / "scripts" / script))
    result = agent.run(
        "plan my week",
        providers=dict.fromkeys(agent.model_ids, fake),
        tools=_tools(),
        secrets={"STORE_TOKEN": "test-token"},
        approver=AutoApprove(),
        run_id="t",
        runs_dir=Path(tempfile.mkdtemp()),
    )
    return result, read_trace(result.trace_path).events


def _denied(ev: list[TraceEvent], policy: str) -> bool:
    return any(
        e.type == "policy_checked"
        and e.payload.decision.value == "deny"
        and e.payload.policy == policy
        for e in ev
    )


def _executed_ok(ev: list[TraceEvent], tool: str) -> int:
    return sum(
        1
        for e in ev
        if e.type == "tool_executed" and e.payload.tool == tool and e.payload.ok
    )


def _routed_to(ev: list[TraceEvent], model: str) -> bool:
    return any(e.type == "model_routed" and e.payload.model == model for e in ev)


# --- the agent and deploy files are valid -------------------------------------


def test_planner_passes_check() -> None:
    assert check_agent_path(TUTORIAL / "planner.md").name == "meal-planner"


def test_deploy_file_is_valid() -> None:
    text = (TUTORIAL / "deploy.yaml").read_text(encoding="utf-8")
    _file, config = parse_and_validate_deploy(text, filename="deploy.yaml")
    assert config.name == "meal-planner"
    assert config.triggers and config.triggers[0].schedule == "0 8 * * 0"
    assert "STORE_TOKEN" in config.secrets


# --- each chapter's lesson shows in the trace ---------------------------------


def test_happy_path_orders_within_budget_and_routes_sensitive_local() -> None:
    result, ev = _run("plan.yaml")
    assert result.completed
    assert _executed_ok(ev, "order_groceries") == 1  # the small cart was ordered
    # Reading preferences (sensitive) pins the rest of the run to the local model.
    assert _routed_to(ev, "local/llama3.1")


def test_over_budget_cart_is_blocked_by_spend_limit() -> None:
    _result, ev = _run("over_budget.yaml")
    assert _denied(ev, "spend_limit")
    assert _executed_ok(ev, "order_groceries") == 0  # nothing was ordered


def test_recipe_injection_is_contained() -> None:
    _result, ev = _run("injected.yaml")
    # The injected "$500 order" is refused by spend_limit, and nothing is bought.
    assert _denied(ev, "spend_limit")
    assert _executed_ok(ev, "order_groceries") == 0
    # The untrusted recipe entered context as data, and the run stayed on local.
    assert _routed_to(ev, "local/llama3.1")
    assert any(
        e.type == "tool_executed" and e.payload.tool == "search_recipes" for e in ev
    )
