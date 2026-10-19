"""Replay against a changed agent file (DTN-238)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from wicklight.agent import Agent
from wicklight.cli import app
from wicklight.core import AutoApprove
from wicklight.counterfactual import counterfactual_replay
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import read_trace

runner = CliRunner()
EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

# An original agent with NO recipient policy, so the injected send succeeds.
NO_POLICY_AGENT = (
    "---\nname: inbox-summarizer\nmodels: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  send_email: write\n---\nHandle the inbox.\n"
)
# A tightened agent that adds the recipient allowlist.
GUARDED_AGENT = (
    "---\nname: inbox-summarizer\nmodels: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  send_email: write\n"
    'policies:\n  - email_only_to: ["@mycompany.com"]\n---\nHandle the inbox.\n'
)


def _original_run(tmp: Path) -> Path:
    """Run the injection scenario with no policy; the attacker email is sent."""
    (tmp / "orig.md").write_text(NO_POLICY_AGENT, encoding="utf-8")
    world = MockWorld.from_yaml(
        (EXAMPLES / "worlds" / "injection.yaml").read_text(encoding="utf-8")
    )
    script = FakeScript.from_yaml(
        (EXAMPLES / "scripts" / "injection.yaml").read_text(encoding="utf-8")
    )
    result = Agent.load(tmp / "orig.md").run(
        "handle inbox",
        provider=FakeProvider(script),
        world=world,
        approver=AutoApprove(),
        run_id="orig",
        runs_dir=tmp,
    )
    assert world.sent and world.sent[0].to == "attacker@evil.com"  # it was sent
    assert result.trace_path is not None
    return result.trace_path


# --- the done-when ------------------------------------------------------------


def test_added_policy_flags_the_send_as_now_blocked() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-cf-"))
    original = _original_run(tmp)
    (tmp / "guarded.md").write_text(GUARDED_AGENT, encoding="utf-8")

    result = counterfactual_replay(original, tmp / "guarded.md", runs_dir=tmp)

    assert result.divergence is not None
    d = result.divergence
    assert d.tool == "send_email"
    assert d.original.allowed is True
    assert d.counterfactual.allowed is False
    assert d.counterfactual.by == "email_only_to"
    assert "attacker@evil.com" in (d.counterfactual.reason or "")


def test_counterfactual_trace_is_written_and_marked() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-cf-"))
    original = _original_run(tmp)
    (tmp / "guarded.md").write_text(GUARDED_AGENT, encoding="utf-8")

    result = counterfactual_replay(original, tmp / "guarded.md", runs_dir=tmp)
    assert result.trace_path is not None
    events = read_trace(result.trace_path).events
    started = [e for e in events if e.type == "run_started"]
    assert started and started[0].payload.counterfactual is True
    # It stopped at the divergence rather than running to completion.
    finished = [e for e in events if e.type == "run_finished"]
    assert finished and finished[0].payload.status.value == "stopped"


# --- no change, and permission tightening -------------------------------------


def test_no_change_when_the_agent_is_equivalent() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-cf-"))
    original = _original_run(tmp)
    # Replaying against the same (no-policy) agent changes nothing.
    (tmp / "same.md").write_text(NO_POLICY_AGENT, encoding="utf-8")

    result = counterfactual_replay(original, tmp / "same.md", runs_dir=tmp)
    assert result.divergence is None
    assert result.evaluated_steps >= 1


def test_tightening_permissions_flags_a_now_unpermitted_tool() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-cf-"))
    original = _original_run(tmp)
    # The tightened agent no longer lists send_email at all.
    (tmp / "noemail.md").write_text(
        "---\nname: inbox-summarizer\nmodels: { default: fake/x }\n"
        "tools:\n  read_inbox: read\n---\nHandle the inbox.\n",
        encoding="utf-8",
    )
    result = counterfactual_replay(original, tmp / "noemail.md", runs_dir=tmp)
    assert result.divergence is not None
    assert result.divergence.tool == "send_email"
    assert result.divergence.counterfactual.by == "permissions"


# --- the command --------------------------------------------------------------


def test_replay_agent_cli_reports_the_divergence() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="wicklight-cf-"))
    original = _original_run(tmp)
    (tmp / "guarded.md").write_text(GUARDED_AGENT, encoding="utf-8")

    result = runner.invoke(
        app, ["replay", str(original), "--agent", str(tmp / "guarded.md")]
    )
    assert result.exit_code == 0
    assert "send_email was allowed, now blocked by email_only_to" in result.output
