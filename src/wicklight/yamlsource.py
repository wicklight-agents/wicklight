"""Load YAML while preserving the source line of every key and list item.

Both the agent file (its frontmatter) and the deploy file need line-numbered
errors, so the ``ruamel.yaml`` round-trip load and the line index it carries live
here, shared by both parsers. ``load_with_lines`` returns the data as plain
``dict``/``list`` (callers never see ruamel types) plus a map from a key path to
its 1-indexed source line.
"""

from __future__ import annotations

from typing import Any, cast

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

# A path to a value: mapping keys (str) and list indices (int).
KeyPath = tuple[str | int, ...]


class YamlSourceError(Exception):
    """Raised when YAML cannot be parsed.

    ``line`` is the 1-indexed source line the error refers to, when known.
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


def load_with_lines(
    source: str, *, line_offset: int = 1
) -> tuple[object, dict[KeyPath, int]]:
    """Load ``source``, returning its ruamel node and a key-path → line map.

    ``line_offset`` is the 1-indexed source line of the first YAML line (``1`` for
    a whole file; the agent file passes ``2`` to skip its opening ``---``). The
    returned node keeps ruamel's line info; convert it with :func:`to_plain`.
    """
    raw = _load(source, line_offset=line_offset)
    lines: dict[KeyPath, int] = {}
    _build_line_index(raw, offset=line_offset, prefix=(), out=lines)
    return raw, lines


def to_plain(node: object) -> object:
    """Convert ruamel containers to plain ``dict``/``list``."""
    if isinstance(node, dict):
        return {
            str(k): to_plain(v) for k, v in cast("dict[object, object]", node).items()
        }
    if isinstance(node, list):
        return [to_plain(v) for v in cast("list[object]", node)]
    return node


def _load(source: str, *, line_offset: int) -> object:
    """Load YAML in round-trip mode (which retains line info), or raise."""
    yaml: Any = YAML()  # round-trip loader; nodes carry ``.lc`` line/column info
    try:
        return yaml.load(source)
    except YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = int(getattr(mark, "line", 0)) + line_offset if mark is not None else None
        # Raise the underlying message; callers add their own context prefix.
        raise YamlSourceError(str(exc), line=line) from exc


def _build_line_index(
    node: object, *, offset: int, prefix: KeyPath, out: dict[KeyPath, int]
) -> None:
    """Walk a ruamel node, recording the source line of every key and item."""
    lc_data = _lc_data(node)
    if isinstance(node, dict):
        for key, value in cast("dict[object, object]", node).items():
            token = _path_token(key)
            if lc_data is not None and key in lc_data:
                out[(*prefix, token)] = int(lc_data[key][0]) + offset
            _build_line_index(value, offset=offset, prefix=(*prefix, token), out=out)
    elif isinstance(node, list):
        for index, value in enumerate(cast("list[object]", node)):
            if lc_data is not None and index in lc_data:
                out[(*prefix, index)] = int(lc_data[index][0]) + offset
            _build_line_index(value, offset=offset, prefix=(*prefix, index), out=out)


def _lc_data(node: object) -> dict[Any, Any] | None:
    """Return a ruamel node's ``.lc.data`` line map, or ``None`` if absent."""
    lc = getattr(node, "lc", None)
    data = getattr(lc, "data", None) if lc is not None else None
    return cast("dict[Any, Any] | None", data)


def _path_token(key: object) -> str | int:
    return key if isinstance(key, (str, int)) else str(key)
