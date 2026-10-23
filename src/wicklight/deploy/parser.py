"""Parse a deploy file into data, tracking source lines for friendly errors.

Unlike the agent file, the deploy file is plain YAML (no frontmatter), so the
whole file is loaded with :func:`wicklight.yamlsource.load_with_lines` and every
key's source line is kept for ``deploy.yaml line N`` error messages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from wicklight.yamlsource import KeyPath, YamlSourceError, load_with_lines, to_plain


class DeployFileError(Exception):
    """Raised when a deploy file cannot be parsed.

    ``line`` is the 1-indexed source line the error refers to, when known.
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class DeployFile:
    """A parsed deploy file: its data and the source line of every key."""

    data: dict[str, Any]
    path: Path | None = None
    _lines: MappingProxyType[KeyPath, int] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )

    def line_of(self, *key_path: str | int) -> int | None:
        """Return the 1-indexed source line for a key path, or ``None``."""
        return self._lines.get(key_path)

    @classmethod
    def from_path(cls, path: str | Path) -> DeployFile:
        """Read and parse a deploy file from disk."""
        path = Path(path)
        return parse_deploy_file(path.read_text(encoding="utf-8"), path=path)


def parse_deploy_file(text: str, *, path: Path | None = None) -> DeployFile:
    """Parse deploy-file ``text`` into a :class:`DeployFile`."""
    try:
        raw, lines = load_with_lines(text, line_offset=1)
    except YamlSourceError as exc:
        raise DeployFileError(f"invalid YAML: {exc}", line=exc.line) from exc

    if raw is None:
        data: dict[str, Any] = {}
    elif isinstance(raw, dict):
        data = cast("dict[str, Any]", to_plain(cast("dict[Any, Any]", raw)))
    else:
        raise DeployFileError(
            f"deploy file must be a mapping of keys, got {type(raw).__name__}",
            line=1,
        )

    return DeployFile(data=data, path=path, _lines=MappingProxyType(lines))
