"""Parsing and validation of the agent file (``agent.md``).

YAML frontmatter holds the rules the harness enforces (model, tools,
permissions, policies, limits, routes); the Markdown body holds instructions
the model may or may not follow.
"""

from __future__ import annotations

from wicklight.agentfile.parser import AgentFile, AgentFileError, parse_agent_file
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
    "AgentConfig",
    "AgentFile",
    "AgentFileError",
    "Approval",
    "Limits",
    "ModelsConfig",
    "PermissionLevel",
    "Route",
    "ToolSpec",
    "agent_config_json_schema",
    "parse_agent_file",
    "validate_frontmatter",
]
