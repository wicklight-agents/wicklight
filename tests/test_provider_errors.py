"""Provider error mapping and visible retries in the core loop (DTN-228)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from wicklight.agent import Agent
from wicklight.contracts import ProviderError, ProviderErrorKind
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import RunStatus, TraceEvent, read_trace

# retry_backoff: 0 keeps the test fast; max_retries: 2 allows two retries.
AGENT = (
    "---\nname: t\nmodels: { default: fake/x }\n"
    "tools: { read_inbox: read }\n"
    "limits: { max_retries: 2, retry_backoff: 0 }\n---\nGo.\n"
)


def _run(script: str) -> tuple[RunStatus, list[TraceEvent]]:
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-errors-"))
    (run_dir / "agent.md").write_text(AGENT, encoding="utf-8")
    agent = Agent.load(run_dir / "agent.md")
    result = agent.run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(script)),
        world=MockWorld(),
        run_id="e",
        runs_dir=run_dir,
    )
    events = read_trace(result.trace_path).events if result.trace_path else []
    return result.status, events


def _errors(events: list[TraceEvent]) -> list[TraceEvent]:
    return [e for e in events if e.type == "error"]


# --- the error taxonomy -------------------------------------------------------


def test_provider_error_kinds_drive_retryability() -> None:
    assert ProviderError("x", kind=ProviderErrorKind.RATE_LIMIT).retryable
    assert ProviderError("x", kind=ProviderErrorKind.OVERLOADED).retryable
    # Only rate-limit and overloaded retry.
    for kind in (
        ProviderErrorKind.AUTH,
        ProviderErrorKind.INVALID_REQUEST,
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.CONTEXT_TOO_LONG,
        ProviderErrorKind.UNKNOWN,
    ):
        assert not ProviderError("x", kind=kind).retryable


def test_auth_error_carries_a_default_suggestion() -> None:
    assert "API key" in (
        ProviderError("x", kind=ProviderErrorKind.AUTH).suggestion or ""
    )


# --- visible retries ----------------------------------------------------------


def test_rate_limit_is_retried_visibly_then_succeeds() -> None:
    # Two rate-limit errors, then a normal completion.
    script = (
        "responses:\n"
        '  - error: "rate limited (429)"\n    error_kind: rate_limit\n'
        '  - error: "rate limited (429)"\n    error_kind: rate_limit\n'
        "  - text: done\n"
    )
    status, events = _run(script)
    assert status is RunStatus.COMPLETED  # it recovered

    retries = [e for e in _errors(events) if e.payload.recoverable]
    assert len(retries) == 2
    # Each retry records the attempt number, the wait, and the kind.
    assert [e.payload.attempt for e in retries] == [1, 2]
    assert all(e.payload.wait_seconds is not None for e in retries)
    assert all(e.payload.kind == "rate_limit" for e in retries)


def test_retries_are_exhausted_then_the_run_fails() -> None:
    # Always rate-limited: 1 initial + 2 retries = 3 attempts, then terminal.
    script = (
        "responses:\n"
        + '  - error: "rate limited"\n    error_kind: rate_limit\n' * 4
        + "  - text: never reached\n"
    )
    status, events = _run(script)
    assert status is RunStatus.ERROR
    recoverable = [e for e in _errors(events) if e.payload.recoverable]
    terminal = [e for e in _errors(events) if not e.payload.recoverable]
    assert len(recoverable) == 2  # max_retries
    assert len(terminal) == 1


# --- immediate, clear failures ------------------------------------------------


def test_auth_error_fails_immediately_with_a_suggestion() -> None:
    script = 'responses:\n  - error: "invalid x-api-key"\n    error_kind: auth\n'
    status, events = _run(script)
    assert status is RunStatus.ERROR
    terminal = [e for e in _errors(events) if not e.payload.recoverable]
    assert len(terminal) == 1  # no retries for auth
    assert not [e for e in _errors(events) if e.payload.recoverable]
    assert terminal[0].payload.kind == "auth"
    assert "API key" in (terminal[0].payload.suggestion or "")


def test_invalid_request_fails_immediately() -> None:
    script = 'responses:\n  - error: "bad request"\n    error_kind: invalid_request\n'
    status, events = _run(script)
    assert status is RunStatus.ERROR
    assert not [e for e in _errors(events) if e.payload.recoverable]  # never retried
    terminal = [e for e in _errors(events) if not e.payload.recoverable]
    assert terminal[0].payload.kind == "invalid_request"
