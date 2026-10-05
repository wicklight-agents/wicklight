"""Parsing and validation of the agent file (``agent.md``).

YAML frontmatter holds the rules the harness enforces (model, tools,
permissions, policies, limits, routes); the Markdown body holds instructions
the model may or may not follow.
"""

from __future__ import annotations

from wicklight.agentfile.parser import AgentFile, AgentFileError, parse_agent_file

__all__ = ["AgentFile", "AgentFileError", "parse_agent_file"]
