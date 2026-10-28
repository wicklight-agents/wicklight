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
from wicklight.agentfile.config import EffectiveConfig
from wicklight.contracts import Capabilities, ProviderError, describe_providers
from wicklight.core import AutoApprove, TerminalApprover
from wicklight.counterfactual import counterfactual_replay
from wicklight.explain import (
    ExplainError,
    explain_step,
    explanation_json,
    render_explanation,
)
from wicklight.preflight import PreflightIssue, preflight, routing_issues
from wicklight.providers import FakeProvider, FakeScript
from wicklight.providers.credentials import required_keys
from wicklight.tools import MockWorld
from wicklight.trace import Trace, TraceReadError, dump_trace_event, read_trace
from wicklight.trace.console import StepPrinter, filter_events, print_trace
from wicklight.trace.stepper import ReplayStepper, run_stepper

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
    target: Annotated[
        Path,
        typer.Argument(help="Path to an agent file (.md) or deploy file (.yaml)."),
    ],
) -> None:
    """Validate an agent or deploy file and print its effective settings.

    A ``.yaml``/``.yml`` file is treated as a deploy file (validated together
    with its agent file); anything else is an agent file. Exits 0 when valid and
    non-zero (usable in CI) on any read or validation error.
    """
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        message = exc.strerror or str(exc)
        typer.echo(f"{target}: {message}", err=True)
        raise typer.Exit(code=1) from exc

    if target.suffix in (".yaml", ".yml"):
        _check_deploy(target, text)
        return

    try:
        agent, config = parse_and_validate(text, filename=target.name)
    except AgentFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc

    effective = build_effective_config(config, provided=agent.frontmatter)
    typer.echo(render_effective_config(effective))
    typer.echo("")
    typer.echo(_render_api_keys(effective))
    typer.echo("")

    fatal = _report_issues("capabilities", preflight(effective, agent))
    typer.echo("")
    fatal |= _report_issues("routing", routing_issues(effective))
    if fatal:
        raise typer.Exit(code=1)


def _check_deploy(path: Path, text: str) -> None:
    """Validate a deploy file together with its agent file, and print it."""
    from wicklight.deploy import (
        build_effective_deployment,
        parse_and_validate_deploy,
        render_effective_deployment,
    )
    from wicklight.deploy.errors import DeployFileValidationError

    try:
        _deploy_file, config = parse_and_validate_deploy(text, filename=path.name)
    except DeployFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc

    # Validate the referenced agent file too (resolved relative to the deploy file).
    agent_path = path.parent / config.agent
    try:
        agent_text = agent_path.read_text(encoding="utf-8")
        agent, _agent_config = parse_and_validate(agent_text, filename=agent_path.name)
    except OSError as exc:
        typer.echo(f"{path.name}: agent file not found: {config.agent}", err=True)
        raise typer.Exit(code=1) from exc
    except AgentFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc

    agent_name = str(agent.frontmatter.get("name")) if agent.frontmatter else None
    effective = build_effective_deployment(
        config, base_dir=path.parent, agent_name=agent_name
    )
    typer.echo(render_effective_deployment(effective))


def _report_issues(heading: str, issues: list[PreflightIssue]) -> bool:
    """Print a preflight section; return True if a fatal issue was found."""
    typer.echo(f"{heading}:")
    if not issues:
        typer.echo("  ok")
        return False
    for issue in issues:
        label = "error" if issue.fatal else "warning"
        typer.echo(f"  {label}: {issue.message}", err=True)
    return any(issue.fatal for issue in issues)


