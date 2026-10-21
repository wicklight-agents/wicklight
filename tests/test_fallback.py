"""Fallback chain on provider errors (DTN-244)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
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

TEXT = "responses:\n  - text: answered\n"


class _FailingProvider:
    """Always fails with the given error kind."""

    contract_version = "1.0"
    capabilities = Capabilities(tool_calls=True)

    def __init__(self, kind: ProviderErrorKind = ProviderErrorKind.OVERLOADED) -> None:
        self._kind = kind

    async def complete(self, request: ModelRequest) -> ModelResponse:
        raise ProviderError(f"{self._kind.value} boom", kind=self._kind)

    async def stream(self, request: ModelRequest):  # pragma: no cover - unused
        raise NotImplementedError
        yield


def _run(agent_text: str, providers: dict[str, object], *, world=None):
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-fb-"))
    (run_dir / "agent.md").write_text(agent_text, encoding="utf-8")
    result = Agent.load(run_dir / "agent.md").run(
        "go",
        providers=providers,  # type: ignore[arg-type]
        world=world or MockWorld(),
        run_id="fb",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result, events


def _errors(events: list[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.type == "error"]


# retry_backoff: 0 keeps the fail-then-fallback fast.
LIMITS = "limits: { max_retries: 0, retry_backoff: 0 }"


# --- fallback order and success ----------------------------------------------


def test_falls_back_in_order_until_one_succeeds() -> None:
    agent = (
        f"---\nname: t\nmodels:\n  default: a/m\n  fallback: [b/m, c/m]\n"
        f"{LIMITS}\ntools: {{}}\n---\nGo.\n"
    )
    result, events = _run(
        agent,
        {
            "a/m": _FailingProvider(),
            "b/m": _FailingProvider(),
            "c/m": FakeProvider(FakeScript.from_yaml(TEXT)),
        },
    )
    assert result.completed
    assert result.output == "answered"
    # The two failures were logged as recoverable fallbacks naming the next model.
    fallback_errors = [
        e
        for e in _errors(events)
        if e.payload.where == "fallback" and e.payload.recoverable
    ]
    assert len(fallback_errors) == 2
    assert "falling back to b/m" in fallback_errors[0].explain
    assert "falling back to c/m" in fallback_errors[1].explain
    # c/m answered.
    responded = [e for e in events if e.type == "model_responded"]
    assert responded[0].payload.model == "c/m"


def test_all_fail_stops_with_a_clear_error() -> None:
    agent = (
        f"---\nname: t\nmodels:\n  default: a/m\n  fallback: [b/m]\n"
        f"{LIMITS}\ntools: {{}}\n---\nGo.\n"
    )
    result, events = _run(agent, {"a/m": _FailingProvider(), "b/m": _FailingProvider()})
    assert result.stopped
    terminal = [e for e in _errors(events) if not e.payload.recoverable]
    assert terminal and "all models failed" in terminal[-1].payload.message
    assert (
        "a/m" in terminal[-1].payload.message and "b/m" in terminal[-1].payload.message
    )


# --- fallbacks honor sensitivity ----------------------------------------------


def test_disallowed_fallback_is_skipped_under_sensitivity() -> None:
    # read_file is sensitive and routes to local/safe. If local/safe fails, the
    # only fallback is hosted/big — which is NOT allowed for sensitive data, so
    # it must be skipped and the run must stop rather than leak.
    agent = (
        "---\nname: t\nmodels:\n  default: local/safe\n"
        "  routes:\n    - when: { data: sensitive }\n      use: local/safe\n"
        "  fallback: [hosted/big]\n"
        "limits: { max_retries: 0, retry_backoff: 0 }\n"
        "tools:\n  read_file: { level: read, sensitive: true }\n---\nSummarize.\n"
    )
    # local/safe: step1 reads the file (sensitive), step2 the model call fails.
    local = FakeProvider(
        FakeScript.from_yaml(
            "responses:\n  - tool_calls:\n      - name: read_file\n"
            '        arguments: { path: "s.txt" }\n'
            "  - error: overloaded\n    error_kind: overloaded\n"
        )
    )
    result, events = _run(
        agent,
        {"local/safe": local, "hosted/big": FakeProvider(FakeScript.from_yaml(TEXT))},
        world=MockWorld.from_yaml('files:\n  "s.txt": "secret"\n'),
    )
    assert result.stopped
    # hosted/big was skipped for sensitivity, and the run stopped — never called.
    assert not any(
        e.type == "model_responded" and e.payload.model == "hosted/big" for e in events
    )
    skipped = [
        e
        for e in _errors(events)
        if e.payload.where == "fallback" and "not allowed for sensitive" in e.explain
    ]
    assert skipped and "hosted/big" in skipped[0].explain
