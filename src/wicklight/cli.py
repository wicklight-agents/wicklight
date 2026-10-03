"""Command-line entry point for Wicklight.

This module defines the Typer application exposed as the ``wicklight`` console
script (see ``[project.scripts]`` in ``pyproject.toml``). It currently provides
``--version`` and ``--help`` plus placeholders for the ``check``, ``run``, and
``trace`` commands; each placeholder fails loudly until its own ticket lands,
rather than silently doing nothing.
"""

from __future__ import annotations

from typing import Annotated

import typer

from wicklight import __version__

app = typer.Typer(
    name="wicklight",
    help="Wicklight — a small, observable, safe-by-default agent harness.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(*, value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


def _not_implemented(command: str) -> None:
    """Report that a command exists but is not implemented yet, and exit 1."""
    typer.echo(f"`wicklight {command}` is not implemented yet.", err=True)
    raise typer.Exit(code=1)


@app.callback()
def main_callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Wicklight command-line interface."""


@app.command()
def check() -> None:
    """Validate an agent file and print its effective config (DTN-197)."""
    _not_implemented("check")


@app.command()
def run() -> None:
    """Run an agent with step-by-step tracing (M5)."""
    _not_implemented("run")


@app.command()
def trace() -> None:
    """Inspect a run trace (DTN-202)."""
    _not_implemented("trace")


def main() -> None:
    """Entry point for the ``wicklight`` console script."""
    app()


if __name__ == "__main__":
    main()
