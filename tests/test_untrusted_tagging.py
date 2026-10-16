"""Untrusted-content tagging for tool results (DTN-219).

Every tool result must enter the model's context wrapped in a "data, not
instructions" envelope and flagged ``trusted=False``; only the agent-file
instructions and the user's task are trusted. These tests capture the messages
the provider actually receives and assert on them.
"""

from __future__ import annotations

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from wicklight.agent import Agent
from wicklight.contracts import (
    Capabilities,
    Message,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    Role,
)
from wicklight.core.loop import (
    _MAX_TOOL_OUTPUT_CHARS,
    _UNTRUSTED_CLOSE,
    _UNTRUSTED_OPEN,
)
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import read_trace

AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  read_file: read\n---\nDo the task.\n"
)


class CapturingProvider:
    """A FakeProvider that records the messages of every request it receives."""

    contract_version = "1.0"
    capabilities = Capabilities(tool_calls=True)

    def __init__(self, script: str) -> None:
        self._inner = FakeProvider(FakeScript.from_yaml(script))
        self.requests: list[list[Message]] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(list(request.messages))
        return await self._inner.complete(request)

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        return self._inner.stream(request)


def _run(
    script: str, world: MockWorld
) -> tuple[CapturingProvider, list[Message], Path]:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-untrusted-"))
    (run_dir / "agent.md").write_text(AGENT, encoding="utf-8")
    agent = Agent.load(run_dir / "agent.md")
    provider = CapturingProvider(script)
    result = agent.run(
        "task", provider=provider, world=world, run_id="t", runs_dir=run_dir
    )
    # The last request carries the fullest history (including the tool result).
    assert result.trace_path is not None
    return provider, provider.requests[-1], result.trace_path


def _tool_message(messages: list[Message]) -> Message:
    tool_messages = [m for m in messages if m.role is Role.TOOL]
    assert tool_messages, "expected a tool-result message in context"
    return tool_messages[-1]


_READ_INBOX = "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: done\n"


def test_tool_result_is_wrapped_and_flagged_untrusted() -> None:
    world = MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n")
    _, messages, _ = _run(_READ_INBOX, world)

    tool = _tool_message(messages)
    assert tool.trusted is False
    assert tool.content.startswith(_UNTRUSTED_OPEN)
    assert tool.content.rstrip().endswith(_UNTRUSTED_CLOSE)


def test_only_instructions_and_task_are_trusted() -> None:
    world = MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n")
    _, messages, _ = _run(_READ_INBOX, world)

    trusted = {m.role for m in messages if m.trusted}
    untrusted_roles = {m.role for m in messages if not m.trusted}
    assert trusted == {Role.SYSTEM, Role.USER}
    # The model's own turns and tool results are never trusted.
    assert Role.ASSISTANT in untrusted_roles
    assert Role.TOOL in untrusted_roles


def test_error_result_is_also_tagged() -> None:
    # read_file on a missing path returns a failure result.
    script = (
        "responses:\n  - tool_calls:\n      - name: read_file\n"
        '        arguments: { path: "nope.txt" }\n  - text: done\n'
    )
    _, messages, _ = _run(script, MockWorld())

    tool = _tool_message(messages)
    assert tool.trusted is False
    assert tool.content.startswith(_UNTRUSTED_OPEN)
    assert "no such file" in tool.content


def test_large_output_is_truncated_but_still_tagged() -> None:
    big = "A" * (_MAX_TOOL_OUTPUT_CHARS + 500)
    world = MockWorld(files={"big.txt": big})
    script = (
        "responses:\n  - tool_calls:\n      - name: read_file\n"
        '        arguments: { path: "big.txt" }\n  - text: done\n'
    )
    _, messages, _ = _run(script, world)

    tool = _tool_message(messages)
    assert tool.trusted is False
    assert tool.content.startswith(_UNTRUSTED_OPEN)
    assert "[truncated 500 characters]" in tool.content
    # The envelope + marker add a little, but the payload itself was capped.
    assert len(tool.content) < _MAX_TOOL_OUTPUT_CHARS + 200


def test_context_built_records_untrusted_spans() -> None:
    world = MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n")
    _, _, trace_path = _run(_READ_INBOX, world)

    events = read_trace(trace_path).events
    built = [e for e in events if e.type == "context_built"]
    # Step 1 has no untrusted spans; by step 2 the assistant turn and the tool
    # result (indices 2 and 3) are both recorded as untrusted.
    assert built[0].payload.untrusted == []
    assert built[-1].payload.untrusted == [2, 3]
