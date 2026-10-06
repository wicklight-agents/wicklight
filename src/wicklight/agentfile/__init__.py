"""Parsing and validation of the agent file (``agent.md``).

YAML frontmatter holds the rules the harness enforces (model, tools,
permissions, policies, limits, routes); the Markdown body holds instructions
the model may or may not follow.
"""

from __future__ import annotations

from wicklight.agentfile.config import (
    DEFAULT_MAX_COST_USD,
    DEFAULT_MAX_STEPS,
    DEFAULT_TIMEOUT_SECONDS,
    UNLISTED_TOOL_LEVEL,
    EffectiveConfig,
    EffectiveLimits,
    EffectiveModels,
    EffectiveTool,
    Source,
    Sourced,
    build_effective_config,
)
from wicklight.agentfile.errors import (
    AgentFileIssue,
    AgentFileValidationError,
    check_agent_file,
    check_agent_path,
    parse_and_validate,
)
from wicklight.agentfile.parser import AgentFile, AgentFileError, parse_agent_file
from wicklight.agentfile.render import render_effective_config
from wicklight.agentfile.schema import (
    AgentConfig,
    Approval,
    Limits,
    ModelsConfig,
    PermissionLevel,
    Route,
    ToolSpec,
    agent_config_json_schema,
    validate_frontmatter,
)

__all__ = [
    "DEFAULT_MAX_COST_USD",
    "DEFAULT_MAX_STEPS",
    "DEFAULT_TIMEOUT_SECONDS",
    "UNLISTED_TOOL_LEVEL",
    "AgentConfig",
    "AgentFile",
    "AgentFileError",
    "AgentFileIssue",
    "AgentFileValidationError",
    "Approval",
    "EffectiveConfig",
    "EffectiveLimits",
    "EffectiveModels",
    "EffectiveTool",
    "Limits",
    "ModelsConfig",
    "PermissionLevel",
    "Route",
    "Source",
    "Sourced",
    "ToolSpec",
    "agent_config_json_schema",
    "build_effective_config",
    "check_agent_file",
    "check_agent_path",
    "parse_agent_file",
    "parse_and_validate",
    "render_effective_config",
    "validate_frontmatter",
]
