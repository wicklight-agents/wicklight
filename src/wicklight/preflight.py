"""Pre-run capability checks (DTN-232).

Fail at check time, not mid-run, when an agent asks for something its provider
can't do. ``wicklight check`` runs the full preflight — the provider plugin is
installed, its contract version is supported, and its declared capabilities
cover the agent's needs. The core loop runs the capability comparison again at
the start of every run and stops with an ``error`` event if it fails.

The needs compared are the ones an agent file states statically: whether tools
are enabled (needs tool calling) and a rough estimate of the context size.
Parallel tool calls and streaming are runtime choices, not static needs, so
they are not enforced here.
"""

from __future__ import annotations

from dataclasses import dataclass

from wicklight.agentfile import AgentFile, PermissionLevel
from wicklight.agentfile.config import EffectiveConfig
from wicklight.contracts import (
    Capabilities,
    ProviderError,
    ProviderRegistry,
    classify_contract_version,
)
from wicklight.routing import allowed_sensitive_models, unreachable_routes

#: Rough characters-per-token ratio for the context-size estimate.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class PreflightIssue:
    """A problem found before running. ``fatal`` issues block the run."""

    message: str
    fatal: bool = True


def _enabled_tools(config: EffectiveConfig) -> list[str]:
    return [
        name
        for name, tool in config.tools.items()
        if tool.level.value is not PermissionLevel.OFF
    ]


def estimate_context_tokens(
    config: EffectiveConfig, agent_file: AgentFile | None
) -> int:
    """A rough upper-ish estimate of the agent's base context size, in tokens."""
    chars = len(agent_file.body) if agent_file is not None else 0
    chars += sum(len(name) for name in config.tools)
    return chars // _CHARS_PER_TOKEN


def _model_source(config: EffectiveConfig, agent_file: AgentFile | None) -> str:
    if agent_file is None:
        return "agent.md"
    line = agent_file.line_of("models", "default")
    filename = agent_file.path.name if agent_file.path else "agent.md"
    return f"{filename} line {line}" if line is not None else filename


def capability_issues(
    model_id: str,
    capabilities: Capabilities,
    *,
    enabled_tools: list[str],
    estimated_tokens: int,
    source: str,
) -> list[PreflightIssue]:
    """Compare an agent's static needs against a provider's declared capabilities."""
    issues: list[PreflightIssue] = []

    if enabled_tools and not capabilities.tool_calls:
        count = len(enabled_tools)
        plural = "s" if count != 1 else ""
        verb = "are" if count != 1 else "is"
        issues.append(
            PreflightIssue(
                f"{source}: {model_id} does not declare tool calling, but "
                f"{count} tool{plural} {verb} enabled. Use a model with tool "
                f"support or remove the tools."
            )
        )

    max_tokens = capabilities.max_context_tokens
    if max_tokens is not None and estimated_tokens > max_tokens:
        issues.append(
            PreflightIssue(
                f"{source}: {model_id} supports up to {max_tokens} context "
                f"tokens, but this agent needs about {estimated_tokens}. Shorten "
                f"the instructions or use a larger-context model."
            )
        )
    return issues


def run_capability_issues(
    config: EffectiveConfig,
    capabilities: Capabilities,
    agent_file: AgentFile | None = None,
) -> list[PreflightIssue]:
    """The capability comparison the loop runs at the start of a run."""
    return capability_issues(
        config.models.default.value,
        capabilities,
        enabled_tools=_enabled_tools(config),
        estimated_tokens=estimate_context_tokens(config, agent_file),
        source=_model_source(config, agent_file),
    )


def preflight(
    config: EffectiveConfig,
    agent_file: AgentFile | None = None,
    *,
    registry: ProviderRegistry | None = None,
) -> list[PreflightIssue]:
    """Full pre-run check: provider installed, contract supported, capabilities.

    Used by ``wicklight check``. Resolving the provider reads only its declared
    capabilities and contract version — no network call and no API key.
    """
    registry = registry if registry is not None else ProviderRegistry.discover()
    model_id = config.models.default.value
    source = _model_source(config, agent_file)

    try:
        provider, _ = registry.resolve(model_id)
    except ProviderError as exc:
        return [PreflightIssue(f"{source}: {exc}")]

    status, detail = classify_contract_version(provider.contract_version)
    if status == "unsupported":
        # Don't trust the capabilities of a plugin we can't support.
        return [PreflightIssue(f"{source}: provider for {model_id}: {detail}")]

    issues: list[PreflightIssue] = []
    if status == "deprecated":
        issues.append(PreflightIssue(f"{source}: {detail}", fatal=False))
    issues.extend(run_capability_issues(config, provider.capabilities, agent_file))
    return issues


def routing_issues(
    config: EffectiveConfig,
    *,
    registry: ProviderRegistry | None = None,
) -> list[PreflightIssue]:
    """Validate routing: every referenced model resolves, and flag dead routes."""
    registry = registry if registry is not None else ProviderRegistry.discover()
    models = config.models
    issues: list[PreflightIssue] = []

    # Every route target and fallback must resolve to an installed provider.
    # (The default is already checked by preflight's resolve.)
    referenced = [route.use for route in models.routes.value] + list(
        models.fallback.value
    )
    for model_id in referenced:
        try:
            registry.resolve(model_id)
        except ProviderError as exc:
            issues.append(PreflightIssue(f"routing: {model_id}: {exc}"))

    # Routes shadowed by an earlier, broader rule can never fire.
    whens = [route.when for route in models.routes.value]
    for index, shadowed_by in unreachable_routes(whens):
        issues.append(
            PreflightIssue(
                f"routing: route {index + 1} is unreachable — route "
                f"{shadowed_by + 1} is broader and always matches first",
                fatal=False,
            )
        )

    # If the agent can produce sensitive data but declares no model allowed for
    # it, any run that touches that data will stop (DTN-245). Warn up front.
    sensitive_tools = [
        name for name, tool in config.tools.items() if tool.sensitive.value
    ]
    route_pairs = [(route.when, route.use) for route in models.routes.value]
    if sensitive_tools and not allowed_sensitive_models(route_pairs):
        joined = ", ".join(sensitive_tools)
        issues.append(
            PreflightIssue(
                f"routing: {joined} can produce sensitive data, but no route "
                f"allows a model for sensitive data — such a run will stop. Add "
                f"a 'when: {{ data: sensitive }}' route.",
                fatal=False,
            )
        )
    return issues