def _render_api_keys(config: EffectiveConfig) -> str:
    """Report which API keys the config's models need, and whether they are set.

    Keys are read from the environment, never the agent file, and their values
    are never printed — only the variable name and whether it is present.
    """
    models = config.models
    model_ids = [
        models.default.value,
        *(route.use for route in models.routes.value),
        *models.fallback.value,
    ]
    requirements = required_keys(model_ids)
    lines = ["api keys:"]
    if not requirements:
        lines.append("  none required")
        return "\n".join(lines)
    for req in requirements:
        state = "set" if req.is_set else "MISSING"
        lines.append(f"  {req.env_var}: {state} (for {req.provider})")
    return "\n".join(lines)


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
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Stub every tool: show what would run after checks, execute nothing.",
        ),
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
    # A dry run is a what-if: assume approvals are granted so the full path is
    # shown; the automatic permission and policy checks still genuinely block.
    approver = AutoApprove() if dry_run else TerminalApprover()

    try:
        result = agent.run(
            task,
            provider=provider,
            world=world_state,
            approver=approver,
            dry_run=dry_run,
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


@app.command()
def replay(
    trace_file: Annotated[
        Path, typer.Argument(help="Path to the trace .jsonl or .jsonl.gz file.")
    ],
    all_events: Annotated[
        bool,
        typer.Option("--all", help="Print the whole run instead of stepping (for CI)."),
    ] = False,
    agent: Annotated[
        Path | None,
        typer.Option(
            "--agent",
            help="Re-check the run's decisions against this changed agent file.",
        ),
    ] = None,
) -> None:
    """Step through a past run, event by event. No model calls, no side effects.

    With ``--agent`` it instead replays the run's recorded decisions against a
    changed agent file and reports the first outcome that differs.
    """
    try:
        trace = read_trace(trace_file)
    except TraceReadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    console = Console()
    if agent is not None:
        _counterfactual(console, trace, agent)
        return
    if all_events:
        print_trace(console, trace)
        return
    run_stepper(ReplayStepper(trace.events), console, readline=input)


def _counterfactual(console: Console, trace: Trace, agent_path: Path) -> None:
    result = counterfactual_replay(trace, agent_path)
    if result.divergence is None:
        console.print(
            f"No outcomes changed across {result.evaluated_steps} tool call(s) "
            f"under {agent_path.name}."
        )
    else:
        d = result.divergence
        console.print(d.describe(), style="bold red")
        if d.counterfactual.reason:
            console.print(f"  reason: {d.counterfactual.reason}")
        console.print(
            "[dim]stopped here: later model decisions depended on the old result.[/]"
        )
    console.print(f"[dim]counterfactual trace: {result.trace_path}[/]")


@app.command()
def explain(
    trace_file: Annotated[
        Path, typer.Argument(help="Path to the trace .jsonl or .jsonl.gz file.")
    ],
    step: Annotated[int, typer.Option("--step", help="The step to explain.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print a structured JSON explanation.")
    ] = False,
) -> None:
    """Show what the model saw at a step, and what happened next."""
    try:
        trace = read_trace(trace_file)
        explanation = explain_step(trace, step)
    except TraceReadError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    except ExplainError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc

    if as_json:
        typer.echo(json.dumps(explanation_json(explanation), ensure_ascii=False))
        return
    render_explanation(Console(), explanation)


@app.command()
def view(
    target: Annotated[
        str | None,
        typer.Argument(
            help="A trace file or run id. Omit to list all runs under ./runs.",
        ),
    ] = None,
    host: Annotated[
        str, typer.Option("--host", help="Address to bind (loopback by default).")
    ] = "127.0.0.1",
    port: Annotated[
        int, typer.Option("--port", help="Port to bind (0 picks a free one).")
    ] = 0,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not open a browser.")
    ] = False,
    live: Annotated[
        bool,
        typer.Option("--live", help="Follow a run in progress, appending steps."),
    ] = False,
    runs_dir: Annotated[
        Path, typer.Option("--runs-dir", help="Directory of run traces.")
    ] = Path("runs"),
) -> None:
    """Open a local web viewer for runs (offline, no account).

    With no target, lists every run under ``--runs-dir``. With a trace file or
    run id, opens that run; add ``--live`` to follow it as it is written.
    """
    from wicklight.viewer.server import serve
    from wicklight.viewer.source import RunSource, run_id_for

    live_run_id: str | None = None
    if target is None:
        if live:
            typer.echo("--live needs a run id or trace file.", err=True)
            raise typer.Exit(code=1)
        source = RunSource.from_dir(runs_dir)
        if not source.run_ids():
            typer.echo(f"no runs found in {runs_dir}/", err=True)
            raise typer.Exit(code=1)
    else:
        trace_path = _resolve_trace_target(target, runs_dir)
        if trace_path is None:
            typer.echo(f"no trace found for: {target}", err=True)
            raise typer.Exit(code=1)
        # Serve the whole runs dir when present so run-list links resolve too.
        source = RunSource.from_dir(runs_dir)
        if run_id_for(trace_path) not in source.run_ids():
            source = RunSource.from_path(trace_path)
        if live:
            live_run_id = run_id_for(trace_path)

    try:
        serve(
            source,
            host=host,
            port=port,
            open_browser=not no_browser,
            live_run_id=live_run_id,
        )
    except KeyboardInterrupt:  # Ctrl+C is the documented way to stop.
        typer.echo("\nstopped.")


def _resolve_trace_target(target: str, runs_dir: Path) -> Path | None:
    """Resolve a CLI target to a trace file: a direct path or a run id."""
    direct = Path(target)
    if direct.is_file():
        return direct
    for suffix in (".jsonl", ".jsonl.gz"):
        candidate = runs_dir / f"{target}{suffix}"
        if candidate.is_file():
            return candidate
    return None


@app.command()
def deploy(
    deploy_file: Annotated[
        Path, typer.Argument(help="Path to the deploy.yaml to build an image for.")
    ],
    engine: Annotated[
        str | None,
        typer.Option("--engine", help="Container engine: docker or podman (auto)."),
    ] = None,
    print_dockerfile: Annotated[
        bool,
        typer.Option("--print-dockerfile", help="Print the generated build file."),
    ] = False,
) -> None:
    """Build a locked-down container image for a deployment.

    Generates the build file automatically (no Dockerfile to write) and builds a
    hardened, non-root, shell-less image. ``--print-dockerfile`` just shows the
    generated build file.
    """
    from wicklight.deploy.build import (
        BuildError,
        build_deployment,
        generate_containerfile,
    )
    from wicklight.deploy.engine import EngineError
    from wicklight.deploy.errors import DeployFileValidationError

    try:
        if print_dockerfile:
            typer.echo(generate_containerfile(deploy_file))
            return
        result = build_deployment(deploy_file, engine=engine)
    except DeployFileValidationError as exc:
        for issue in exc.issues:
            typer.echo(issue.message, err=True)
        raise typer.Exit(code=1) from exc
    except (BuildError, EngineError, AgentFileValidationError) as exc:
        typer.echo(f"deploy failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"built {result.tag} with {result.engine}")


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
