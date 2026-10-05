"""Tests for the agent-file parser (DTN-193)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wicklight.agentfile import AgentFile, AgentFileError, parse_agent_file

# A sample agent file. Line numbers (1-indexed) matter for the assertions:
#  1: ---
#  2: name: inbox-summarizer
#  3: models:
#  4:   default: anthropic/claude-sonnet
#  5:   routes:
#  6:     - when: planning
#  7:       use: anthropic/claude-opus
#  8: tools:
#  9:   read_inbox: read
# 10:   send_email: { level: write, approval: required }
# 11: policies:
# 12:   - email_only_to: ["@mycompany.com"]
# 13: limits: { max_steps: 20 }
# 14: ---
# 15: You summarize this week's emails and draft replies.
# 16: Be concise.
SAMPLE = """\
---
name: inbox-summarizer
models:
  default: anthropic/claude-sonnet
  routes:
    - when: planning
      use: anthropic/claude-opus
tools:
  read_inbox: read
  send_email: { level: write, approval: required }
policies:
  - email_only_to: ["@mycompany.com"]
limits: { max_steps: 20 }
---
You summarize this week's emails and draft replies.
Be concise.
"""


def test_body_is_extracted_verbatim() -> None:
    agent = parse_agent_file(SAMPLE)
    assert agent.body == (
        "You summarize this week's emails and draft replies.\nBe concise.\n"
    )


def test_frontmatter_values_are_plain_python() -> None:
    agent = parse_agent_file(SAMPLE)
    assert agent.frontmatter["name"] == "inbox-summarizer"
    assert agent.frontmatter["models"]["default"] == "anthropic/claude-sonnet"
    assert agent.frontmatter["limits"] == {"max_steps": 20}
    # Plain dict/list, not ruamel's CommentedMap/CommentedSeq.
    assert type(agent.frontmatter) is dict
    assert type(agent.frontmatter["models"]) is dict
    assert type(agent.frontmatter["policies"]) is list


@pytest.mark.parametrize(
    ("key_path", "expected_line"),
    [
        (("name",), 2),
        (("models",), 3),
        (("models", "default"), 4),
        (("models", "routes"), 5),
        (("models", "routes", 0), 6),
        (("models", "routes", 0, "when"), 6),
        (("models", "routes", 0, "use"), 7),
        (("tools",), 8),
        (("tools", "read_inbox"), 9),
        (("tools", "send_email"), 10),
        (("tools", "send_email", "level"), 10),
        (("tools", "send_email", "approval"), 10),
        (("policies",), 11),
        (("policies", 0), 12),
        (("policies", 0, "email_only_to"), 12),
        (("limits",), 13),
        (("limits", "max_steps"), 13),
    ],
)
def test_line_of_tracks_nested_keys(
    key_path: tuple[str | int, ...], expected_line: int
) -> None:
    agent = parse_agent_file(SAMPLE)
    assert agent.line_of(*key_path) == expected_line


def test_line_of_returns_none_for_unknown_path() -> None:
    agent = parse_agent_file(SAMPLE)
    assert agent.line_of("does", "not", "exist") is None


def test_empty_frontmatter_is_allowed() -> None:
    agent = parse_agent_file("---\n---\njust a body\n")
    assert agent.frontmatter == {}
    assert agent.body == "just a body\n"


def test_from_path_reads_file(tmp_path: Path) -> None:
    agent_path = tmp_path / "agent.md"
    agent_path.write_text(SAMPLE, encoding="utf-8")
    agent = AgentFile.from_path(agent_path)
    assert agent.path == agent_path
    assert agent.line_of("models", "default") == 4


def test_missing_opening_delimiter_is_reported() -> None:
    with pytest.raises(AgentFileError) as exc_info:
        parse_agent_file("name: inbox-summarizer\n")
    assert exc_info.value.line == 1
    assert "opening" in str(exc_info.value)


def test_unterminated_frontmatter_is_reported() -> None:
    with pytest.raises(AgentFileError, match="unterminated"):
        parse_agent_file("---\nname: inbox-summarizer\n")


def test_invalid_yaml_is_reported_with_a_line() -> None:
    with pytest.raises(AgentFileError, match="invalid YAML") as exc_info:
        parse_agent_file("---\nmodels: [unclosed\n---\nbody\n")
    assert exc_info.value.line is not None


def test_non_mapping_frontmatter_is_rejected() -> None:
    with pytest.raises(AgentFileError, match="must be a mapping"):
        parse_agent_file("---\n- a\n- b\n---\n")
