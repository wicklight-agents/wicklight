"""Tests for safe defaults and the effective config (DTN-195)."""

from __future__ import annotations

from typing import Any

from wicklight.agentfile import (
    DEFAULT_MAX_COST_USD,
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_SECONDS,
    PermissionLevel,
    Source,
    build_effective_config,
    validate_frontmatter,
)


def _effective(raw: dict[str, Any]):
    return build_effective_config(validate_frontmatter(raw), provided=raw)


MINIMAL: dict[str, Any] = {"name": "demo", "models": {"default": "anthropic/sonnet"}}


def test_unlisted_tools_are_off() -> None:
    eff = _effective({**MINIMAL, "tools": {"read_inbox": "read"}})
    assert eff.tool_level("read_inbox") is PermissionLevel.READ
    # A tool that is not listed is off, with no approval.
    assert eff.tool_level("send_email") is PermissionLevel.OFF
    assert eff.requires_approval("send_email") is False


def test_limits_always_set_with_documented_defaults() -> None:
    eff = _effective(MINIMAL)
    assert eff.limits.max_steps.value == DEFAULT_MAX_STEPS
    assert eff.limits.max_steps.source is Source.DEFAULT
    assert eff.limits.max_cost.value == DEFAULT_MAX_COST_USD
    assert eff.limits.max_cost.source is Source.DEFAULT
    assert eff.limits.timeout.value == DEFAULT_TIMEOUT_SECONDS
    assert eff.limits.timeout.source is Source.DEFAULT


def test_limits_from_file_are_marked_file() -> None:
    eff = _effective({**MINIMAL, "limits": {"max_steps": 5}})
    assert eff.limits.max_steps.value == 5
    assert eff.limits.max_steps.source is Source.FILE
    # Unspecified sibling limits still fall back to defaults.
    assert eff.limits.max_cost.source is Source.DEFAULT


def test_irreversible_tool_requires_approval_by_default() -> None:
    eff = _effective({**MINIMAL, "tools": {"delete_file": {"level": "irreversible"}}})
    tool = eff.tools["delete_file"]
    assert tool.approval_required.value is True
    assert tool.approval_required.source is Source.DEFAULT
    assert eff.requires_approval("delete_file") is True


def test_irreversible_tool_with_waiver_skips_approval() -> None:
    eff = _effective(
        {**MINIMAL, "tools": {"delete_file": {"level": "irreversible", "waiver": True}}}
    )
    tool = eff.tools["delete_file"]
    assert tool.approval_required.value is False
    assert tool.approval_required.source is Source.FILE
    assert tool.waiver.value is True
    assert tool.waiver.source is Source.FILE


def test_explicit_approval_on_write_tool_is_from_file() -> None:
    eff = _effective(
        {**MINIMAL, "tools": {"send_email": {"level": "write", "approval": "required"}}}
    )
    tool = eff.tools["send_email"]
    assert tool.approval_required.value is True
    assert tool.approval_required.source is Source.FILE


def test_read_tool_has_no_approval_by_default() -> None:
    eff = _effective({**MINIMAL, "tools": {"read_inbox": "read"}})
    tool = eff.tools["read_inbox"]
    assert tool.approval_required.value is False
    assert tool.approval_required.source is Source.DEFAULT
    assert tool.waiver.value is False
    assert tool.waiver.source is Source.DEFAULT


def test_name_and_default_model_come_from_file() -> None:
    eff = _effective(MINIMAL)
    assert eff.name.value == "demo"
    assert eff.name.source is Source.FILE
    assert eff.models.default.value == "anthropic/sonnet"
    assert eff.models.default.source is Source.FILE


def test_optional_collections_track_presence() -> None:
    absent = _effective(MINIMAL)
    assert absent.models.routes.source is Source.DEFAULT
    assert absent.models.fallback.source is Source.DEFAULT
    assert absent.policies.source is Source.DEFAULT

    present = _effective(
        {
            **MINIMAL,
            "models": {"default": "m", "routes": [], "fallback": ["x"]},
            "policies": [{"spend_limit": 10}],
        }
    )
    # Present in the file, even when empty, is sourced from the file.
    assert present.models.routes.source is Source.FILE
    assert present.models.fallback.source is Source.FILE
    assert present.policies.source is Source.FILE
