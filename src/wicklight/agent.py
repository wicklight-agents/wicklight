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
from wicklight.contracts import Provider, ProviderRegistry, Tool, ToolRegistry
from wicklight.core import RunResult, ToolCheck, run_agent
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
            path.read_text(encoding="utf-8"), filename=path.name
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
        tools: Mapping[str, Tool] | None = None,
        world: MockWorld | None = None,
        approver: object | None = None,
        checks: Sequence[ToolCheck] = (),
        on_event: Callable[[TraceEvent], None] | None = None,
        run_id: str | None = None,
        runs_dir: str | Path = "runs",
    ) -> RunResult:
        """Run the agent on ``task``, writing a trace and returning the result."""
        run_id = run_id or f"run_{uuid4().hex[:12]}"
        model_provider = self._resolve_provider(provider)
        tool_map = self._resolve_tools(tools, world)
        # `approver` is accepted now for API stability; the approval gate that
        # uses it lands in M7.
        with TraceWriter(run_id, root=runs_dir) as writer:
            return await run_agent(
                run_id=run_id,
                instructions=self._agent_file.body,
                task=task,
                config=self._config,
                provider=model_provider,
                tools=tool_map,
                writer=writer,
                checks=checks,
                agent_file=self._agent_file,
                on_event=on_event,
            )

    def run(
        self,
        task: str,
        *,
        provider: Provider | None = None,
        tools: Mapping[str, Tool] | None = None,
        world: MockWorld | None = None,
        approver: object | None = None,
        checks: Sequence[ToolCheck] = (),
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
                    tools=tools,
                    world=world,
                    approver=approver,
                    checks=checks,
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

    def _resolve_provider(self, provider: Provider | None) -> Provider:
        if provider is not None:
            return provider
        model_id = self._config.models.default.value
        resolved, _ = ProviderRegistry.discover().resolve(model_id)
        return resolved

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
