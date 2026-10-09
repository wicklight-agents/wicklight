"""Tests for the Typer CLI skeleton (DTN-191)."""

from __future__ import annotations

from typer.testing import CliRunner

from wicklight import __version__
from wicklight.cli import app

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lists_placeholder_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("check", "run", "trace"):
        assert command in result.output


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])
    # no_args_is_help prints usage and signals "no command given" (exit 2).
    assert result.exit_code == 2
    assert "Usage" in result.output
