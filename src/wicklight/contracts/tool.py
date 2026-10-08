"""The Tool contract: typed actions with a declared risk level.

A tool is a named action the model can request. It declares a typed input
schema (a Pydantic model), a risk level (read, write, irreversible), the network
hosts it needs, and whether its output is sensitive. ``run`` receives the
validated input and a :class:`ToolContext` that carries injected secrets the
model never sees; it returns a :class:`ToolResult` — errors are returned as
results, not raised.

Tools register through the ``wicklight.tools`` entry point, or are written as
simple async functions with the :func:`tool` decorator.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from importlib.metadata import EntryPoint, entry_points
from typing import Any, Protocol, get_type_hints, runtime_checkable

from pydantic import BaseModel, ConfigDict

#: The entry-point group plugins register tools under.
TOOL_ENTRY_POINT_GROUP = "wicklight.tools"


class ToolError(Exception):
    """Raised for tool definition, loading, or lookup problems."""


class ToolRisk(str, Enum):
    """How dangerous a tool is, from least to most."""

    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


def _empty_secrets() -> dict[str, str]:
    return {}


@dataclass
class ToolContext:
    """Runtime context passed to a tool, never shown to the model."""

    secrets: Mapping[str, str] = field(default_factory=_empty_secrets)
    run_id: str | None = None

    def secret(self, name: str) -> str:
        """Return an injected secret by name, or raise if it is not available."""
        try:
            return self.secrets[name]
        except KeyError as exc:
            raise ToolError(f"secret {name!r} is not available") from exc


class ToolResult(BaseModel):
    """The structured outcome of a tool call."""

    model_config = ConfigDict(extra="forbid")

    ok: bool
    output: str = ""
    error: str | None = None
    sensitive: bool = False

    @classmethod
    def success(cls, output: str = "", *, sensitive: bool = False) -> ToolResult:
        return cls(ok=True, output=output, sensitive=sensitive)

    @classmethod
    def failure(cls, error: str, *, sensitive: bool = False) -> ToolResult:
        return cls(ok=False, error=error, sensitive=sensitive)


@runtime_checkable
class Tool(Protocol):
    """A named action with a typed input schema and a declared risk level."""

    name: str
    description: str
    risk: ToolRisk
    network_hosts: list[str]
    input_model: type[BaseModel]

    def is_sensitive(self, tool_input: BaseModel) -> bool: ...

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult: ...


Sensitivity = bool | Callable[[BaseModel], bool]
ToolFunction = Callable[[Any, ToolContext], Awaitable[ToolResult | str]]


class FunctionTool:
    """A :class:`Tool` built from an async function by :func:`tool`."""

    def __init__(
        self,
        fn: ToolFunction,
        *,
        name: str,
        description: str,
        risk: ToolRisk,
        network_hosts: Iterable[str],
        sensitive: Sensitivity,
        input_model: type[BaseModel],
    ) -> None:
        self._fn = fn
        self.name = name
        self.description = description
        self.risk = risk
        self.network_hosts = list(network_hosts)
        self._sensitive = sensitive
        self.input_model = input_model

    def is_sensitive(self, tool_input: BaseModel) -> bool:
        sensitive = self._sensitive
        return sensitive(tool_input) if callable(sensitive) else bool(sensitive)

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        result = await self._fn(tool_input, ctx)
        sensitive = self.is_sensitive(tool_input)
        if isinstance(result, ToolResult):
            return result.model_copy(update={"sensitive": sensitive})
        return ToolResult(ok=True, output=result, sensitive=sensitive)


def tool(
    *,
    risk: ToolRisk | str,
    network_hosts: Iterable[str],
    sensitive: Sensitivity,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[ToolFunction], FunctionTool]:
    """Turn an async function into a :class:`Tool`.

    ``risk``, ``network_hosts``, and ``sensitive`` are required declarations so
    the author makes a conscious choice (``[]`` and ``False`` are valid). The
    input schema is inferred from the first parameter's Pydantic annotation.
    """

    def decorator(fn: ToolFunction) -> FunctionTool:
        if not inspect.iscoroutinefunction(fn):
            raise ToolError(f"tool {fn.__name__!r} must be an async function")
        return FunctionTool(
            fn,
            name=name or fn.__name__,
            description=description or (fn.__doc__ or "").strip(),
            risk=_coerce_risk(risk),
            network_hosts=network_hosts,
            sensitive=sensitive,
            input_model=_infer_input_model(fn),
        )

    return decorator


def _coerce_risk(risk: ToolRisk | str) -> ToolRisk:
    try:
        return ToolRisk(risk)
    except ValueError as exc:
        valid = ", ".join(member.value for member in ToolRisk)
        raise ToolError(f"invalid risk {risk!r}; use one of: {valid}") from exc


def _infer_input_model(fn: ToolFunction) -> type[BaseModel]:
    parameters = list(inspect.signature(fn).parameters)
    if not parameters:
        raise ToolError(f"tool {fn.__name__!r} must take an input argument")
    first = parameters[0]
    annotation = get_type_hints(fn).get(first)
    if not (isinstance(annotation, type) and issubclass(annotation, BaseModel)):
        raise ToolError(
            f"tool {fn.__name__!r} first argument must be annotated with a "
            f"Pydantic model"
        )
    return annotation


class ToolRegistry:
    """The tools discovered in this environment, keyed by tool name."""

    def __init__(self, tools: dict[str, Tool]) -> None:
        self._tools = tools

    @classmethod
    def discover(
        cls, entry_points_: Iterable[EntryPoint] | None = None
    ) -> ToolRegistry:
        """Discover tools from the ``wicklight.tools`` entry-point group."""
        eps = (
            entry_points(group=TOOL_ENTRY_POINT_GROUP)
            if entry_points_ is None
            else entry_points_
        )
        tools: dict[str, Tool] = {}
        for ep in eps:
            loaded = _load_tool(ep)
            tools[loaded.name] = loaded
        return cls(tools)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool:
        loaded = self._tools.get(name)
        if loaded is None:
            available = ", ".join(self.names()) or "none"
            raise ToolError(f"unknown tool {name!r}; available: {available}")
        return loaded


def _load_tool(ep: EntryPoint) -> Tool:
    obj = ep.load()
    # A plugin may register a Tool instance or a no-arg Tool class.
    return obj() if isinstance(obj, type) else obj
