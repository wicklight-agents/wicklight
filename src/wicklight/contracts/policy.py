"""The Policy contract: pure allow/deny decisions over proposed tool calls.

A policy inspects a tool call the model has proposed and returns :class:`Allow`
or :class:`Deny` with a reason. Policies are *pure decisions*: they cannot
execute tools, mutate the call's arguments, or disable other checks. Every
policy declares a name and a typed config schema (a Pydantic model) and is
configured by name in the agent file's ``policies:`` list.

Policies register through the ``wicklight.policies`` entry point. The harness
discovers them as factories (the policy class), validates the agent-file config
against the policy's ``config_model``, and constructs the policy with it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict

from wicklight.contracts.tool import ToolRisk

#: The entry-point group plugins register policies under.
POLICY_ENTRY_POINT_GROUP = "wicklight.policies"


class PolicyError(Exception):
    """Raised for policy definition, loading, lookup, or config problems."""


class EmptyConfig(BaseModel):
    """The config schema for a policy that takes no configuration."""

    model_config = ConfigDict(extra="forbid")


def _empty_arguments() -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class PolicyCall:
    """A proposed tool call, as a policy sees it — read-only.

    The policy may inspect ``tool``, ``arguments``, and ``risk`` but must not
    mutate them. ``arguments`` is typed as a read-only mapping to signal this;
    the conformance kit also verifies a policy leaves them untouched.
    """

    tool: str
    arguments: Mapping[str, Any] = field(default_factory=_empty_arguments)
    risk: ToolRisk | None = None


@dataclass(frozen=True)
class PolicyContext:
    """Read-only run context a policy may consult, never shown to the model."""

    run_id: str | None = None
    #: Dollars spent so far this run, for spend-limit style policies.
    spent_usd: float = 0.0
    #: The directory the agent file lives in, for path-allowlist style policies.
    agent_dir: Path | None = None


@dataclass(frozen=True)
class Allow:
    """The policy permits the call."""


@dataclass(frozen=True)
class Deny:
    """The policy blocks the call, always with a human-readable reason."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason or not self.reason.strip():
            raise PolicyError("a Deny decision must carry a non-empty reason")


#: A policy's verdict on a proposed call.
PolicyDecision = Allow | Deny

#: A shared, immutable allow decision — policies may return this directly.
ALLOW = Allow()


def deny(reason: str) -> Deny:
    """Build a :class:`Deny` with a reason (reads better than ``Deny(...)``)."""
    return Deny(reason)


@runtime_checkable
class Policy(Protocol):
    """A pure allow/deny decision over a proposed tool call.

    ``name`` and ``config_model`` are read-only declarations so implementations
    may provide them as class attributes, ClassVars, or instance attributes.
    ``check`` is synchronous and side-effect free: given a call and context it
    returns a decision and nothing else.
    """

    @property
    def name(self) -> str: ...

    @property
    def config_model(self) -> type[BaseModel]: ...

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision: ...


@runtime_checkable
class PolicyFactory(Protocol):
    """A policy *class*: carries the name and config schema, builds a policy.

    A policy class with ``name`` and ``config_model`` class attributes and an
    ``__init__`` taking its validated config satisfies this structurally.
    """

    name: str
    config_model: type[BaseModel]

    def __call__(self, config: Any) -> Policy: ...


class PolicyRegistry:
    """The policies discovered in this environment, keyed by policy name."""

    def __init__(self, factories: dict[str, PolicyFactory]) -> None:
        self._factories = factories

    @classmethod
    def discover(
        cls, entry_points_: Iterable[EntryPoint] | None = None
    ) -> PolicyRegistry:
        """Discover policies from the ``wicklight.policies`` entry-point group."""
        eps = (
            entry_points(group=POLICY_ENTRY_POINT_GROUP)
            if entry_points_ is None
            else entry_points_
        )
        factories: dict[str, PolicyFactory] = {}
        for ep in eps:
            factory = _load_policy(ep)
            factories[factory.name] = factory
        return cls(factories)

    def names(self) -> list[str]:
        return sorted(self._factories)

    def get(self, name: str) -> PolicyFactory:
        factory = self._factories.get(name)
        if factory is None:
            available = ", ".join(self.names()) or "none"
            raise PolicyError(f"unknown policy {name!r}; available: {available}")
        return factory

    def create(self, name: str, config: Any = None) -> Policy:
        """Build a configured policy by name, validating its config first.

        ``config`` is the raw agent-file value for the policy — usually a
        mapping, but a policy may accept a list or scalar via its config model
        (e.g. ``email_only_to: ["@acme.com"]``). ``None`` means no config.
        """
        factory = self.get(name)
        data: Any = {} if config is None else config
        try:
            validated = factory.config_model.model_validate(data)
        except Exception as exc:
            raise PolicyError(f"invalid config for policy {name!r}: {exc}") from exc
        return factory(validated)


def _load_policy(ep: EntryPoint) -> PolicyFactory:
    obj = ep.load()
    if not isinstance(obj, type):
        raise PolicyError(
            f"policy entry point {ep.name!r} must load a policy class, "
            f"got {type(obj).__name__}"
        )
    return cast("PolicyFactory", obj)
