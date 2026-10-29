"""The example-tools plugin resolves and runs the scenarios (DTN-258).

Host-side: proves the entry-point tools load from the registry, seed their world
from WICKLIGHT_MOCK_WORLD, and drive the injection scenario — the same path a
deployed container takes (tools via entry points, no in-process injection).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import wicklight.examples.tools as example_tools
from wicklight.agent import Agent
from wicklight.contracts import ToolRegistry
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import read_trace

INJECTION_WORLD = Path("examples/worlds/injection.yaml")
INJECTION_SCRIPT = Path("examples/scripts/injection.yaml")

# A fake-provider inbox agent: the email_only_to policy is the only gate (no
# approval), so the injected send is blocked purely by policy.
AGENT = (
    "---\n"
    "name: inbox\n"
    "models: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  send_email: write\n"
    'policies:\n  - email_only_to: ["@mycompany.com"]\n'
    "---\n"
    "Handle the inbox.\n"
)


@pytest.fixture(autouse=True)
def _reset_world(monkeypatch: pytest.MonkeyPatch) -> None:
    # The example world is a process-wide singleton; reset it per test.
    example_tools._world = None
    yield
    example_tools._world = None


def test_tools_are_discoverable() -> None:
    names = ToolRegistry.discover().names()
    assert {"read_inbox", "send_email", "read_file", "make_payment"} <= set(names)


def test_world_seeds_from_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world_file = tmp_path / "world.yaml"
    world_file.write_text(INJECTION_WORLD.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("WICKLIGHT_MOCK_WORLD", str(world_file))
    importlib.reload(example_tools)  # pick up the env for a fresh load
    try:
        world = example_tools.shared_world()
        assert world.inbox  # the poisoned inbox loaded from the file
    finally:
        example_tools._world = None


def test_injection_scenario_blocks_the_send_via_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world_file = tmp_path / "world.yaml"
    world_file.write_text(INJECTION_WORLD.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("WICKLIGHT_MOCK_WORLD", str(world_file))
    example_tools._world = None  # reload world from the env file

    agent_file = tmp_path / "inbox.md"
    agent_file.write_text(AGENT, encoding="utf-8")

    # No tools=/world= injected: tools resolve through the entry-point registry,
    # exactly as in a deployed container.
    result = Agent.load(agent_file).run(
        "handle my inbox",
        provider=FakeProvider(FakeScript.from_yaml(INJECTION_SCRIPT.read_text())),
        run_id="inj",
        runs_dir=tmp_path,
    )
    events = read_trace(result.trace_path).events
    denials = [
        e
        for e in events
        if e.type == "policy_checked" and e.payload.decision.value == "deny"
    ]
    assert denials and denials[0].payload.policy == "email_only_to"
    # The attacker never received mail: no send_email tool_executed succeeded.
    sent = [
        e
        for e in events
        if e.type == "tool_executed" and e.payload.tool == "send_email" and e.payload.ok
    ]
    assert not sent
