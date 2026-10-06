"""Render an effective config as readable text for ``wicklight check``.

The output makes the harness's reasoning visible: every value shows whether it
came from the file or a default, and irreversible tools and approval waivers —
the settings most likely to be dangerous — are called out in their own
sections.
"""

from __future__ import annotations

from typing import Any

from wicklight.agentfile.config import EffectiveConfig, EffectiveTool, Sourced
from wicklight.agentfile.schema import PermissionLevel


def render_effective_config(config: EffectiveConfig) -> str:
    """Render ``config`` as a readable, deterministic multi-line string."""
    models = config.models
    limits = config.limits
    fallback = ", ".join(models.fallback.value) if models.fallback.value else "none"

    lines: list[str] = [
        f"agent: {config.name.value}",
        "",
        "models:",
        f"  default: {models.default.value} {_src(models.default)}",
        f"  routes: {len(models.routes.value)} {_src(models.routes)}",
        f"  fallback: {fallback} {_src(models.fallback)}",
        "",
        "limits:",
        f"  max_steps: {limits.max_steps.value} {_src(limits.max_steps)}",
        f"  max_cost: ${limits.max_cost.value:.2f} {_src(limits.max_cost)}",
        f"  timeout: {limits.timeout.value:g}s {_src(limits.timeout)}",
        "",
        "tools:",
    ]

    if config.tools:
        for name, tool in config.tools.items():
            summary = ", ".join(_tool_summary(tool))
            lines.append(f"  {name}: {summary} {_src(tool.level)}")
    else:
        lines.append("  none (all tools off by default)")
    lines.append("")

    irreversible = [
        name
        for name, tool in config.tools.items()
        if tool.level.value is PermissionLevel.IRREVERSIBLE
    ]
    waivers = [name for name, tool in config.tools.items() if tool.waiver.value]

    lines += _tool_list("irreversible tools", irreversible)
    lines.append("")
    lines += _tool_list("approval waivers", waivers)

    return "\n".join(lines)


def _tool_summary(tool: EffectiveTool) -> list[str]:
    parts = [tool.level.value.value]
    if tool.approval_required.value:
        parts.append("approval required")
    if tool.waiver.value:
        parts.append("waiver")
    return parts


def _tool_list(heading: str, names: list[str]) -> list[str]:
    lines = [f"{heading}:"]
    if names:
        lines += [f"  - {name}" for name in names]
    else:
        lines.append("  none")
    return lines


def _src(sourced: Sourced[Any]) -> str:
    return "(from file)" if sourced.from_file else "(default)"
