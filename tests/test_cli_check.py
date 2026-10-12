"""Tests for the `wicklight check` command (DTN-197)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from wicklight.agentfile import (
    build_effective_config,
    parse_and_validate,
    render_effective_config,
)
from wicklight.cli import app

runner = CliRunner()

REPO_ROOT = Path(__file__).parent.parent
INBOX = REPO_ROOT / "examples" / "inbox.md"
BAD = REPO_ROOT / "tests" / "fixtures" / "agentfile" / "invalid_level.md"

INBOX_SNAPSHOT = """\
agent: inbox-summarizer

models:
  default: anthropic/claude-sonnet (from file)
  routes: 0 (default)
  fallback: none (default)

limits:
  max_steps: 20 (from file)
  max_cost: $1.00 (default)
  timeout: 300s (default)

tools:
  read_inbox: read (from file)
  send_email: write, approval required (from file)

policies:
  email_only_to: @mycompany.com (from file)

irreversible tools:
  none

approval waivers:
  none"""


def _render(text: str) -> str:
    agent, config = parse_and_validate(text)
    effective = build_effective_config(config, provided=agent.frontmatter)
    return render_effective_config(effective)


def test_effective_config_render_snapshot() -> None:
    assert _render(INBOX.read_text(encoding="utf-8")) == INBOX_SNAPSHOT


def test_render_lists_irreversible_tools_and_waivers() -> None:
    text = (
        "---\n"
        "name: danger\n"
        "models:\n"
        "  default: m\n"
        "tools:\n"
        "  delete_all: { level: irreversible }\n"
        '  purge: { level: irreversible, waive_approval: true, reason: "nightly gc" }\n'
        "---\n"
        "Body.\n"
    )
    output = _render(text)
    assert "  delete_all: irreversible, approval required (from file)" in output
    assert "  purge: irreversible, approval waived (from file)" in output
    assert "irreversible tools:\n  - delete_all\n  - purge" in output
    assert "approval waivers:\n  - purge: nightly gc" in output


def test_render_lists_configured_policies() -> None:
    text = (
        "---\n"
        "name: guarded\n"
        "models:\n"
        "  default: m\n"
        "tools:\n"
        "  make_payment: { level: irreversible }\n"
        "policies:\n"
        '  - email_only_to: ["@acme.com"]\n'
        "  - spend_limit: { max_usd: 100 }\n"
        "---\n"
        "Body.\n"
    )
    output = _render(text)
    assert "  email_only_to: @acme.com (from file)" in output
    assert "  spend_limit: max_usd=100 (from file)" in output


def test_render_shows_none_when_no_policies() -> None:
    text = (
        "---\n"
        "name: plain\n"
        "models:\n"
        "  default: m\n"
        "tools:\n"
        "  read_inbox: read\n"
        "---\n"
        "Body.\n"
    )
    assert "policies:\n  none (default)" in _render(text)


def test_check_valid_file_exits_zero_and_prints_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = runner.invoke(app, ["check", str(INBOX)])
    assert result.exit_code == 0
    # The effective config is printed, followed by the api-keys report.
    assert INBOX_SNAPSHOT in result.output
    assert "api keys:\n  ANTHROPIC_API_KEY: MISSING (for anthropic)" in result.output


def test_check_reports_a_set_key_without_printing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret-value-123456")
    result = runner.invoke(app, ["check", str(INBOX)])
    assert result.exit_code == 0
    assert "ANTHROPIC_API_KEY: set (for anthropic)" in result.output
    assert "sk-ant-super-secret-value-123456" not in result.output  # never printed


def test_check_reports_no_keys_for_a_keyless_provider(tmp_path: Path) -> None:
    agent = tmp_path / "fake.md"
    agent.write_text(
        "---\nname: t\nmodels: { default: fake/x }\ntools: { read_inbox: read }\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    result = runner.invoke(app, ["check", str(agent)])
    assert result.exit_code == 0
    assert "api keys:\n  none required" in result.output


def test_check_invalid_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["check", str(BAD)])
    assert result.exit_code == 1


def test_check_missing_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["check", "does/not/exist.md"])
    assert result.exit_code == 1
