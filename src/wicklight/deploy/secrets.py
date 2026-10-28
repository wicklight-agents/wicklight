"""Resolve deploy-file secrets on the host, from env, a file, or the keychain.

Secret *values* live only here at runtime — never in the deploy file, never baked
into the image, never shown to the model, and (once registered with the trace
redactor) never written to a trace. Resolution happens on the host at start; the
values are then injected into the container as runtime environment. Every missing
secret is reported at once so a deployment fails fast at start, not mid-run.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from wicklight.deploy.schema import DeployConfig, SecretSource, SecretSpec


class MissingSecretsError(Exception):
    """Raised when one or more secrets cannot be resolved; names every one."""

    def __init__(self, names: list[str]) -> None:
        self.names = names
        super().__init__(
            "missing secret(s): " + ", ".join(names) + " — set them before starting"
        )


class SecretResolutionError(Exception):
    """Raised when a secret cannot be resolved for a reason other than absence."""


class _MissingSecretError(Exception):
    """Internal: a single secret was absent."""


def resolve_secrets(
    config: DeployConfig,
    *,
    base_dir: Path,
    env: Mapping[str, str],
) -> dict[str, str]:
    """Resolve every secret in ``config``; raise listing all that are missing."""
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for key, spec in config.secrets.items():
        try:
            resolved[key] = _resolve_one(key, spec, base_dir=base_dir, env=env)
        except _MissingSecretError:
            missing.append(key)
    if missing:
        raise MissingSecretsError(missing)
    return resolved


def _resolve_one(
    key: str, spec: SecretSpec, *, base_dir: Path, env: Mapping[str, str]
) -> str:
    if spec.source is SecretSource.ENV:
        value = env.get(spec.name or key)
        if value is None:
            raise _MissingSecretError
        return value

    if spec.source is SecretSource.FILE:
        raw = Path(spec.path or "")
        resolved = raw if raw.is_absolute() else base_dir / raw
        if not resolved.is_file():
            raise _MissingSecretError
        # Secret files commonly end in a newline; drop a trailing one.
        return resolved.read_text(encoding="utf-8").rstrip("\n")

    # keychain
    item = spec.name or key
    try:
        import keyring  # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise SecretResolutionError(
            f"secret {key!r} uses the keychain, which needs the 'keyring' package"
        ) from exc
    # keyring ships no type stubs; the API returns the password or None.
    value = cast("str | None", cast("Any", keyring).get_password("wicklight", item))
    if value is None:
        raise _MissingSecretError
    return value


def secrets_for_tool(secrets: Mapping[str, str], required: list[str]) -> dict[str, str]:
    """The subset of ``secrets`` a tool declared it needs (``required_secrets``)."""
    return {name: secrets[name] for name in required if name in secrets}
