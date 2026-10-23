"""Human-friendly, line-numbered validation errors shared by config files.

Pydantic and YAML errors are precise but unfriendly. This turns a
``ValidationError`` into messages a beginner can act on — citing the source
line, naming the location, explaining the fix, and suggesting a correction for a
misspelled key — and reports every problem in one pass. The agent file and the
deploy file both use it so their errors read the same way:

    deploy.yaml line 4: 'agent' is required.
    agent.md line 9: tools.send_email.level: "writ" is not a valid level. …
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic_core import ErrorDetails

# A path to a value: mapping keys (str) and list indices (int).
KeyPath = tuple[str | int, ...]

# A callable that maps a key path to its 1-indexed source line, or None.
LineOf = Callable[[KeyPath], int | None]


@dataclass(frozen=True)
class ConfigIssue:
    """One problem found in a config file, formatted for a human."""

    message: str
    line: int | None
    location: str


def format_issues(
    errors: list[ErrorDetails],
    *,
    root_model: type[BaseModel],
    line_of: LineOf,
    filename: str,
    enum_fields: Mapping[str, type[Enum]] = {},
    field_nouns: Mapping[str, str] = {},
) -> list[ConfigIssue]:
    """Turn a model's validation ``errors`` into friendly, line-numbered issues.

    ``root_model`` is the top-level model (used to suggest a corrected key).
    ``line_of`` maps a key path to a source line. ``enum_fields`` names the
    fields whose values are enums, so the message can list the valid options,
    and ``field_nouns`` renames a field in the message ("not a valid <noun>").
    """
    issues = [
        _issue(
            error,
            root_model=root_model,
            line_of=line_of,
            filename=filename,
            enum_fields=enum_fields,
            field_nouns=field_nouns,
        )
        for error in errors
    ]
    # Stable order: by line (errors without a line last), then by location.
    issues.sort(key=lambda i: (i.line is None, i.line or 0, i.location))
    return issues


def _issue(
    error: ErrorDetails,
    *,
    root_model: type[BaseModel],
    line_of: LineOf,
    filename: str,
    enum_fields: Mapping[str, type[Enum]],
    field_nouns: Mapping[str, str],
) -> ConfigIssue:
    loc = tuple(error["loc"])
    error_type = str(error["type"])

    # Unexpected and missing keys read better when the message names the
    # container and the detail names the key.
    if error_type in ("extra_forbidden", "missing"):
        location = _dotted(loc[:-1])
    else:
        location = _dotted(loc)
    line = line_of(loc)

    detail = _detail(
        error_type,
        loc,
        error,
        root_model=root_model,
        enum_fields=enum_fields,
        field_nouns=field_nouns,
    )
    return ConfigIssue(
        message=format_message(filename, line, location, detail),
        line=line,
        location=location,
    )


def _detail(
    error_type: str,
    loc: KeyPath,
    error: ErrorDetails,
    *,
    root_model: type[BaseModel],
    enum_fields: Mapping[str, type[Enum]],
    field_nouns: Mapping[str, str],
) -> str:
    given = error.get("input")
    field = loc[-1] if loc else ""

    if error_type == "extra_forbidden":
        key = str(field)
        suggestion = _suggest(key, _valid_keys_at(root_model, loc[:-1]))
        detail = f"unexpected key '{key}'."
        return f"{detail} Did you mean '{suggestion}'?" if suggestion else detail

    if error_type == "missing":
        return f"'{field}' is required."

    if error_type == "enum":
        enum = enum_fields.get(str(field))
        if enum is not None:
            values = ", ".join(member.value for member in enum)
            noun = field_nouns.get(str(field), str(field))
            return f'"{given}" is not a valid {noun}. Use one of: {values}.'

    if error_type.startswith("int"):
        return f'"{given}" is not a valid integer.'
    if error_type.startswith("float"):
        return f'"{given}" is not a valid number.'

    # Fallback: Pydantic's own message, which is still reasonably clear.
    return str(error.get("msg", "invalid value"))


def format_message(filename: str, line: int | None, location: str, detail: str) -> str:
    """Format one issue: ``file line N: location: detail`` (location optional)."""
    prefix = f"{filename} line {line}" if line is not None else filename
    return f"{prefix}: {location}: {detail}" if location else f"{prefix}: {detail}"


def _suggest(key: str, candidates: list[str]) -> str | None:
    matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _dotted(path: KeyPath) -> str:
    return ".".join(str(token) for token in path)


def _valid_keys_at(root_model: type[BaseModel], path: KeyPath) -> list[str]:
    """Field names of the model that directly contains ``path``'s last key.

    Returns an empty list when the location cannot be resolved to a model (for
    example a free-form mapping), in which case no suggestion is made.
    """
    model: type[BaseModel] = root_model
    tokens = list(path)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not isinstance(token, str):
            return []
        field = model.model_fields.get(token)
        if field is None:
            return []
        inner, container = _unwrap(field.annotation)
        if inner is None:
            return []
        model = inner
        index += 1
        if container in ("dict", "list"):
            index += 1  # skip the key/index that addresses into the container
    return list(model.model_fields)


def _unwrap(annotation: Any) -> tuple[type[BaseModel] | None, str | None]:
    """Find the BaseModel inside an annotation and how it is contained."""
    origin = get_origin(annotation)
    if origin is None:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation, "model"
        return None, None

    args = get_args(annotation)
    if origin is Union or origin is UnionType:
        for arg in args:
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                return arg, "model"
        return None, None
    if origin is list and args:
        inner = args[0]
        if isinstance(inner, type) and issubclass(inner, BaseModel):
            return inner, "list"
    if origin is dict and len(args) == 2:
        value = args[1]
        if isinstance(value, type) and issubclass(value, BaseModel):
            return value, "dict"
    return None, None
