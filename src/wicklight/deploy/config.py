"""The effective deployment: what ``check`` prints for a deploy file.

Resolves triggers, secret status (set or missing — never the value), and the
egress allowlist into a small, printable summary. The egress allowlist here is
the author's ``extra_hosts``; the model-provider and tool hosts are added when
the container is built (DTN-254).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from wicklight.deploy.schema import (
    DeployConfig,
    SecretSource,
    SecretSpec,
    TriggerSpec,
)


@dataclass(frozen=True)
class SecretStatus:
    """A secret's resolution, with status but never its value."""

    key: str
    source: str
    detail: str  # env var name, file path, or keychain item
    status: str  # "set", "MISSING", or "deferred"


@dataclass(frozen=True)
class EffectiveDeployment:
    """A deploy file's settings, resolved for display."""

    name: str
    agent: str
    agent_name: str | None
    triggers: list[str]
    secrets: list[SecretStatus]
    egress_extra_hosts: list[str]
    traces: str


def build_effective_deployment(
    config: DeployConfig,
    *,
    base_dir: Path,
    agent_name: str | None = None,
    env: Mapping[str, str] | None = None,
) -> EffectiveDeployment:
    """Resolve ``config`` for display. ``base_dir`` is the deploy file's folder."""
    environ = os.environ if env is None else env
    return EffectiveDeployment(
        name=config.name,
        agent=config.agent,
        agent_name=agent_name,
        triggers=[_describe_trigger(trigger) for trigger in config.triggers],
        secrets=[
            _secret_status(key, spec, base_dir=base_dir, env=environ)
            for key, spec in config.secrets.items()
        ],
        egress_extra_hosts=list(config.egress.extra_hosts),
        traces=config.traces,
    )


def _describe_trigger(trigger: TriggerSpec) -> str:
    if trigger.schedule is not None:
        return f"schedule: {trigger.schedule}"
    path = trigger.webhook.path if trigger.webhook else "/run"
    return f"webhook: POST {path}"


def _secret_status(
    key: str, spec: SecretSpec, *, base_dir: Path, env: Mapping[str, str]
) -> SecretStatus:
    source = spec.source.value
    if spec.source is SecretSource.ENV:
        var = spec.name or key
        status = "set" if var in env else "MISSING"
        return SecretStatus(key, source, var, status)
    if spec.source is SecretSource.FILE:
        # spec.path is required for a file secret (enforced by the schema).
        raw = Path(spec.path or "")
        resolved = raw if raw.is_absolute() else base_dir / raw
        status = "set" if resolved.exists() else "MISSING"
        return SecretStatus(key, source, str(spec.path), status)
    # keychain: not checkable portably at check time; resolved on the host at start.
    return SecretStatus(key, source, spec.name or key, "deferred")


def render_effective_deployment(eff: EffectiveDeployment) -> str:
    """Render the effective deployment as the text ``check`` prints."""
    agent_label = f"{eff.agent} ({eff.agent_name})" if eff.agent_name else eff.agent
    lines = [
        f"deployment: {eff.name}",
        f"agent: {agent_label}",
        "",
        "triggers:",
    ]
    if eff.triggers:
        lines.extend(f"  {trigger}" for trigger in eff.triggers)
    else:
        lines.append("  none")

    lines.extend(["", "secrets:"])
    if eff.secrets:
        for secret in eff.secrets:
            lines.append(
                f"  {secret.key}: from {secret.source} "
                f"({secret.detail}) — {secret.status}"
            )
        lines.append("  (values are read on the host at start, never printed)")
    else:
        lines.append("  none")

    lines.extend(["", f"traces: {eff.traces}", "", "egress:"])
    if eff.egress_extra_hosts:
        lines.extend(f"  {host}" for host in eff.egress_extra_hosts)
    else:
        lines.append("  no extra hosts")
    lines.append("  (model-provider and tool hosts are added at deploy time)")

    return "\n".join(lines)
