"""Command-line entry point for Wicklight.

This module defines the Typer application exposed as the ``wicklight`` console
script (see ``[project.scripts]`` in ``pyproject.toml``). It provides
``--version`` and ``--help``, the ``check`` command, the ``trace`` command
group, and a ``run`` placeholder that fails loudly until M5 lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from wicklight import __version__
from wicklight.agentfile import (
    AgentFileValidationError,
    build_effective_config,
    parse_and_validate,
    render_effective_config,
)
from wicklight.trace import TraceReadError, dump_trace_event, read_trace
from wicklight.trace.console import filter_events, print_trace

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
def check(
    agent_file: Annotated[
        Path, typer.Argument(help="Path to the agent file to validate.")
    ],
) -> None:
    """Validate an agent file and print its effective config.

    Exits 0 when the file is valid, and non-zero (usable in CI) when it cannot
    be read or has any validation error.
    """
    try:
        text = agent_file.read_text(encoding="utf-8")
    except OSError as exc:
        message = exc.strerror or str(exc)
        typer.echo(f"{agent_file}: {message}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        agent, config = parse_and_validate(text, filename=agent_file.name)
    except AgentFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc

    effective = build_effective_config(config, provided=agent.frontmatter)
    typer.echo(render_effective_config(effective))


@app.command()
def run() -> None:
    """Run an agent with step-by-step tracing (M5)."""
    _not_implemented("run")


trace_app = typer.Typer(name="trace", help="Inspect a run trace.", no_args_is_help=True)
app.add_typer(trace_app)


@trace_app.command("show")
def trace_show(
    trace_file: Annotated[
        Path, typer.Argument(help="Path to the trace .jsonl or .jsonl.gz file.")
    ],
    step: Annotated[
        int | None, typer.Option("--step", help="Only show events at this step.")
    ] = None,
    event_type: Annotated[
        str | None, typer.Option("--type", help="Only show events of this type.")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print raw JSON events instead of a trace.")
    ] = False,
) -> None:
    """Print a run trace step by step."""
    try:
        trace = read_trace(trace_file)
    except TraceReadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        for event in filter_events(trace.events, step=step, event_type=event_type):
            typer.echo(json.dumps(dump_trace_event(event), ensure_ascii=False))
        return

    print_trace(Console(), trace, step=step, event_type=event_type)


def main() -> None:
    """Entry point for the ``wicklight`` console script."""
    app()


if __name__ == "__main__":
    main()
