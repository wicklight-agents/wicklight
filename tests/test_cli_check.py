"""Tests for the `wicklight check` command (DTN-197)."""

from __future__ import annotations

from pathlib import Path

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
        "  purge: { level: irreversible, waiver: true }\n"
        "---\n"
        "Body.\n"
    )
    output = _render(text)
    assert "  delete_all: irreversible, approval required (from file)" in output
    assert "  purge: irreversible, waiver (from file)" in output
    assert "irreversible tools:\n  - delete_all\n  - purge" in output
    assert "approval waivers:\n  - purge" in output


def test_check_valid_file_exits_zero_and_prints_config() -> None:
    result = runner.invoke(app, ["check", str(INBOX)])
    assert result.exit_code == 0
    assert result.output.rstrip("\n") == INBOX_SNAPSHOT


def test_check_invalid_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["check", str(BAD)])
    assert result.exit_code == 1


def test_check_missing_file_exits_nonzero() -> None:
    result = runner.invoke(app, ["check", "does/not/exist.md"])
    assert result.exit_code == 1
