"""The Provider contract: a Protocol, capabilities, and entry-point discovery.

A provider plugin translates between the harness's neutral model types and one
model API. It declares the contract version it targets and its capabilities,
both checked at load time. Plugins register through the ``wicklight.providers``
entry point, so ``pip install`` is enough to make a provider available; agent
files then refer to models as ``provider/model`` (e.g. ``anthropic/claude-sonnet``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from wicklight.contracts.models import ModelEvent, ModelRequest, ModelResponse
from wicklight.contracts.version import CONTRACT_VERSION

#: The entry-point group plugins register providers under.
PROVIDER_ENTRY_POINT_GROUP = "wicklight.providers"


class ProviderError(Exception):
    """Raised when a provider cannot be loaded, version-checked, or resolved."""


class Capabilities(BaseModel):
    """What a provider supports, checked against an agent's needs at load time."""

    model_config = ConfigDict(extra="forbid")

    parallel_tool_calls: bool = False
    max_context_tokens: int | None = None
    streaming: bool = False
    structured_output: bool = False


@runtime_checkable
class Provider(Protocol):
    """A model provider: neutral in, neutral out."""

    contract_version: str
    capabilities: Capabilities

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Make a single, non-streaming model call."""
        ...

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        """Make a streaming model call, yielding events as they arrive."""
        ...


def classify_contract_version(version: str) -> tuple[str, str]:
    """Classify a contract version as ``ok``, ``deprecated``, or ``unsupported``.

    The current major is ``ok``; the one before it is ``deprecated`` (still
    supported for six months after a new major ships); anything else is
    ``unsupported``. Returns the status and a human-readable detail (empty when
    ``ok``).
    """
    try:
        plugin_major = int(version.split(".", 1)[0])
    except ValueError:
        return "unsupported", f"invalid contract version {version!r}"

    current_major = int(CONTRACT_VERSION.split(".", 1)[0])
    if plugin_major > current_major:
        return (
            "unsupported",
            f"plugin targets contract v{version}, newer than this harness's "
            f"v{CONTRACT_VERSION}; upgrade wicklight",
        )
    if current_major - plugin_major == 0:
        return "ok", ""
    if current_major - plugin_major == 1:
        return (
            "deprecated",
            f"plugin targets the previous major v{version}; upgrade before "
            f"support ends (six months after a new major ships)",
        )
    return (
        "unsupported",
        f"plugin targets contract v{version}, which is no longer supported "
        f"(harness is v{CONTRACT_VERSION})",
    )


def check_contract_version(version: str) -> None:
    """Validate a plugin's contract version against the harness, or raise.

    The current major and the one before it are supported (the previous major
    for six months after a new one ships).
    """
    status, detail = classify_contract_version(version)
    if status == "unsupported":
        raise ProviderError(detail)


class ProviderRegistry:
    """The providers discovered in this environment, keyed by name."""

    def __init__(self, providers: dict[str, Provider]) -> None:
        self._providers = providers

    @classmethod
    def discover(
        cls, entry_points_: Iterable[EntryPoint] | None = None
    ) -> ProviderRegistry:
        """Discover providers from the ``wicklight.providers`` entry point group.

        Each provider is loaded and its contract version checked; a bad version
        fails loudly rather than being silently skipped.
        """
        eps = (
            entry_points(group=PROVIDER_ENTRY_POINT_GROUP)
            if entry_points_ is None
            else entry_points_
        )
        providers: dict[str, Provider] = {}
        for ep in eps:
            provider = _load_provider(ep)
            check_contract_version(provider.contract_version)
            providers[ep.name] = provider
        return cls(providers)

    def names(self) -> list[str]:
        return sorted(self._providers)

    def get(self, name: str) -> Provider:
        provider = self._providers.get(name)
        if provider is None:
            available = ", ".join(self.names()) or "none"
            raise ProviderError(f"unknown provider {name!r}; available: {available}")
        return provider

    def resolve(self, model_id: str) -> tuple[Provider, str]:
        """Resolve a ``provider/model`` id to its provider and model name."""
        provider_name, slash, model = model_id.partition("/")
        if not slash or not provider_name or not model:
            raise ProviderError(f"model id must be 'provider/model', got {model_id!r}")
        return self.get(provider_name), model


def _load_provider(ep: EntryPoint) -> Provider:
    obj = ep.load()
    # A plugin may register a Provider instance or a no-arg Provider class.
    return obj() if isinstance(obj, type) else obj


@dataclass(frozen=True)
class ProviderInfo:
    """A description of one registered provider, for listing to a user."""

    name: str
    package: str | None
    package_version: str | None
    contract_version: str | None
    capabilities: Capabilities | None
    status: str  # "ok" | "deprecated" | "unsupported" | "error"
    detail: str = ""


def describe_providers(
    entry_points_: Iterable[EntryPoint] | None = None,
) -> list[ProviderInfo]:
    """Describe every registered provider, tolerating ones that fail to load.

    Unlike :meth:`ProviderRegistry.discover`, this never raises on a bad plugin:
    load failures and unsupported versions are reported as a status so the whole
    listing can be shown.
    """
    eps = (
        entry_points(group=PROVIDER_ENTRY_POINT_GROUP)
        if entry_points_ is None
        else entry_points_
    )
    infos: list[ProviderInfo] = []
    for ep in eps:
        package, package_version = _distribution_of(ep)
        try:
            provider = _load_provider(ep)
        except Exception as exc:  # noqa: BLE001 - surfaced in the listing, not swallowed
            infos.append(
                ProviderInfo(
                    name=ep.name,
                    package=package,
                    package_version=package_version,
                    contract_version=None,
                    capabilities=None,
                    status="error",
                    detail=str(exc),
                )
            )
            continue
        status, detail = classify_contract_version(provider.contract_version)
        infos.append(
            ProviderInfo(
                name=ep.name,
                package=package,
                package_version=package_version,
                contract_version=provider.contract_version,
                capabilities=provider.capabilities,
                status=status,
                detail=detail,
            )
        )
    return sorted(infos, key=lambda info: info.name)


def _distribution_of(ep: EntryPoint) -> tuple[str | None, str | None]:
    dist = getattr(ep, "dist", None)
    if dist is None:
        return None, None
    return getattr(dist, "name", None), getattr(dist, "version", None)
