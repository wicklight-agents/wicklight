"""Pydantic v2 schema for agent-file frontmatter.

These models validate the rules in an agent file's YAML frontmatter and reject
unknown keys (a typo should be an error, not a silently ignored setting). The
schema is also the source of the JSON Schema used for editor autocompletion.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, field_validator

# Forbid unknown keys everywhere: an unrecognized field is a mistake, and the
# harness would rather fail loudly than silently drop a rule the author meant.
_STRICT = ConfigDict(extra="forbid")


class PermissionLevel(str, Enum):
    """How much a tool is allowed to do, from least to most dangerous."""

    OFF = "off"
    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class Approval(str, Enum):
    """Whether a tool call must be approved by a human before it runs."""

    REQUIRED = "required"


class ToolSpec(BaseModel):
    """A tool's declared permission, plus optional approval and waiver rules."""

    model_config = _STRICT

    level: PermissionLevel
    approval: Approval | None = None
    # Explicit per-tool waiver of the approval an irreversible tool would
    # otherwise require. `check` flags every waiver; the trace records it.
    waiver: bool = False


class Route(BaseModel):
    """One model-routing rule: when the condition matches, use this model."""

    model_config = _STRICT

    # Route-condition semantics (step, context_tokens, data, ...) are enforced
    # by the routing milestone; here it is a free-form mapping.
    when: dict[str, Any]
    use: str


class ModelsConfig(BaseModel):
    """Model selection: a default, optional routes, and optional fallbacks."""

    model_config = _STRICT

    default: str
    routes: list[Route] = []
    fallback: list[str] = []


class Limits(BaseModel):
    """Run limits. Effective defaults are applied by a later step (DTN-195)."""

    model_config = _STRICT

    max_steps: int | None = None
    max_cost: float | None = None
    timeout: float | None = None


class AgentConfig(BaseModel):
    """The validated frontmatter of an agent file."""

    model_config = _STRICT

    name: str
    models: ModelsConfig
    tools: dict[str, ToolSpec] = {}
    # Policy internals are validated by the policy contract (M6); here each
    # policy is a free-form mapping such as {"email_only_to": [...]}.
    policies: list[dict[str, Any]] = []
    limits: Limits | None = None

    @field_validator("tools", mode="before")
    @classmethod
    def _expand_tool_shorthand(cls, value: object) -> object:
        """Allow `tool_name: read` as shorthand for `tool_name: {level: read}`."""
        if not isinstance(value, dict):
            return value
        expanded: dict[Any, Any] = {}
        for name, spec in cast("dict[Any, Any]", value).items():
            expanded[name] = {"level": spec} if isinstance(spec, str) else spec
        return expanded


def validate_frontmatter(data: dict[str, Any]) -> AgentConfig:
    """Validate raw frontmatter (e.g. from :func:`parse_agent_file`).

    Raises :class:`pydantic.ValidationError` on unknown keys or invalid values.
    """
    return AgentConfig.model_validate(data)


def agent_config_json_schema() -> dict[str, Any]:
    """Return the JSON Schema for agent frontmatter, for editor autocompletion."""
    return AgentConfig.model_json_schema()
