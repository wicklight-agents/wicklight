"""Tests for the agent-frontmatter Pydantic schema (DTN-194)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from wicklight.agentfile import (
    AgentConfig,
    Approval,
    PermissionLevel,
    agent_config_json_schema,
    parse_agent_file,
    validate_frontmatter,
)

# The full frontmatter from the solution brief, as plain Python.
EXAMPLE: dict[str, Any] = {
    "name": "inbox-summarizer",
    "models": {
        "default": "anthropic/claude-sonnet",
        "routes": [
            {"when": {"step": "planning"}, "use": "anthropic/claude-opus"},
            {"when": {"context_tokens": ">100k"}, "use": "google/gemini-pro"},
            {"when": {"data": "sensitive"}, "use": "local/llama"},
        ],
        "fallback": ["openai/gpt-5", "local/llama"],
    },
    "tools": {
        "read_inbox": "read",
        "send_email": {"level": "write", "approval": "required"},
    },
    "policies": [{"email_only_to": ["@mycompany.com"]}],
    "limits": {"max_steps": 20},
}


def test_validates_the_brief_example() -> None:
    config = validate_frontmatter(EXAMPLE)
    assert config.name == "inbox-summarizer"
    assert config.models.default == "anthropic/claude-sonnet"
    assert config.models.fallback == ["openai/gpt-5", "local/llama"]
    assert len(config.models.routes) == 3
    assert config.models.routes[0].use == "anthropic/claude-opus"
    assert config.limits is not None
    assert config.limits.max_steps == 20


def test_tool_shorthand_and_full_form() -> None:
    config = validate_frontmatter(EXAMPLE)
    # Bare string shorthand expands to a ToolSpec.
    assert config.tools["read_inbox"].level is PermissionLevel.READ
    assert config.tools["read_inbox"].approval is None
    assert config.tools["read_inbox"].waiver is False
    # Full mapping form.
    send = config.tools["send_email"]
    assert send.level is PermissionLevel.WRITE
    assert send.approval is Approval.REQUIRED


def test_parses_and_validates_end_to_end() -> None:
    text = (
        "---\n"
        "name: demo\n"
        "models:\n"
        "  default: anthropic/claude-sonnet\n"
        "tools:\n"
        "  read_inbox: read\n"
        "---\n"
        "Body.\n"
    )
    agent = parse_agent_file(text)
    config = validate_frontmatter(agent.frontmatter)
    assert config.name == "demo"
    assert config.tools["read_inbox"].level is PermissionLevel.READ


def test_unknown_top_level_key_is_rejected() -> None:
    bad = {**EXAMPLE, "modles": {}}  # typo for "models"
    with pytest.raises(ValidationError) as exc_info:
        validate_frontmatter(bad)
    message = str(exc_info.value)
    assert "Extra inputs are not permitted" in message
    assert "modles" in message


def test_unknown_nested_key_is_rejected() -> None:
    bad = {"name": "x", "models": {"default": "m"}, "limits": {"max_stepz": 5}}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validate_frontmatter(bad)


def test_invalid_permission_level_is_rejected() -> None:
    bad = {"name": "x", "models": {"default": "m"}, "tools": {"t": "delete"}}
    with pytest.raises(ValidationError):
        validate_frontmatter(bad)


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="models"):
        validate_frontmatter({"name": "x"})


def test_json_schema_export() -> None:
    schema = agent_config_json_schema()
    assert schema["title"] == "AgentConfig"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"name", "models"}
    # Permission levels are enumerated for autocompletion.
    perm = schema["$defs"]["PermissionLevel"]
    assert set(perm["enum"]) == {"off", "read", "write", "irreversible"}


def test_defaults_for_optional_collections() -> None:
    config = AgentConfig.model_validate({"name": "x", "models": {"default": "m"}})
    assert config.tools == {}
    assert config.policies == []
    assert config.limits is None
