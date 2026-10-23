"""Friendly, line-numbered deploy-file errors — the same style as the agent file.

Reuses :mod:`wicklight.configerrors` so a deploy file's problems read exactly
like an agent file's, reported all at once.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from pydantic import ValidationError

from wicklight.configerrors import KeyPath, format_issues, format_message
from wicklight.deploy.parser import DeployFile, DeployFileError, parse_deploy_file
from wicklight.deploy.schema import DeployConfig, SecretSource

# The ``from`` field is an enum; include both the alias and the field name since
# either may appear in a Pydantic error location.
_ENUM_FIELDS: dict[str, type[Enum]] = {
    "from": SecretSource,
    "source": SecretSource,
}
_FIELD_NOUN: dict[str, str] = {"from": "secret source", "source": "secret source"}


@dataclass(frozen=True)
class DeployFileIssue:
    """One problem found in a deploy file, formatted for a human."""

    message: str
    line: int | None
    location: str


class DeployFileValidationError(Exception):
    """Raised when a deploy file has one or more problems (all reported)."""

    def __init__(self, issues: list[DeployFileIssue], *, filename: str) -> None:
        self.issues = issues
        self.filename = filename
        super().__init__("\n".join(issue.message for issue in issues))


def parse_and_validate_deploy(
    text: str, *, filename: str = "deploy.yaml", path: Path | None = None
) -> tuple[DeployFile, DeployConfig]:
    """Parse and validate ``text``, raising with friendly, line-numbered messages."""
    name = path.name if path is not None else filename
    try:
        deploy = parse_deploy_file(text, path=path)
    except DeployFileError as exc:
        issue = DeployFileIssue(
            message=format_message(name, exc.line, "", str(exc)),
            line=exc.line,
            location="",
        )
        raise DeployFileValidationError([issue], filename=name) from exc

    try:
        config = DeployConfig.model_validate(deploy.data)
    except ValidationError as exc:
        issues = format_issues(
            exc.errors(),
            root_model=DeployConfig,
            line_of=lambda loc: _nearest_line(deploy, loc),
            filename=name,
            enum_fields=_ENUM_FIELDS,
            field_nouns=_FIELD_NOUN,
        )
        raise DeployFileValidationError(
            [DeployFileIssue(i.message, i.line, i.location) for i in issues],
            filename=name,
        ) from exc

    return deploy, config


def _nearest_line(deploy: DeployFile, loc: KeyPath) -> int | None:
    """The source line for ``loc``, falling back to its nearest known ancestor.

    A field addressed by its name rather than its alias (e.g. ``source`` for the
    ``from`` key) won't be in the line index; citing the enclosing key's line is
    better than citing none.
    """
    path = loc
    while path:
        line = deploy.line_of(*path)
        if line is not None:
            return line
        path = path[:-1]
    return None


def check_deploy_path(path: str | Path) -> DeployConfig:
    """Read, parse, and validate a deploy file from disk."""
    path = Path(path)
    return parse_and_validate_deploy(
        path.read_text(encoding="utf-8"), filename=path.name, path=path
    )[1]
