"""API-key resolution and trace redaction (DTN-227)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from wicklight.agent import Agent
from wicklight.contracts import ProviderError
from wicklight.providers import FakeProvider, FakeScript
from wicklight.providers.credentials import (
    provider_of,
    required_keys,
    resolve_key,
    trace_redactor,
)
from wicklight.redaction import build_secret_redactor, scan_for_secrets, scrub_text
from wicklight.tools import MockWorld

_KEY = "sk-ant-abcdef0123456789abcdef"


# --- key resolution -----------------------------------------------------------


def test_provider_of_splits_the_prefix() -> None:
    assert provider_of("anthropic/claude-sonnet") == "anthropic"
    assert provider_of("fake/x") == "fake"


def test_resolve_key_reads_env_and_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    assert resolve_key("anthropic") == _KEY

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        resolve_key("openai")


def test_resolve_key_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ProviderError, match="no known API-key variable"):
        resolve_key("fake")


def test_required_keys_dedupes_and_reports_set_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    reqs = required_keys(
        ["anthropic/claude", "anthropic/haiku", "openai/gpt", "fake/x"]
    )
    by_var = {r.env_var: r for r in reqs}
    assert set(by_var) == {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}  # fake needs none
    assert by_var["ANTHROPIC_API_KEY"].is_set is True
    assert by_var["OPENAI_API_KEY"].is_set is False


# --- redaction primitives -----------------------------------------------------


def test_build_secret_redactor_strips_exact_values_and_patterns() -> None:
    redact = build_secret_redactor(["hunter2-not-key-shaped"])
    out = redact("key=hunter2-not-key-shaped and token=sk-ABCDEF0123456789")
    assert "hunter2-not-key-shaped" not in out
    assert scan_for_secrets(out) == []
    # Idempotent (the trace writer runs it on every line).
    assert redact(out) == out


def test_scrub_text_is_a_no_op_on_clean_text() -> None:
    assert scrub_text("nothing secret here") == "nothing secret here"


# --- the end-to-end guarantee: a key echoed in an error is redacted -----------


def test_provider_error_echoing_a_key_is_redacted_in_the_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", _KEY)
    run_dir = Path(tempfile.mkdtemp(prefix="wicklight-redact-"))
    (run_dir / "agent.md").write_text(
        "---\nname: t\nmodels: { default: anthropic/claude }\n"
        "tools: { read_inbox: read }\n---\nGo.\n",
        encoding="utf-8",
    )
    # The provider fails with an error message that echoes the API key.
    script = f'responses:\n  - error: "upstream rejected key {_KEY}"\n'
    agent = Agent.load(run_dir / "agent.md")
    result = agent.run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(script)),
        world=MockWorld(),
        run_id="redact",
        runs_dir=run_dir,
    )

    assert result.trace_path is not None
    trace_text = result.trace_path.read_text(encoding="utf-8")
    assert _KEY not in trace_text  # the key never reached disk
    assert "REDACTED" in trace_text  # it was scrubbed, not just absent


def test_trace_redactor_uses_the_live_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "plain-value-not-key-shaped")
    redact = trace_redactor()
    assert "plain-value-not-key-shaped" not in redact("leak plain-value-not-key-shaped")
