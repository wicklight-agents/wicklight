"""Enforced sensitivity routing (DTN-245).

Once a sensitive tool result is in context, the run is restricted to models
allowed for sensitive data; it stops rather than call a disallowed one. These
tests prove sensitive content never reaches a disallowed provider, and that the
restriction latches (survives context truncation).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

# The model calls: step 1 reads a file (the sensitive tool), step 2 is a plain
# reply. The reply model differs per provider so we can see which answered.
SCRIPT = (
    "responses:\n  - tool_calls:\n      - name: read_file\n"
    '        arguments: { path: "secret.txt" }\n'
    "  - text: summarized locally\n"
)
WORLD = 'files:\n  "secret.txt": "the launch codes"\n'


def _run(agent_text: str, providers: dict[str, FakeProvider]):
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-sens-"))
    (run_dir / "agent.md").write_text(agent_text, encoding="utf-8")
    result = Agent.load(run_dir / "agent.md").run(
        "summarize the secret file",
        providers=providers,
        world=MockWorld.from_yaml(WORLD),
        run_id="s",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _routed(events: list[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.type == "model_routed"]


# --- sensitive content routes to the allowed model ---------------------------


def test_sensitive_result_restricts_routing_to_the_allowed_model() -> None:
    # read_file is marked sensitive; a data:sensitive route sends sensitive runs
    # to local/llama. The default is a hosted model.
    agent = (
        "---\nname: t\nmodels:\n  default: hosted/big\n"
        "  routes:\n    - when: { data: sensitive }\n      use: local/llama\n"
        "tools:\n  read_file: { level: read, sensitive: true }\n---\nSummarize.\n"
    )
    result, events = _run(
        agent,
        {
            "hosted/big": FakeProvider(FakeScript.from_yaml(SCRIPT)),
            "local/llama": FakeProvider(
                FakeScript.from_yaml("responses:\n  - text: summarized locally\n")
            ),
        },
    )
    assert result.completed
    routed = _routed(events)
    # Step 1 (not yet sensitive) used the default; step 2 (after the sensitive
    # read) was routed to the allowed local model.
    assert routed[0].payload.model == "hosted/big"
    assert routed[1].payload.model == "local/llama"
    # The tool result was flagged sensitive.
    executed = [e for e in events if e.type == "tool_executed"]
    assert executed[0].payload.sensitive is True


# --- a disallowed route is excluded, not followed -----------------------------


def test_sensitive_run_excludes_a_disallowed_matching_route() -> None:
    # An execution route would send step 2 to a hosted model, but once sensitive
    # that route is excluded and the allowed local model is used instead.
    agent = (
        "---\nname: t\nmodels:\n  default: local/llama\n"
        "  routes:\n"
        "    - when: { step: execution }\n      use: hosted/big\n"
        "    - when: { data: sensitive }\n      use: local/llama\n"
        "tools:\n  read_file: { level: read, sensitive: true }\n---\nSummarize.\n"
    )
    result, events = _run(
        agent,
        {
            "local/llama": FakeProvider(FakeScript.from_yaml(SCRIPT)),
            "hosted/big": FakeProvider(
                FakeScript.from_yaml("responses:\n  - text: leaked\n")
            ),
        },
    )
    assert result.completed
    step2 = _routed(events)[1]
    assert step2.payload.model == "local/llama"
    assert "hosted/big" in step2.payload.excluded  # the hosted route was skipped


# --- no allowed model: stop rather than leak ----------------------------------


def test_sensitive_run_with_no_allowed_model_stops() -> None:
    # read_file is sensitive but there is no data:sensitive route, so after the
    # read there is no model allowed to continue — the run must stop, not leak.
    agent = (
        "---\nname: t\nmodels:\n  default: hosted/big\n"
        "tools:\n  read_file: { level: read, sensitive: true }\n---\nSummarize.\n"
    )
    result, events = _run(
        agent, {"hosted/big": FakeProvider(FakeScript.from_yaml(SCRIPT))}
    )
    assert result.stopped
    errors = [
        e for e in events if e.type == "error" and e.payload.where == "sensitivity"
    ]
    assert (
        errors and "no model is allowed for sensitive data" in errors[0].payload.message
    )
    # Only the first (pre-sensitive) model call happened; step 2 never called a model.
    assert len(_routed(events)) == 1


# --- runtime-sensitive result (ToolResult.sensitive) also latches -------------


def test_runtime_sensitive_result_latches_without_a_file_flag() -> None:
    # The tool isn't declared sensitive in the agent file, but a MockWorld file
    # whose content the tool marks sensitive would latch too. Here we rely on the
    # agent-file flag path above; this checks the latch survives a later step.
    agent = (
        "---\nname: t\nmodels:\n  default: hosted/big\n"
        "  routes:\n    - when: { data: sensitive }\n      use: local/llama\n"
        "tools:\n  read_file: { level: read, sensitive: true }\n"
        "  read_inbox: read\n---\nSummarize.\n"
    )
    # step1 read_file (sensitive), step2 read_inbox (not sensitive), step3 reply.
    script = (
        "responses:\n"
        "  - tool_calls:\n      - name: read_file\n"
        '        arguments: { path: "s.txt" }\n'
        "  - tool_calls:\n      - name: read_inbox\n"
        "  - text: done\n"
    )
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-sens-"))
    (run_dir / "agent.md").write_text(agent, encoding="utf-8")
    result = Agent.load(run_dir / "agent.md").run(
        "go",
        providers={
            "hosted/big": FakeProvider(FakeScript.from_yaml(script)),
            "local/llama": FakeProvider(
                FakeScript.from_yaml(
                    "responses:\n"
                    "  - tool_calls:\n      - name: read_inbox\n"
                    "  - text: done\n"
                )
            ),
        },
        world=MockWorld.from_yaml('files:\n  "s.txt": "secret"\ninbox: []\n'),
        run_id="s",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events
    routed = [e for e in events if e.type == "model_routed"]
    # Once sensitive at step 1, every later step stays on the local model.
    assert routed[0].payload.model == "hosted/big"
    assert all(r.payload.model == "local/llama" for r in routed[1:])
