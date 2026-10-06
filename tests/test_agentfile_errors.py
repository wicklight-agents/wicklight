"""Tests for human-friendly validation errors (DTN-196).

Each fixture in ``tests/fixtures/agentfile/`` exercises one error kind; the
tests assert the exact message and line number a beginner would see.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wicklight.agentfile import AgentFileValidationError, check_agent_path

FIXTURES = Path(__file__).parent / "fixtures" / "agentfile"


def _messages(fixture: str) -> list[str]:
    with pytest.raises(AgentFileValidationError) as exc_info:
        check_agent_path(FIXTURES / fixture)
    return [issue.message for issue in exc_info.value.issues]


@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        (
            "unknown_key.md",
            ["unknown_key.md line 5: unexpected key 'modles'. Did you mean 'models'?"],
        ),
        (
            "invalid_level.md",
            [
                'invalid_level.md line 6: tools.send_email.level: "writ" is not a '
                "valid level. Use one of: off, read, write, irreversible."
            ],
        ),
        (
            "missing_required.md",
            ["missing_required.md: 'models' is required."],
        ),
        (
            "invalid_type.md",
            [
                'invalid_type.md line 6: limits.max_steps: "twenty" is not a valid '
                "integer."
            ],
        ),
        (
            "no_frontmatter.md",
            [
                "no_frontmatter.md line 1: missing opening frontmatter delimiter: "
                "expected '---' on line 1"
            ],
        ),
    ],
)
def test_fixture_produces_expected_message(fixture: str, expected: list[str]) -> None:
    assert _messages(fixture) == expected


def test_all_errors_are_reported_in_one_pass() -> None:
    assert _messages("multiple_errors.md") == [
        'multiple_errors.md line 6: tools.send_email.level: "writ" is not a valid '
        "level. Use one of: off, read, write, irreversible.",
        'multiple_errors.md line 8: limits.max_steps: "twenty" is not a valid integer.',
        "multiple_errors.md line 9: unexpected key 'bogus'.",
    ]


def test_bad_yaml_reports_a_line() -> None:
    with pytest.raises(AgentFileValidationError) as exc_info:
        check_agent_path(FIXTURES / "bad_yaml.md")
    (issue,) = exc_info.value.issues
    assert issue.line == 3
    assert issue.message.startswith("bad_yaml.md line 3: invalid YAML in frontmatter:")


def test_valid_file_returns_config(tmp_path: Path) -> None:
    good = tmp_path / "agent.md"
    good.write_text(
        "---\nname: demo\nmodels:\n  default: anthropic/sonnet\n---\nBody.\n",
        encoding="utf-8",
    )
    config = check_agent_path(good)
    assert config.name == "demo"
