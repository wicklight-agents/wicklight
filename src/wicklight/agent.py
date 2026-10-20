"""The public Python API: load an agent file and run it.

    from wicklight import Agent

    agent = Agent.load("agent.md")
    result = agent.run("Summarize my inbox")          # sync
    result = await agent.arun("Summarize my inbox")   # async

``run`` is a thin wrapper over ``arun`` that also works where an event loop is
already running (e.g. a Jupyter notebook). Test overrides let a caller supply a
provider, tools, a seeded world, or an approver without an agent-file change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from wicklight.agentfile import AgentFile, build_effective_config, parse_and_validate
from wicklight.agentfile.config import EffectiveConfig
from wicklight.contracts import (
    PolicyError,
    PolicyRegistry,
    Provider,
    ProviderError,
    ProviderRegistry,
    Tool,
    ToolRegistry,
)
from wicklight.core import (
    Approver,
    ConfiguredPolicy,
    RunResult,
    ToolCheck,
    run_agent,
)
from wicklight.providers.credentials import trace_redactor
from wicklight.tools import MockWorld, mock_tools
from wicklight.trace import TraceEvent, TraceWriter

__all__ = ["Agent", "RunResult"]


class Agent:
    """A loaded, validated agent file ready to run."""

    def __init__(self, agent_file: AgentFile, config: EffectiveConfig) -> None:
        self._agent_file = agent_file
        self._config = config

    @classmethod
    def load(cls, path: str | Path) -> Agent:
        """Load and validate an agent file, raising on any validation error."""
        path = Path(path)
        agent_file, agent_config = parse_and_validate(
            path.read_text(encoding="utf-8"), path=path
        )
        config = build_effective_config(agent_config, provided=agent_file.frontmatter)
        return cls(agent_file, config)

    @property
    def name(self) -> str:
        return self._config.name.value

    async def arun(
        self,
        task: str,
        *,
        provider: Provider | None = None,
        providers: Mapping[str, Provider] | None = None,
        tools: Mapping[str, Tool] | None = None,
        world: MockWorld | None = None,
        approver: Approver | None = None,
        checks: Sequence[ToolCheck] = (),
        policies: Sequence[ConfiguredPolicy] | None = None,
        dry_run: bool = False,
        on_event: Callable[[TraceEvent], None] | None = None,
        run_id: str | None = None,
        runs_dir: str | Path = "runs",
    ) -> RunResult:
        """Run the agent on ``task``, writing a trace and returning the result.

        With ``dry_run=True`` tools are stubbed: calls that pass every check are
        recorded as "would have run" but never executed (DTN-240). For a routed
        agent, ``providers`` maps each routed model id to its provider.
        """
        run_id = run_id or f"run_{uuid4().hex[:12]}"
        provider_map, default_provider = self._resolve_providers(provider, providers)
        tool_map = self._resolve_tools(tools, world)
        configured_policies = self._resolve_policies(policies)
        with TraceWriter(run_id, root=runs_dir, redactor=trace_redactor()) as writer:
            return await run_agent(
                run_id=run_id,
                instructions=self._agent_file.body,
                task=task,
                config=self._config,
                provider=default_provider,
                providers=provider_map,
                tools=tool_map,
                writer=writer,
                checks=checks,
                policies=configured_policies,
                approver=approver,
                dry_run=dry_run,
                agent_file=self._agent_file,
                on_event=on_event,
            )

    def run(
        self,
        task: str,
        *,
        provider: Provider | None = None,
        providers: Mapping[str, Provider] | None = None,
        tools: Mapping[str, Tool] | None = None,
        world: MockWorld | None = None,
        approver: Approver | None = None,
        checks: Sequence[ToolCheck] = (),
        policies: Sequence[ConfiguredPolicy] | None = None,
        dry_run: bool = False,
        on_event: Callable[[TraceEvent], None] | None = None,
        run_id: str | None = None,
        runs_dir: str | Path = "runs",
    ) -> RunResult:
        """Synchronous wrapper over :meth:`arun`.

        Works both in a plain script and where an event loop is already running
        (a notebook): in that case the run executes in a worker thread so it
        never fights the running loop.
        """

        def _call() -> RunResult:
            return asyncio.run(
                self.arun(
                    task,
                    provider=provider,
                    providers=providers,
                    tools=tools,
                    world=world,
                    approver=approver,
                    checks=checks,
                    policies=policies,
                    dry_run=dry_run,
                    on_event=on_event,
                    run_id=run_id,
                    runs_dir=runs_dir,
                )
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return _call()  # no loop running: safe to drive one here
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_call).result()

    def _resolve_providers(
        self,
        provider: Provider | None,
        providers: Mapping[str, Provider] | None,
    ) -> tuple[dict[str, Provider], Provider]:
        """Build the model→provider map and the default provider.

        Covers the default model plus every routed and fallback model. Injected
        ``providers`` win; an injected single ``provider`` stands in for the
        default; anything else is resolved from the installed plugins.
        """
        models = self._config.models
        default_model = models.default.value
        resolved: dict[str, Provider] = dict(providers or {})

        referenced = [default_model]
        referenced += [route.use for route in models.routes.value]
        referenced += list(models.fallback.value)

        registry: ProviderRegistry | None = None
        for model_id in referenced:
            if model_id in resolved:
                continue
            if provider is not None and model_id == default_model:
                resolved[model_id] = provider
                continue
            registry = registry or ProviderRegistry.discover()
            try:
                resolved[model_id], _ = registry.resolve(model_id)
            except ProviderError:
                # A route/fallback target that isn't installed is left out: the
                # loop raises a routing error only if that model is actually
                # chosen (an unused route shouldn't abort the run). The default
                # must resolve, so let its failure propagate.
                if model_id == default_model:
                    raise
        return resolved, resolved[default_model]

    def _resolve_tools(
        self, tools: Mapping[str, Tool] | None, world: MockWorld | None
    ) -> Mapping[str, Tool]:
        if tools is not None:
            return dict(tools)
        if world is not None:
            return mock_tools(world)
        # Otherwise offer the installed tools the agent file lists by name.
        registry = ToolRegistry.discover()
        available = set(registry.names())
        return {
            name: registry.get(name) for name in self._config.tools if name in available
        }

    def _resolve_policies(
        self, override: Sequence[ConfiguredPolicy] | None
    ) -> list[ConfiguredPolicy]:
        """Build the configured policies for this run, in agent-file order.

        A caller may inject policies directly (for tests); otherwise they are
        discovered and configured from the agent file's ``policies:`` list.
        """
        if override is not None:
            return list(override)

        entries = self._config.policies.value
        if not entries:
            return []

        registry = PolicyRegistry.discover()
        filename = self._agent_file.path.name if self._agent_file.path else "agent.md"
        configured: list[ConfiguredPolicy] = []
        for index, entry in enumerate(entries):
            if len(entry) != 1:
                raise PolicyError(
                    "each policies entry must be a single '<name>: <config>' "
                    f"mapping, got {entry!r}"
                )
            name = next(iter(entry))
            policy = registry.create(name, entry[name])
            line = self._agent_file.line_of("policies", index)
            source = f"{filename} line {line}" if line is not None else None
            configured.append(ConfiguredPolicy(name=name, policy=policy, source=source))
        return configured
