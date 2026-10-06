"""Human-friendly agent-file errors with line numbers.

Pydantic and YAML errors are precise but unfriendly. This module turns them into
messages a beginner can act on — citing the source line, naming the location,
explaining the fix, and suggesting a correction for a misspelled key — and
reports every problem in one pass instead of stopping at the first.

    agent.md line 9: tools.send_email.level: "writ" is not a valid level.
    Use one of: off, read, write, irreversible.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails

from wicklight.agentfile.parser import AgentFile, AgentFileError, parse_agent_file
from wicklight.agentfile.schema import (
    AgentConfig,
    Approval,
    PermissionLevel,
    validate_frontmatter,
)

# Fields whose values are enums, so we can render "Use one of: ...".
_ENUM_FIELDS: dict[str, type[Enum]] = {"level": PermissionLevel, "approval": Approval}
# How to name a field in a message ("... is not a valid <noun>").
_FIELD_NOUN: dict[str, str] = {"level": "level", "approval": "approval"}


@dataclass(frozen=True)
class AgentFileIssue:
    """One problem found in an agent file, formatted for a human."""

    message: str
    line: int | None
    location: str


class AgentFileValidationError(Exception):
    """Raised when an agent file has one or more problems.

    ``issues`` holds every problem found in a single pass; ``str`` of the error
    is the issues joined by newlines.
    """

    def __init__(self, issues: list[AgentFileIssue], *, filename: str) -> None:
        self.issues = issues
        self.filename = filename
        super().__init__("\n".join(issue.message for issue in issues))


def check_agent_file(text: str, *, filename: str = "agent.md") -> AgentConfig:
    """Parse and validate ``text``, raising with friendly messages on any problem."""
    try:
        agent = parse_agent_file(text)
    except AgentFileError as exc:
        issue = AgentFileIssue(
            message=_format(filename, exc.line, "", str(exc)),
            line=exc.line,
            location="",
        )
        raise AgentFileValidationError([issue], filename=filename) from exc

    try:
        return validate_frontmatter(agent.frontmatter)
    except ValidationError as exc:
        issues = _issues_from_validation(exc, agent, filename=filename)
        raise AgentFileValidationError(issues, filename=filename) from exc


def check_agent_path(path: str | Path) -> AgentConfig:
    """Read, parse, and validate an agent file from disk."""
    path = Path(path)
    return check_agent_file(path.read_text(encoding="utf-8"), filename=path.name)


def _issues_from_validation(
    exc: ValidationError, agent: AgentFile, *, filename: str
) -> list[AgentFileIssue]:
    issues = [
        _issue_from_error(error, agent, filename=filename) for error in exc.errors()
    ]
    # Stable order: by line (errors without a line last), then by location.
    issues.sort(key=lambda i: (i.line is None, i.line or 0, i.location))
    return issues


def _issue_from_error(
    error: ErrorDetails, agent: AgentFile, *, filename: str
) -> AgentFileIssue:
    loc = tuple(error["loc"])
    error_type = str(error["type"])

    # Unexpected and missing keys read better when the message names the
    # container and the detail names the key.
    if error_type in ("extra_forbidden", "missing"):
        location = _dotted(loc[:-1])
    else:
        location = _dotted(loc)
    line = agent.line_of(*loc)

    detail = _detail(error_type, loc, error)
    return AgentFileIssue(
        message=_format(filename, line, location, detail),
        line=line,
        location=location,
    )


def _detail(error_type: str, loc: tuple[str | int, ...], error: ErrorDetails) -> str:
    given = error.get("input")
    field = loc[-1] if loc else ""

    if error_type == "extra_forbidden":
        key = str(field)
        suggestion = _suggest(key, _valid_keys_at(loc[:-1]))
        detail = f"unexpected key '{key}'."
        return f"{detail} Did you mean '{suggestion}'?" if suggestion else detail

    if error_type == "missing":
        return f"'{field}' is required."

    if error_type == "enum":
        enum = _ENUM_FIELDS.get(str(field))
        if enum is not None:
            values = ", ".join(member.value for member in enum)
            noun = _FIELD_NOUN.get(str(field), str(field))
            return f'"{given}" is not a valid {noun}. Use one of: {values}.'

    if error_type.startswith("int"):
        return f'"{given}" is not a valid integer.'
    if error_type.startswith("float"):
        return f'"{given}" is not a valid number.'

    # Fallback: Pydantic's own message, which is still reasonably clear.
    return str(error.get("msg", "invalid value"))


def _format(filename: str, line: int | None, location: str, detail: str) -> str:
    prefix = f"{filename} line {line}" if line is not None else filename
    return f"{prefix}: {location}: {detail}" if location else f"{prefix}: {detail}"


def _suggest(key: str, candidates: list[str]) -> str | None:
    matches = difflib.get_close_matches(key, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _dotted(path: tuple[str | int, ...]) -> str:
    return ".".join(str(token) for token in path)


def _valid_keys_at(path: tuple[str | int, ...]) -> list[str]:
    """Field names of the model that directly contains ``path``'s last key.

    Returns an empty list when the location cannot be resolved to a model (for
    example a free-form policy mapping), in which case no suggestion is made.
    """
    model: type[BaseModel] = AgentConfig
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
