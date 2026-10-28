"""Derive the egress allowlist for a deployment (DTN-254).

The allowlist is derived automatically, never hand-maintained: the hosts of the
model providers the agent can route to, plus the hosts each enabled tool
declares (``network_hosts``), plus the deploy file's ``egress.extra_hosts``.
``check`` prints it; the egress proxy enforces it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from urllib.parse import urlparse

from wicklight.agentfile.config import EffectiveConfig
from wicklight.agentfile.schema import PermissionLevel
from wicklight.contracts import (
    ProviderError,
    ProviderRegistry,
    ToolError,
    ToolRegistry,
)
from wicklight.deploy.schema import DeployConfig


@dataclass(frozen=True)
class AllowedHost:
    """One allowed host and where it came from (for the ``check`` display)."""

    host: str
    source: str  # "provider:anthropic", "tool:send_email", or "extra_hosts"


def model_ids(config: EffectiveConfig) -> list[str]:
    """Every ``provider/model`` the agent can route to: default, routes, fallback."""
    models = config.models
    return [
        models.default.value,
        *(route.use for route in models.routes.value),
        *models.fallback.value,
    ]


def derive_allowlist(
    deploy: DeployConfig,
    agent: EffectiveConfig,
    *,
    provider_registry: ProviderRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
) -> list[AllowedHost]:
    """Derive the full egress allowlist, in a stable, de-duplicated order."""
    providers = provider_registry or ProviderRegistry.discover()
    tools = tool_registry or ToolRegistry.discover()

    # host -> source; the first source that introduces a host wins.
    found: dict[str, str] = {}

    for model_id in model_ids(agent):
        name = model_id.split("/", 1)[0]
        host = _provider_host(name, registry=providers)
        if host is not None:
            found.setdefault(host, f"provider:{name}")

    for tool_name, effective in agent.tools.items():
        if effective.level.value is PermissionLevel.OFF:
            continue
        try:
            declared = tools.get(tool_name)
        except ToolError:
            continue  # a tool the agent lists but isn't installed here
        for host in getattr(declared, "network_hosts", []):
            if isinstance(host, str) and host:
                found.setdefault(host, f"tool:{tool_name}")

    for host in deploy.egress.extra_hosts:
        found.setdefault(host, "extra_hosts")

    return [AllowedHost(host, source) for host, source in found.items()]


def allowlist_hosts(allowlist: Iterable[AllowedHost]) -> list[str]:
    """Just the host names from a derived allowlist."""
    return [entry.host for entry in allowlist]


def host_allowed(host: str, allowlist: Iterable[str]) -> bool:
    """Whether ``host`` is in ``allowlist`` (exact match)."""
    return host in set(allowlist)


def _provider_host(provider_name: str, *, registry: ProviderRegistry) -> str | None:
    try:
        provider = registry.get(provider_name)
    except ProviderError:
        return None  # a provider the agent routes to but isn't installed here
    base = getattr(provider, "base_url", None)
    if not isinstance(base, str) or not base:
        return None
    return urlparse(base).hostname
