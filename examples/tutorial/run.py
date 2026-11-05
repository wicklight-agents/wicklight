"""Run the meal-planner with your own tools, offline on the fake provider.

This is the runner the tutorial builds in chapter 6. It loads the agent file,
supplies the tools you wrote, and replays a scripted model so you can watch the
whole run with no API key:

    python run.py scripts/plan.yaml
    python run.py scripts/over_budget.yaml      # watch spend_limit block it
    python run.py scripts/injected.yaml         # watch an injection get contained

Then open the run in the viewer:  wicklight view runs/<run-id>
"""

from __future__ import annotations

import sys
from pathlib import Path

from tools import meal_planner_tools

from wicklight.agent import Agent
from wicklight.core import AutoApprove
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import read_trace

HERE = Path(__file__).parent


def main() -> None:
    script = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "scripts" / "plan.yaml"
    agent = Agent.load(HERE / "planner.md")
    fake = FakeProvider(FakeScript.from_path(script))

    result = agent.run(
        "plan my dinners for the week",
        # One fake provider stands in for every model the agent can route to.
        providers=dict.fromkeys(agent.model_ids, fake),
        tools=meal_planner_tools(),
        # The harness holds secrets; order_groceries receives STORE_TOKEN, the
        # model never does.
        secrets={"STORE_TOKEN": "test-token"},
        # Auto-approve so the demo runs unattended; in a terminal, drop this to
        # get the real y/N prompt before an order.
        approver=AutoApprove(),
        runs_dir=HERE / "runs",
    )

    # Print the run step by step (the trace is the source of truth).
    for event in read_trace(result.trace_path).events:
        print(f"  {event.type:<16} {event.explain}")
    print(f"\n{result.status.value} in {result.steps} steps")
    print(f"open it in the viewer:  wicklight view {result.trace_path}")


if __name__ == "__main__":
    main()
