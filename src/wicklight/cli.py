"""Command-line entry point for Wicklight.

This module defines the Typer application exposed as the ``wicklight`` console
script (see ``[project.scripts]`` in ``pyproject.toml``). It provides
``--version`` and ``--help``, the ``check`` and ``run`` commands, and the
``trace`` and ``providers`` command groups.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from wicklight import __version__
from wicklight.agent import Agent
from wicklight.agentfile import (
    AgentFileValidationError,
    build_effective_config,
    parse_and_validate,
    render_effective_config,
)
from wicklight.contracts import Capabilities, ProviderError, describe_providers
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import TraceReadError, dump_trace_event, read_trace
from wicklight.trace.console import StepPrinter, filter_events, print_trace

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
def run(
    agent_file: Annotated[Path, typer.Argument(help="Path to the agent file.")],
    task: Annotated[str, typer.Argument(help="The task for the agent.")],
    fake: Annotated[
        Path | None,
        typer.Option("--fake", help="Run with the fake provider using this script."),
    ] = None,
    world: Annotated[
        Path | None,
        typer.Option("--world", help="Seed the mock world from this YAML file."),
    ] = None,
    trace: Annotated[
        bool, typer.Option("--trace", help="Stream each trace event live.")
    ] = False,
    runs_dir: Annotated[
        Path, typer.Option("--runs-dir", help="Directory for trace files.")
    ] = Path("runs"),
) -> None:
    """Run an agent from the command line."""
    console = Console()
    try:
        agent = Agent.load(agent_file)
    except AgentFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc
    except OSError as exc:
        typer.echo(f"{agent_file}: {exc.strerror or exc}", err=True)
        raise typer.Exit(code=1) from exc

    provider = FakeProvider(FakeScript.from_path(fake)) if fake is not None else None
    world_state = (
        MockWorld.from_yaml(world.read_text(encoding="utf-8"))
        if world is not None
        else None
    )
    on_event = StepPrinter(console) if trace else None

    try:
        result = agent.run(
            task,
            provider=provider,
            world=world_state,
            runs_dir=runs_dir,
            on_event=on_event,
        )
    except ProviderError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not trace:
        console.print(result.output or "(no output)")
    console.print(
        f"\n[dim]run {result.run_id}: {result.status.value} in "
        f"{result.steps} steps · trace: {result.trace_path}[/]"
    )
    if not result.completed:
        raise typer.Exit(code=1)


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


providers_app = typer.Typer(
    name="providers", help="Inspect installed provider plugins.", no_args_is_help=True
)
app.add_typer(providers_app)

_STATUS_COLORS = {
    "ok": "green",
    "deprecated": "yellow",
    "unsupported": "red",
    "error": "red",
}


@providers_app.command("list")
def providers_list() -> None:
    """List installed provider plugins, their versions, and capabilities."""
    infos = describe_providers()
    console = Console()
    if not infos:
        console.print("No providers are installed.")
        return

    table = Table(title="Installed providers")
    for column in ("name", "package", "version", "contract", "status", "capabilities"):
        table.add_column(column)
    for info in infos:
        color = _STATUS_COLORS.get(info.status, "white")
        table.add_row(
            info.name,
            info.package or "—",
            info.package_version or "—",
            info.contract_version or "—",
            f"[{color}]{info.status}[/]",
            _capabilities_summary(info.capabilities),
        )
    console.print(table)


def _capabilities_summary(capabilities: Capabilities | None) -> str:
    if capabilities is None:
        return "—"
    parts: list[str] = []
    if capabilities.streaming:
        parts.append("streaming")
    if capabilities.parallel_tool_calls:
        parts.append("parallel-tools")
    if capabilities.structured_output:
        parts.append("structured-output")
    if capabilities.max_context_tokens is not None:
        parts.append(f"ctx={capabilities.max_context_tokens}")
    return ", ".join(parts) or "—"


def main() -> None:
    """Entry point for the ``wicklight`` console script."""
    app()


if __name__ == "__main__":
    main()
