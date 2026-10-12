"""Render an effective config as readable text for ``wicklight check``.

The output makes the harness's reasoning visible: every value shows whether it
came from the file or a default, and irreversible tools and approval waivers —
the settings most likely to be dangerous — are called out in their own
sections.
"""

from __future__ import annotations

from typing import Any, cast

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

    lines += _render_policies(config.policies)
    lines.append("")

    irreversible = [
        name
        for name, tool in config.tools.items()
        if tool.level.value is PermissionLevel.IRREVERSIBLE
    ]

    lines += _tool_list("irreversible tools", irreversible)
    lines.append("")
    lines += _render_waivers(config)

    return "\n".join(lines)


def _tool_summary(tool: EffectiveTool) -> list[str]:
    parts = [tool.level.value.value]
    if tool.approval_required.value:
        parts.append("approval required")
    if tool.waiver.value:
        parts.append("approval waived")
    return parts


def _render_waivers(config: EffectiveConfig) -> list[str]:
    # Waivers drop a safety default, so `check` calls them out with their reason.
    waived = [
        (name, tool.waiver_reason.value or "(no reason given)")
        for name, tool in config.tools.items()
        if tool.waiver.value
    ]
    lines = ["approval waivers:"]
    if waived:
        lines += [f"  - {name}: {reason}" for name, reason in waived]
    else:
        lines.append("  none")
    return lines


def _render_policies(policies: Sourced[list[dict[str, Any]]]) -> list[str]:
    lines = ["policies:"]
    entries = policies.value
    if not entries:
        lines.append("  none (default)")
        return lines
    for entry in entries:
        for name, cfg in entry.items():
            lines.append(f"  {name}: {_policy_summary(cfg)} (from file)")
    return lines


def _policy_summary(cfg: Any) -> str:
    """A compact one-line summary of a policy's config value."""
    if isinstance(cfg, dict):
        items = cast("dict[str, Any]", cfg).items()
        return ", ".join(f"{key}={value}" for key, value in items) or "(no config)"
    if isinstance(cfg, list):
        rendered = ", ".join(str(item) for item in cast("list[Any]", cfg))
        return rendered or "(empty)"
    if cfg is None:
        return "(no config)"
    return str(cfg)


def _tool_list(heading: str, names: list[str]) -> list[str]:
    lines = [f"{heading}:"]
    if names:
        lines += [f"  - {name}" for name in names]
    else:
        lines.append("  none")
    return lines


def _src(sourced: Sourced[Any]) -> str:
    return "(from file)" if sourced.from_file else "(default)"
