"""The deploy file: schema, line-numbered errors, and `check` (DTN-252)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from wicklight.cli import app
from wicklight.deploy import (
    DeployFileValidationError,
    build_effective_deployment,
    parse_and_validate_deploy,
    render_effective_deployment,
)

runner = CliRunner()
REPO_ROOT = Path(__file__).parent.parent
EXAMPLE = REPO_ROOT / "examples" / "deploy.yaml"

VALID = """\
name: inbox-summarizer
agent: inbox.md
triggers:
  - schedule: "0 8 * * 1-5"
  - webhook: { path: /run }
secrets:
  EMAIL_TOKEN: { from: env }
traces: ./runs
egress:
  extra_hosts: ["events.example.com"]
"""


def _errors(text: str) -> list[str]:
    with pytest.raises(DeployFileValidationError) as exc:
        parse_and_validate_deploy(text)
    return [issue.message for issue in exc.value.issues]


# --- valid parse --------------------------------------------------------------


def test_valid_deploy_parses() -> None:
    _file, config = parse_and_validate_deploy(VALID)
    assert config.name == "inbox-summarizer"
    assert config.agent == "inbox.md"
    assert len(config.triggers) == 2
    assert config.triggers[0].schedule == "0 8 * * 1-5"
    assert config.triggers[1].webhook is not None
    assert config.secrets["EMAIL_TOKEN"].source.value == "env"
    assert config.egress.extra_hosts == ["events.example.com"]


# --- line-numbered errors, agent-file style -----------------------------------


def test_unknown_key_suggests_a_correction() -> None:
    messages = _errors("name: d\nagent: a.md\ntriggerz: []\n")
    assert any(
        "line 3" in m and "unexpected key 'triggerz'" in m and "triggers" in m
        for m in messages
    )


def test_missing_required_agent_is_reported() -> None:
    assert any("'agent' is required" in m for m in _errors("name: d\n"))


def test_bad_secret_source_lists_valid_options() -> None:
    messages = _errors("name: d\nagent: a.md\nsecrets:\n  T: { from: environment }\n")
    assert any(
        "not a valid secret source" in m and "env, file, keychain" in m
        for m in messages
    )


def test_bad_cron_is_one_clear_error() -> None:
    messages = _errors('name: d\nagent: a.md\ntriggers:\n  - schedule: "0 8 * *"\n')
    assert len(messages) == 1
    assert "5-field cron expression" in messages[0]
    assert "line 4" in messages[0]


def test_trigger_needs_exactly_one_kind() -> None:
    text = (
        'name: d\nagent: a.md\ntriggers:\n  - { schedule: "0 8 * * 1", webhook: {} }\n'
    )
    assert any("exactly one of: schedule, webhook" in m for m in _errors(text))


def test_file_secret_requires_a_path() -> None:
    messages = _errors("name: d\nagent: a.md\nsecrets:\n  K: { from: file }\n")
    assert any("a file secret needs a 'path'" in m for m in messages)


def test_all_problems_reported_in_one_pass() -> None:
    messages = _errors("naem: d\nsecrets:\n  T: { from: nope }\n")
    # Unknown 'naem', missing 'agent', and the bad source all appear at once.
    assert len(messages) >= 3


def test_invalid_yaml_cites_a_line() -> None:
    messages = _errors("name: d\n  bad: : indent\n")
    assert any("invalid YAML" in m for m in messages)


# --- effective deployment (secret status, never values) -----------------------


def test_secret_status_env_and_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "token"
    secret_file.write_text("shhh", encoding="utf-8")
    text = (
        "name: d\nagent: a.md\nsecrets:\n"
        "  SET_ENV: { from: env }\n"
        "  MISSING_ENV: { from: env }\n"
        "  FILE_OK: { from: file, path: token }\n"
        "  FILE_GONE: { from: file, path: nope }\n"
        "  KC: { from: keychain }\n"
    )
    _file, config = parse_and_validate_deploy(text)
    eff = build_effective_deployment(
        config, base_dir=tmp_path, agent_name="a", env={"SET_ENV": "x"}
    )
    status = {s.key: s.status for s in eff.secrets}
    assert status == {
        "SET_ENV": "set",
        "MISSING_ENV": "MISSING",
        "FILE_OK": "set",
        "FILE_GONE": "MISSING",
        "KC": "deferred",
    }
    # The value is never carried on the status.
    assert all("shhh" not in s.detail for s in eff.secrets)


def test_render_shows_triggers_secrets_and_egress() -> None:
    _file, config = parse_and_validate_deploy(VALID)
    eff = build_effective_deployment(
        config, base_dir=Path(), agent_name="inbox-summarizer", env={}
    )
    text = render_effective_deployment(eff)
    assert "deployment: inbox-summarizer" in text
    assert "schedule: 0 8 * * 1-5" in text
    assert "webhook: POST /run" in text
    assert "EMAIL_TOKEN: from env (EMAIL_TOKEN) — MISSING" in text
    assert "events.example.com" in text


# --- CLI: behaves like an agent file under check ------------------------------


def test_cli_check_valid_deploy_file() -> None:
    result = runner.invoke(app, ["check", str(EXAMPLE)])
    assert result.exit_code == 0
    assert "deployment: inbox-summarizer" in result.stdout
    assert "agent: inbox.md (inbox-summarizer)" in result.stdout


def test_cli_check_invalid_deploy_file_exits_1(tmp_path: Path) -> None:
    bad = tmp_path / "deploy.yaml"
    bad.write_text("name: d\ntriggerz: []\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(bad)])
    assert result.exit_code == 1
    assert "unexpected key 'triggerz'" in result.output
    assert "'agent' is required" in result.output


def test_cli_check_reports_missing_agent_file(tmp_path: Path) -> None:
    deploy = tmp_path / "deploy.yaml"
    deploy.write_text("name: d\nagent: nope.md\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(deploy)])
    assert result.exit_code == 1
    assert "agent file not found: nope.md" in result.output
