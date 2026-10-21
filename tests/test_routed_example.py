"""The routing example end to end, and its scenarios (DTN-246).

Drives examples/routed.md through each route condition, a fallback, and a
sensitive-data run with injected FakeProviders — so the shipped example is
proven to work offline and the routing story holds together.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from typer.testing import CliRunner

from wicklight.agent import Agent
from wicklight.cli import app
from wicklight.contracts import (
    Capabilities,
    ModelRequest,
    ModelResponse,
    ProviderError,
    ProviderErrorKind,
)
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceEvent, read_trace

runner = CliRunner()
ROUTED = Path(__file__).resolve().parent.parent / "examples" / "routed.md"


class _Failing:
    contract_version = "1.0"
    capabilities = Capabilities(tool_calls=True)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise ProviderError("overloaded", kind=ProviderErrorKind.OVERLOADED)

    async def stream(self, request: ModelRequest):  # pragma: no cover - unused
        raise NotImplementedError
        yield


def _fake(script: str) -> FakeProvider:
    return FakeProvider(FakeScript.from_yaml(script))


READ_INBOX = "responses:\n  - tool_calls:\n      - name: read_inbox\n"
READ_FILE = (
    "responses:\n  - tool_calls:\n      - name: read_file\n"
    '        arguments: { path: "notes.txt" }\n'
)
DONE = "responses:\n  - text: done\n"


def _run(providers: dict[str, object], *, world=None):
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-routed-"))
    result = Agent.load(ROUTED).run(
        "handle my work",
        providers=providers,  # type: ignore[arg-type]
        world=world or MockWorld(),
        run_id="routed",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _routed_models(events: list[TraceEvent]) -> list[str]:
    return [e.payload.model for e in events if e.type == "model_routed"]


# --- the example is valid -----------------------------------------------------


def test_example_passes_check() -> None:
    result = runner.invoke(app, ["check", str(ROUTED)])
    assert result.exit_code == 0
    assert "routing:\n  ok" in result.output


# --- planning vs execution ----------------------------------------------------


def test_planning_then_execution_routing() -> None:
    # Step 1 (planning) -> opus, which reads the inbox; step 2 (execution) ->
    # the default sonnet, which replies.
    result, events = _run(
        {
            "anthropic/claude-opus": _fake(READ_INBOX),
            "anthropic/claude-sonnet": _fake(DONE),
        },
        world=MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n"),
    )
    assert result.completed
    assert _routed_models(events) == [
        "anthropic/claude-opus",
        "anthropic/claude-sonnet",
    ]


# --- sensitive data pins to the local model -----------------------------------


def test_reading_a_file_pins_the_rest_to_local() -> None:
    # Planning reads a (sensitive) file; from then on the run is local-only.
    result, events = _run(
        {
            "anthropic/claude-opus": _fake(READ_FILE),
            "local/llama3.1": _fake(DONE),
        },
        world=MockWorld.from_yaml('files:\n  "notes.txt": "confidential"\n'),
    )
    assert result.completed
    models = _routed_models(events)
    assert models[0] == "anthropic/claude-opus"  # planning, before the file was read
    assert models[1] == "local/llama3.1"  # pinned local after the sensitive read


# --- fallback on a provider outage --------------------------------------------


def test_fallback_when_the_execution_model_is_down() -> None:
    # Planning (opus) reads the inbox; execution routes to the default sonnet,
    # which is down, so it falls back to openai/gpt-4o.
    result, events = _run(
        {
            "anthropic/claude-opus": _fake(READ_INBOX),
            "anthropic/claude-sonnet": _Failing(),
            "openai/gpt-4o": _fake(DONE),
        },
        world=MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n"),
    )
    assert result.completed
    responded = [e.payload.model for e in events if e.type == "model_responded"]
    assert "openai/gpt-4o" in responded  # the fallback answered
    assert any(
        e.type == "error"
        and e.payload.where == "fallback"
        and "falling back" in e.explain
        for e in events
    )
