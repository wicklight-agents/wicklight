"""Parse an agent file into frontmatter and body, tracking source lines.

An agent file is YAML frontmatter delimited by ``---`` lines, followed by a
Markdown body:

    ---
    name: inbox-summarizer
    models:
      default: anthropic/claude-sonnet
    ---
    You summarize this week's emails and draft replies.

The frontmatter is parsed with ``ruamel.yaml`` so the source line of every key
(including nested keys and list items) is preserved. Later validation and trace
events use those lines to cite ``agent.md line N``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from wicklight.yamlsource import (
    KeyPath,
    YamlSourceError,
    load_with_lines,
    to_plain,
)

_DELIMITER = "---"


class AgentFileError(Exception):
    """Raised when an agent file cannot be parsed.

    ``line`` is the 1-indexed source line the error refers to, when known, so
    callers can render ``agent.md line N``.
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


@dataclass(frozen=True)
class AgentFile:
    """A parsed agent file: frontmatter rules, body instructions, source lines."""

    frontmatter: dict[str, Any]
    body: str
    path: Path | None = None
    _lines: MappingProxyType[KeyPath, int] = field(
        default_factory=lambda: MappingProxyType({}), repr=False
    )

    def line_of(self, *key_path: str | int) -> int | None:
        """Return the 1-indexed source line for a frontmatter key path.

        For example ``line_of("models", "default")`` or ``line_of("policies",
        0)``. Returns ``None`` if the path is not present in the frontmatter.
        """
        return self._lines.get(key_path)

    @classmethod
    def from_path(cls, path: str | Path) -> AgentFile:
        """Read and parse an agent file from disk."""
        path = Path(path)
        return parse_agent_file(path.read_text(encoding="utf-8"), path=path)


def parse_agent_file(text: str, *, path: Path | None = None) -> AgentFile:
    """Parse agent-file ``text`` into an :class:`AgentFile`.

    Raises :class:`AgentFileError` for missing or malformed frontmatter
    delimiters or invalid YAML.
    """
    yaml_source, body, line_offset = _split_frontmatter(text)
    try:
        raw, lines = load_with_lines(yaml_source, line_offset=line_offset)
    except YamlSourceError as exc:
        raise AgentFileError(
            f"invalid YAML in frontmatter: {exc}", line=exc.line
        ) from exc
    frontmatter = _frontmatter_mapping(raw, line_offset=line_offset)

    return AgentFile(
        frontmatter=frontmatter,
        body=body,
        path=path,
        _lines=MappingProxyType(lines),
    )


def _frontmatter_mapping(raw: object, *, line_offset: int) -> dict[str, Any]:
    """Return the frontmatter as a plain dict, or raise if it is not a mapping."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return cast("dict[str, Any]", to_plain(cast("dict[Any, Any]", raw)))
    raise AgentFileError(
        f"frontmatter must be a mapping of keys, got {type(raw).__name__}",
        line=line_offset,
    )


def _split_frontmatter(text: str) -> tuple[str, str, int]:
    """Split ``text`` into (yaml_source, body, line_offset).

    ``line_offset`` is the 1-indexed source line of the first YAML line, used to
    translate ruamel's 0-indexed lines into file lines.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        raise AgentFileError(
            "missing opening frontmatter delimiter: expected '---' on line 1",
            line=1,
        )

    closing: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIMITER:
            closing = i
            break
    if closing is None:
        raise AgentFileError("unterminated frontmatter: missing closing '---'")

    yaml_source = "".join(lines[1:closing])
    body = "".join(lines[closing + 1 :])
    # Opening delimiter is line 1, so the first YAML line is line 2.
    line_offset = 2
    return yaml_source, body, line_offset
