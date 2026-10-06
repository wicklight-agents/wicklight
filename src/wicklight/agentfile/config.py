"""Effective configuration: the agent file with safe defaults filled in.

The agent file only states what the author chose to state. The harness layers
safe defaults on top — unlisted tools are off, limits are always set, and
irreversible tools require approval unless explicitly waived — and records, for
every value, whether it came from the file or from a default. That provenance
is what ``wicklight check`` prints and what the trace cites, so nothing is
silently assumed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, cast

from wicklight.agentfile.schema import (
    AgentConfig,
    Approval,
    PermissionLevel,
    Route,
    ToolSpec,
)

# --- Documented safe defaults -------------------------------------------------

#: A tool not listed in the agent file is off (callable only if listed).
UNLISTED_TOOL_LEVEL = PermissionLevel.OFF
#: Default maximum number of steps in a run.
DEFAULT_MAX_STEPS = 20
#: Default maximum spend per run, in US dollars.
DEFAULT_MAX_COST_USD = 1.0
#: Default wall-clock timeout for a run, in seconds.
DEFAULT_TIMEOUT_SECONDS = 300.0

_T = TypeVar("_T")


class Source(str, Enum):
    """Where an effective value came from."""

    FILE = "file"
    DEFAULT = "default"


@dataclass(frozen=True)
class Sourced(Generic[_T]):
    """An effective value tagged with whether it came from the file or a default."""

    value: _T
    source: Source

    @property
    def from_file(self) -> bool:
        return self.source is Source.FILE


@dataclass(frozen=True)
class EffectiveTool:
    """A listed tool's effective permission, approval, and waiver settings."""

    level: Sourced[PermissionLevel]
    approval_required: Sourced[bool]
    waiver: Sourced[bool]


@dataclass(frozen=True)
class EffectiveModels:
    default: Sourced[str]
    routes: Sourced[list[Route]]
    fallback: Sourced[list[str]]


@dataclass(frozen=True)
class EffectiveLimits:
    max_steps: Sourced[int]
    max_cost: Sourced[float]
    timeout: Sourced[float]


@dataclass(frozen=True)
class EffectiveConfig:
    """An agent config with every default filled in and its source recorded."""

    name: Sourced[str]
    models: EffectiveModels
    tools: dict[str, EffectiveTool]
    policies: Sourced[list[dict[str, Any]]]
    limits: EffectiveLimits

    def tool_level(self, name: str) -> PermissionLevel:
        """Effective permission for a tool: its listed level, or off if unlisted."""
        tool = self.tools.get(name)
        return tool.level.value if tool is not None else UNLISTED_TOOL_LEVEL

    def requires_approval(self, name: str) -> bool:
        """Whether a listed tool needs human approval. Unlisted tools are off."""
        tool = self.tools.get(name)
        return tool.approval_required.value if tool is not None else False


def build_effective_config(
    config: AgentConfig, *, provided: Mapping[str, Any]
) -> EffectiveConfig:
    """Fill in safe defaults, recording the source of every value.

    ``provided`` is the raw frontmatter mapping (before validation), used to tell
    whether an optional value was present in the file or is a default.
    """
    models_raw = _as_mapping(provided.get("models"))
    tools_raw = _as_mapping(provided.get("tools"))

    return EffectiveConfig(
        name=Sourced(config.name, Source.FILE),
        models=EffectiveModels(
            default=Sourced(config.models.default, Source.FILE),
            routes=_sourced_if_present(config.models.routes, "routes" in models_raw),
            fallback=_sourced_if_present(
                config.models.fallback, "fallback" in models_raw
            ),
        ),
        tools={
            name: _effective_tool(spec, _as_mapping(tools_raw.get(name)))
            for name, spec in config.tools.items()
        },
        policies=_sourced_if_present(config.policies, "policies" in provided),
        limits=_effective_limits(config),
    )


def _effective_tool(spec: ToolSpec, raw: Mapping[str, Any]) -> EffectiveTool:
    # A listed tool's level always comes from the file.
    level = Sourced(spec.level, Source.FILE)
    waiver = Sourced(spec.waiver, Source.FILE if "waiver" in raw else Source.DEFAULT)

    if spec.approval is Approval.REQUIRED:
        approval = Sourced(True, Source.FILE)
    elif spec.level is PermissionLevel.IRREVERSIBLE and not spec.waiver:
        # Safe default: irreversible tools require approval unless waived.
        approval = Sourced(True, Source.DEFAULT)
    elif spec.level is PermissionLevel.IRREVERSIBLE:
        # Approval dropped because the file explicitly waived it.
        approval = Sourced(False, Source.FILE)
    else:
        approval = Sourced(False, Source.DEFAULT)

    return EffectiveTool(level=level, approval_required=approval, waiver=waiver)


def _effective_limits(config: AgentConfig) -> EffectiveLimits:
    limits = config.limits
    return EffectiveLimits(
        max_steps=_sourced_or_default(
            None if limits is None else limits.max_steps, DEFAULT_MAX_STEPS
        ),
        max_cost=_sourced_or_default(
            None if limits is None else limits.max_cost, DEFAULT_MAX_COST_USD
        ),
        timeout=_sourced_or_default(
            None if limits is None else limits.timeout, DEFAULT_TIMEOUT_SECONDS
        ),
    )


def _sourced_or_default(file_value: _T | None, default: _T) -> Sourced[_T]:
    """From the file when set, otherwise the documented default."""
    if file_value is None:
        return Sourced(default, Source.DEFAULT)
    return Sourced(file_value, Source.FILE)


def _sourced_if_present(value: _T, present: bool) -> Sourced[_T]:
    """Tag a value FILE if its key was present in the file, else DEFAULT."""
    return Sourced(value, Source.FILE if present else Source.DEFAULT)


def _as_mapping(value: object) -> Mapping[str, Any]:
    """Return ``value`` if it is a mapping, else an empty mapping."""
    if isinstance(value, Mapping):
        return cast("Mapping[str, Any]", value)
    return {}
