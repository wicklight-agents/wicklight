"""Path allowlist: file tools may only touch paths under approved directories.

Applies to any tool call carrying a path argument (``path``, ``paths``,
``file``, or ``filename``). Both the configured roots and each candidate path
are fully resolved first — ``..`` segments and symlinks included — so traversal
tricks like ``./docs/../../etc/passwd`` cannot escape. Relative paths resolve
against the agent file's directory when known, else the current directory.

    policies:
      - paths_within: ["./docs", "./data"]
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, ClassVar, cast

from pydantic import BaseModel, ConfigDict, model_validator

from wicklight.contracts.policy import (
    ALLOW,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    deny,
)

_DEFAULT_PATH_ARGS = ("path", "paths", "file", "filename")


class PathsWithinConfig(BaseModel):
    """Allowed root directories, and which arguments carry a path."""

    model_config = ConfigDict(extra="forbid")

    roots: list[str] = []
    path_args: list[str] = list(_DEFAULT_PATH_ARGS)

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, data: Any) -> Any:
        # Agent-file shorthand: `paths_within: ["./docs"]` -> {"roots": [...]}.
        if isinstance(data, list):
            return {"roots": cast("list[Any]", data)}
        return data


class PathsWithin:
    """Deny file access to paths outside the configured directories."""

    name: ClassVar[str] = "paths_within"
    config_model: ClassVar[type[BaseModel]] = PathsWithinConfig

    def __init__(self, config: PathsWithinConfig) -> None:
        self._roots = config.roots
        self._path_args = config.path_args

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        paths = list(self._paths(call.arguments))
        if not paths:
            return ALLOW  # no path argument: not applicable
        base = ctx.agent_dir or Path.cwd()
        roots = [self._resolve(base, root) for root in self._roots]
        for path in paths:
            resolved = self._resolve(base, path)
            if not any(_is_within(resolved, root) for root in roots):
                allowed = ", ".join(self._roots) or "(none)"
                return deny(
                    f"{call.tool} path {path!r} is outside the allowed "
                    f"directories: {allowed}"
                )
        return ALLOW

    def _paths(self, arguments: Mapping[str, Any]) -> Iterable[str]:
        for key in self._path_args:
            value = arguments.get(key)
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in cast("list[Any]", value):
                    if isinstance(item, str):
                        yield item

    @staticmethod
    def _resolve(base: Path, path: str) -> Path:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = base / candidate
        # realpath resolves symlinks and `..` even for paths that don't exist.
        return Path(os.path.realpath(candidate))


def _is_within(child: Path, root: Path) -> bool:
    try:
        child.relative_to(root)
    except ValueError:
        return False
    return True
