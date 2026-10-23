"""Human-friendly agent-file errors with line numbers.

Pydantic and YAML errors are precise but unfriendly. This module turns them into
messages a beginner can act on — citing the source line, naming the location,
explaining the fix, and suggesting a correction for a misspelled key — and
reports every problem in one pass instead of stopping at the first.

    agent.md line 9: tools.send_email.level: "writ" is not a valid level.
    Use one of: off, read, write, irreversible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from wicklight.agentfile.parser import AgentFile, AgentFileError, parse_agent_file
from wicklight.agentfile.schema import (
    AgentConfig,
    Approval,
    PermissionLevel,
    validate_frontmatter,
)
from wicklight.configerrors import format_issues, format_message

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


def parse_and_validate(
    text: str, *, filename: str = "agent.md", path: Path | None = None
) -> tuple[AgentFile, AgentConfig]:
    """Parse and validate ``text``, returning both the parsed file and config.

    Raises :class:`AgentFileValidationError` with friendly, line-numbered
    messages on any problem. Callers that need the raw frontmatter (e.g. to
    build an effective config) use the returned :class:`AgentFile`.

    Pass ``path`` when the text came from a file: it is recorded on the returned
    :class:`AgentFile` so runtime trace citations (permission and policy denials)
    name the real file, and its name is used in error messages.
    """
    name = path.name if path is not None else filename
    try:
        agent = parse_agent_file(text, path=path)
    except AgentFileError as exc:
        issue = AgentFileIssue(
            message=format_message(name, exc.line, "", str(exc)),
            line=exc.line,
            location="",
        )
        raise AgentFileValidationError([issue], filename=name) from exc

    try:
        config = validate_frontmatter(agent.frontmatter)
    except ValidationError as exc:
        issues = _issues_from_validation(exc, agent, filename=name)
        raise AgentFileValidationError(issues, filename=name) from exc

    return agent, config


def check_agent_file(text: str, *, filename: str = "agent.md") -> AgentConfig:
    """Parse and validate ``text``, raising with friendly messages on any problem."""
    return parse_and_validate(text, filename=filename)[1]


def check_agent_path(path: str | Path) -> AgentConfig:
    """Read, parse, and validate an agent file from disk."""
    path = Path(path)
    return check_agent_file(path.read_text(encoding="utf-8"), filename=path.name)


def _issues_from_validation(
    exc: ValidationError, agent: AgentFile, *, filename: str
) -> list[AgentFileIssue]:
    issues = format_issues(
        exc.errors(),
        root_model=AgentConfig,
        line_of=lambda loc: agent.line_of(*loc),
        filename=filename,
        enum_fields=_ENUM_FIELDS,
        field_nouns=_FIELD_NOUN,
    )
    return [
        AgentFileIssue(message=i.message, line=i.line, location=i.location)
        for i in issues
    ]
