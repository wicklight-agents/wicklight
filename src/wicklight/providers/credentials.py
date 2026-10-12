"""API-key handling for real provider adapters (DTN-227).

Credentials live only in the environment, never in the agent file: an agent
file names a model like ``anthropic/claude-sonnet``, and the provider prefix
maps to a well-known environment variable. This module resolves those keys for
adapters, reports which keys a config needs (without printing them) for
``wicklight check``, and builds the trace redactor that keeps any key — even one
echoed back inside a provider error — out of the JSONL and blobs.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from wicklight.contracts import ProviderError
from wicklight.redaction import build_secret_redactor

#: Provider prefix (the part before ``/`` in a model id) → the environment
#: variable its API key is read from. Providers without a key (e.g. ``fake``,
#: or a local OpenAI-compatible server) are simply absent.
KEY_ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def provider_of(model_id: str) -> str:
    """The provider prefix of a model id (``anthropic/claude`` → ``anthropic``)."""
    return model_id.split("/", 1)[0]


@dataclass(frozen=True)
class KeyRequirement:
    """A key a config needs, and whether it is set — never its value."""

    provider: str
    env_var: str
    is_set: bool


def required_keys(model_ids: Iterable[str]) -> list[KeyRequirement]:
    """Which API keys the given models need, and whether each is set.

    Deduplicated by environment variable and sorted, so the report is stable.
    """
    seen: dict[str, KeyRequirement] = {}
    for model_id in model_ids:
        provider = provider_of(model_id)
        env_var = KEY_ENV_VARS.get(provider)
        if env_var is None or env_var in seen:
            continue
        seen[env_var] = KeyRequirement(
            provider=provider, env_var=env_var, is_set=bool(os.environ.get(env_var))
        )
    return [seen[key] for key in sorted(seen)]


def resolve_key(provider: str) -> str:
    """Return the API key for a provider from the environment, or raise.

    Adapters call this; the error names the variable to set but never leaks a
    value.
    """
    env_var = KEY_ENV_VARS.get(provider)
    if env_var is None:
        raise ProviderError(f"provider {provider!r} has no known API-key variable")
    value = os.environ.get(env_var)
    if not value:
        raise ProviderError(
            f"missing API key for {provider!r}: set the {env_var} environment variable"
        )
    return value


def trace_redactor() -> Callable[[str], str]:
    """A redactor for the trace writer: strips every set API key value and any
    key-shaped string, so a credential can never be written to a trace.
    """
    live_values = [
        value for env_var in KEY_ENV_VARS.values() if (value := os.environ.get(env_var))
    ]
    return build_secret_redactor(live_values)
