"""sender_denylist in the core loop: configured from the agent file, blocking
a real tool call, and recorded in the trace.

The unit tests in ``test_builtin_policies.py`` cover the matching rules. These
cover the wiring: a policy named only in an agent file is discovered from its
entry point, constructed with the file's config, evaluated before the tool runs,
and its denial reaches the trace with the agent-file line that caused it.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel

from wicklight.agent import Agent
from wicklight.contracts import ToolContext, ToolResult, ToolRisk, tool
from wicklight.core import AutoApprove
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import Decision, PolicyChecked, read_trace

AGENT = """\
---
name: unsubscriber
models: { default: fake/x }
tools:
  unsubscribe: write
policies:
  - sender_denylist: ["@mybank.com"]
---
Unsubscribe from promotional mail.
"""


class _UnsubInput(BaseModel):
    sender: str


#: Records every sender it was actually called with, so a test can prove a
#: blocked call never reached the tool at all.
CALLED: list[str] = []


@tool(risk=ToolRisk.WRITE, network_hosts=[], sensitive=False)
async def unsubscribe(inp: _UnsubInput, _ctx: ToolContext) -> ToolResult:
    """Unsubscribe from a sender's mailing list."""
    CALLED.append(inp.sender)
    return ToolResult.success("unsubscribed")


def _script(sender: str) -> str:
    return (
        "responses:\n"
        "  - tool_calls:\n"
        "      - name: unsubscribe\n"
        f"        arguments: {{ sender: {sender} }}\n"
        '  - text: "done"\n'
    )


def _run(sender: str):
    CALLED.clear()
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-denylist-"))
    (run_dir / "agent.md").write_text(AGENT, encoding="utf-8")
    loaded = Agent.load(run_dir / "agent.md")
    result = loaded.run(
        "clean up my inbox",
        provider=FakeProvider(FakeScript.from_yaml(_script(sender))),
        tools={"unsubscribe": unsubscribe},
        approver=AutoApprove(),  # isolate policy behavior from the approval gate
        run_id="t",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _denials(events: list[object]) -> list[PolicyChecked]:
    return [
        e
        for e in events
        if isinstance(e, PolicyChecked) and e.payload.decision is Decision.DENY
    ]


def test_denylisted_sender_is_blocked_and_the_tool_never_runs() -> None:
    _result, events = _run("marketing@mybank.com")

    denials = _denials(events)
    assert len(denials) == 1
    assert denials[0].payload.policy == "sender_denylist"
    assert "marketing@mybank.com" in (denials[0].payload.reason or "")
    # The point of a policy: the call is stopped before the tool executes.
    assert CALLED == []


def test_denial_cites_the_agent_file_line() -> None:
    _result, events = _run("marketing@mybank.com")
    source = _denials(events)[0].payload.source or ""
    assert "agent.md" in source


def test_allowed_sender_runs_the_tool() -> None:
    result, events = _run("deals@shop.example")

    assert _denials(events) == []
    assert CALLED == ["deals@shop.example"]
    assert result.completed


def test_subdomain_of_a_denylisted_domain_is_blocked() -> None:
    # The asymmetry with email_only_to: a denylist that misses subdomains
    # fails open, so this must be blocked end to end, not just in the unit test.
    _result, events = _run("deals@mail.mybank.com")

    assert len(_denials(events)) == 1
    assert CALLED == []
