"""The headline prompt-injection demo, end to end (DTN-220).

A poisoned inbox email tries to make the agent exfiltrate data to an outside
address. The scripted model falls for it and calls ``send_email`` to the
attacker — and the ``email_only_to`` policy on ``examples/inbox.md`` blocks the
send. Nothing leaves the building, and the trace explains exactly why.

This exercises the real example files so the documented command in DTN-220 is
what the test runs.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import Decision, read_trace

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
INBOX = EXAMPLES / "inbox.md"
WORLD = EXAMPLES / "worlds" / "injection.yaml"
SCRIPT = EXAMPLES / "scripts" / "injection.yaml"
ATTACKER = "attacker@evil.com"


def test_prompt_injection_is_blocked_by_policy() -> None:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-injection-"))
    agent = Agent.load(INBOX)
    world = MockWorld.from_yaml(WORLD.read_text(encoding="utf-8"))
    provider = FakeProvider(FakeScript.from_yaml(SCRIPT.read_text(encoding="utf-8")))

    result = agent.run(
        "summarize my inbox and handle anything urgent",
        provider=provider,
        world=world,
        run_id="injection",
        runs_dir=run_dir,
    )

    # The run finishes cleanly — the model is told it was blocked and stops.
    assert result.completed
    # Nothing was exfiltrated.
    assert world.sent == []

    assert result.trace_path is not None
    events = read_trace(result.trace_path).events
    policy_events = [e for e in events if e.type == "policy_checked"]
    denies = [e for e in policy_events if e.payload.decision is Decision.DENY]

    # Exactly one block: send_email to the attacker, by email_only_to, cited.
    assert len(denies) == 1
    deny = denies[0]
    assert deny.payload.tool == "send_email"
    assert deny.payload.policy == "email_only_to"
    assert ATTACKER in (deny.payload.reason or "")
    assert deny.payload.source is not None and "line" in deny.payload.source
    assert ATTACKER in deny.explain and "email_only_to" in deny.explain

    # read_inbox was allowed and ran; send_email never executed.
    assert any(
        e.type == "tool_executed" and e.payload.tool == "read_inbox" and e.payload.ok
        for e in events
    )
    assert not any(
        e.type == "tool_executed" and e.payload.tool == "send_email" and e.payload.ok
        for e in events
    )


def test_injection_payload_entered_context_as_untrusted() -> None:
    # The poisoned email arrives as a tool result, so it is tagged untrusted
    # (DTN-219) and can never be treated as a real instruction.
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-injection-"))
    agent = Agent.load(INBOX)
    world = MockWorld.from_yaml(WORLD.read_text(encoding="utf-8"))
    provider = FakeProvider(FakeScript.from_yaml(SCRIPT.read_text(encoding="utf-8")))

    result = agent.run(
        "handle my inbox", provider=provider, world=world, runs_dir=run_dir
    )
    assert result.trace_path is not None

    built = [
        e for e in read_trace(result.trace_path).events if e.type == "context_built"
    ]
    # After the inbox is read, its (untrusted) result is part of the context.
    assert any(e.payload.untrusted for e in built)
