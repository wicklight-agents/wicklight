"""Regenerate the committed viewer fixture trace.

Produces ``injection.jsonl`` and its ``injection/blobs/`` next to this file: a
real recorded run of the prompt-injection scenario (an inbox agent reading a
poisoned email, then a blocked send to an outside address). The viewer and its
tests open this fixture to show a step's recorded context, the untrusted email,
and the policy block.

Run from the repo root:

    uv run python tests/fixtures/viewer/generate.py
"""

from __future__ import annotations

from pathlib import Path

from wicklight.agent import Agent
from wicklight.core import AutoApprove
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld

HERE = Path(__file__).parent
REPO = HERE.parents[2]


def main() -> None:
    world = MockWorld.from_yaml((REPO / "examples/worlds/injection.yaml").read_text())
    script = FakeScript.from_yaml(
        (REPO / "examples/scripts/injection.yaml").read_text()
    )
    result = Agent.load(REPO / "examples/inbox.md").run(
        "handle my inbox",
        provider=FakeProvider(script),
        world=world,
        approver=AutoApprove(),
        run_id="injection",
        runs_dir=HERE,
    )
    print(f"wrote {result.trace_path} ({result.status.value}, {result.steps} steps)")


if __name__ == "__main__":
    main()
