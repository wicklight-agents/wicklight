"""`wicklight explain`: what the model saw at a step (DTN-239)."""

from __future__ import annotations

import io
import json
import tempfile
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from wicklight.agent import Agent
from wicklight.cli import app
from wicklight.explain import ExplainError, explain_step, render_explanation
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import read_trace

runner = CliRunner()
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def _injection_trace() -> Path:
    """Run the prompt-injection scenario and return its trace path."""
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-explain-"))
    agent = Agent.load(EXAMPLES / "inbox.md")
    world = MockWorld.from_yaml(
        (EXAMPLES / "worlds" / "injection.yaml").read_text(encoding="utf-8")
    )
    script = FakeScript.from_yaml(
        (EXAMPLES / "scripts" / "injection.yaml").read_text(encoding="utf-8")
    )
    result = agent.run(
        "handle my inbox",
        provider=FakeProvider(script),
        world=world,
        run_id="injection",
        runs_dir=run_dir,
    )
    assert result.trace_path is not None
    return result.trace_path


# --- the done-when: explain the step where the poisoned email was read --------


def test_explain_marks_the_poisoned_email_and_shows_the_block() -> None:
    trace = read_trace(_injection_trace())
    # Step 2: the model saw the inbox (with the injection) and proposed send_email.
    explanation = explain_step(trace, 2)

    untrusted = [m for m in explanation.messages if not m.trusted]
    poisoned = [m for m in untrusted if "attacker@evil.com" in m.content]
    assert poisoned, "the poisoned tool result should be in the context"
    assert poisoned[0].name == "read_inbox"  # labeled with its source

    # What happened next: the send was blocked by the policy, with a reason.
    blocked = [
        e
        for e in explanation.outcome
        if e.type == "policy_checked" and "blocked" in e.explain
    ]
    assert blocked and "email_only_to" in blocked[0].explain


def test_render_boxes_untrusted_content() -> None:
    trace = read_trace(_injection_trace())
    console = Console(file=io.StringIO(), width=100, no_color=True)
    render_explanation(console, explain_step(trace, 2))
    output = console.file.getvalue()  # type: ignore[attr-defined]
    assert "untrusted · tool result from read_inbox" in output
    assert "what the model saw" in output
    assert "What happened next" in output


# --- JSON output --------------------------------------------------------------


def test_explain_json_structure() -> None:
    trace_path = _injection_trace()
    result = runner.invoke(app, ["explain", str(trace_path), "--step", "2", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["step"] == 2
    assert any(not m["trusted"] for m in data["messages"])
    assert data["response"]["tool_calls"][0]["name"] == "send_email"
    assert any(o["type"] == "policy_checked" for o in data["outcome"])


# --- errors -------------------------------------------------------------------


def test_explain_step_without_a_model_call_errors() -> None:
    trace = read_trace(_injection_trace())
    # Step 0 is run_started/preflight — no model call there.
    try:
        explain_step(trace, 0)
    except ExplainError as exc:
        assert "no model call" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected an ExplainError")


def test_explain_cli_missing_trace_exits_nonzero() -> None:
    result = runner.invoke(app, ["explain", "nope.jsonl", "--step", "1"])
    assert result.exit_code == 1
