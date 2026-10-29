"""Host-side control of deployed agents (DTN-257).

The host talks to a running deployment through the container engine and the
shared trace volume: it starts the supervisor container, lists deployments
(from container labels — Docker is the registry, so there is no separate state
file), reads traces and pending approvals from the mounted volume, and uses
``docker stop`` as the kill switch. This layer is Docker/Podman-first; a remote
control plane for hosted platforms (ECS, Fly) is a clean follow-on.
"""

from __future__ import annotations

import contextlib
import json
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from wicklight.deploy.approvals import approvals_dir
from wicklight.deploy.engine import EngineError, detect_engine
from wicklight.deploy.supervisor import control_dir, triggers_dir

# Container naming + labels that mark a container as a Wicklight deployment.
_LABEL = "wicklight.deployment"
_TRACES_LABEL = "wicklight.traces"
_SUPERVISOR = ["-m", "wicklight.deploy.supervisor"]
_PROXY = ["-m", "wicklight.deploy.proxy"]
_RUNTIME_PYTHON = "/usr/bin/python3.11"
_PROXY_PORT = 8080
_EGRESS_TRACE = "/app/runs/egress.jsonl"


class HostError(Exception):
    """Raised for host-side control failures."""


@dataclass(frozen=True)
class Deployment:
    """A deployed agent, as seen from the host."""

    name: str
    container: str
    status: str
    traces_dir: Path


def container_name(name: str) -> str:
    return f"wicklight-{name}"


_OPEN_PERMS = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO  # 0o777


def _prepare_traces_dir(traces_dir: Path) -> Path:
    """Create the traces dir tree and make it writable by the container's uid.

    The image runs as a fixed non-root user (65532), but a bind-mounted host
    directory keeps host ownership — and on Linux (unlike Docker Desktop's
    permissive mounts) that uid cannot write to a dir it does not own. The trace
    mount is the one writable surface shared by the host and the container
    (traces, egress log, triggers, and approvals), so we open its directories to
    all users; the tree holds only this deployment's own files.
    """
    resolved = traces_dir.resolve()
    # Pre-create the control subtree both sides write to, all world-writable.
    for directory in (
        resolved,
        control_dir(resolved),
        triggers_dir(resolved),
        approvals_dir(control_dir(resolved)),
    ):
        directory.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            directory.chmod(_OPEN_PERMS)
    return resolved


def internal_network(name: str) -> str:
    return f"wicklight-int-{name}"


def egress_network(name: str) -> str:
    return f"wicklight-ext-{name}"


def proxy_name(name: str) -> str:
    return f"wicklight-proxy-{name}"


def start_deployment(
    *,
    name: str,
    image: str,
    traces_dir: Path,
    secrets_env: dict[str, str],
    allowlist: list[str],
    engine: str | None = None,
    webhook_port: int | None = None,
    egress_proxy: bool = True,
) -> str:
    """Start the sealed deployment topology and return the supervisor container.

    With ``egress_proxy`` (the default), the agent runs on an **internal** network
    with no direct internet route; an egress-proxy sidecar on both the internal
    and an external network is the only way out, and the agent is pointed at it
    via ``HTTPS_PROXY``. Denied hosts are refused and logged to the trace volume.
    """
    chosen = detect_engine(engine)
    traces_dir = _prepare_traces_dir(traces_dir)

    if not egress_proxy:
        return start_supervisor(
            name=name,
            image=image,
            traces_dir=traces_dir,
            secrets_env=secrets_env,
            engine=chosen,
            webhook_port=webhook_port,
        )

    internal = internal_network(name)
    external = egress_network(name)
    _ensure_network(chosen, internal, internal=True)
    _ensure_network(chosen, external, internal=False)

    # The proxy: on the internal net (reachable by the agent) and the external
    # net (its own route out). It logs refusals into the shared trace volume.
    proxy = proxy_name(name)
    _run(
        [
            chosen,
            "run",
            "-d",
            "--name",
            proxy,
            "--label",
            f"{_LABEL}={name}",
            "--network",
            internal,
            "-v",
            f"{traces_dir}:/app/runs",
            "-e",
            f"WICKLIGHT_EGRESS_ALLOW={','.join(allowlist)}",
            "-e",
            f"WICKLIGHT_EGRESS_PORT={_PROXY_PORT}",
            "-e",
            f"WICKLIGHT_EGRESS_TRACE={_EGRESS_TRACE}",
            "--entrypoint",
            _RUNTIME_PYTHON,
            image,
            *_PROXY,
        ]
    )
    _run([chosen, "network", "connect", external, proxy])

    # The agent: internal network only (no internet), routed through the proxy.
    proxy_url = f"http://{proxy}:{_PROXY_PORT}"
    supervisor_env = dict(secrets_env)
    supervisor_env.update(
        {
            "HTTPS_PROXY": proxy_url,
            "HTTP_PROXY": proxy_url,
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    return start_supervisor(
        name=name,
        image=image,
        traces_dir=traces_dir,
        secrets_env=supervisor_env,
        engine=chosen,
        webhook_port=webhook_port,
        network=internal,
    )


def start_supervisor(
    *,
    name: str,
    image: str,
    traces_dir: Path,
    secrets_env: dict[str, str],
    engine: str | None = None,
    webhook_port: int | None = None,
    network: str | None = None,
) -> str:
    """Start the supervisor container for a deployment; returns its name."""
    chosen = detect_engine(engine)
    traces_dir = _prepare_traces_dir(traces_dir)
    cname = container_name(name)

    cmd = [
        chosen,
        "run",
        "-d",
        "--name",
        cname,
        "--label",
        f"{_LABEL}={name}",
        "--label",
        f"{_TRACES_LABEL}={traces_dir}",
        "--restart",
        "unless-stopped",
        "-v",
        f"{traces_dir}:/app/runs",
    ]
    if network is not None:
        cmd += ["--network", network]
    for key, value in secrets_env.items():
        cmd += ["-e", f"{key}={value}"]
    if webhook_port is not None:
        cmd += ["-p", f"127.0.0.1:{webhook_port}:8000"]
    cmd += ["--entrypoint", _RUNTIME_PYTHON, image, *_SUPERVISOR]

    _run(cmd)
    return cname


def _ensure_network(engine: str, net: str, *, internal: bool) -> None:
    """Create a network if it does not already exist (idempotent)."""
    existing = subprocess.run(
        [engine, "network", "inspect", net],
        capture_output=True,
        text=True,
        check=False,
    )
    if existing.returncode == 0:
        return
    cmd = [engine, "network", "create"]
    if internal:
        cmd.append("--internal")
    cmd.append(net)
    _run(cmd)


def deployed_agents(*, engine: str | None = None) -> list[Deployment]:
    """List Wicklight deployments known to the engine (running or stopped)."""
    chosen = detect_engine(engine)
    out = _run(
        [
            chosen,
            "ps",
            "-a",
            "--filter",
            f"label={_LABEL}",
            "--format",
            '{{.Names}}\t{{.Status}}\t{{.Label "' + _LABEL + '"}}'
            '\t{{.Label "' + _TRACES_LABEL + '"}}',
        ]
    ).stdout
    deployments: list[Deployment] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        container, status, name, traces = [*line.split("\t"), "", "", "", ""][:4]
        deployments.append(
            Deployment(
                name=name, container=container, status=status, traces_dir=Path(traces)
            )
        )
    return deployments


def find_deployment(name: str, *, engine: str | None = None) -> Deployment:
    for deployment in deployed_agents(engine=engine):
        if deployment.name == name:
            return deployment
    raise HostError(f"no deployment named {name!r}")


def send_manual_trigger(traces_dir: Path, task: str) -> None:
    """Drop a manual-trigger file the supervisor will pick up."""
    from uuid import uuid4

    folder = triggers_dir(traces_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{uuid4().hex[:12]}.json").write_text(
        json.dumps({"task": task}), encoding="utf-8"
    )


def stop(name: str, *, engine: str | None = None, timeout: int = 10) -> None:
    """The kill switch: SIGTERM the supervisor so it records a killed run."""
    chosen = detect_engine(engine)
    _run([chosen, "stop", "-t", str(timeout), container_name(name)])


def undeploy(name: str, *, engine: str | None = None) -> None:
    """Remove the deployment's containers and networks; traces are kept."""
    chosen = detect_engine(engine)
    # Remove containers first, then their networks; each step is best-effort so a
    # partially-created deployment still tears down cleanly.
    for container in (container_name(name), proxy_name(name)):
        _best_effort([chosen, "rm", "-f", container])
    for net in (internal_network(name), egress_network(name)):
        _best_effort([chosen, "network", "rm", net])


def _best_effort(cmd: list[str]) -> None:
    subprocess.run(cmd, capture_output=True, text=True, check=False)


def latest_trace(traces_dir: Path) -> Path | None:
    """The most recently modified run trace in a deployment's traces dir."""
    traces = sorted(
        traces_dir.glob("run_*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return traces[0] if traces else None


def control_paths(traces_dir: Path) -> Path:
    """The deployment's control directory (approvals, triggers)."""
    return control_dir(traces_dir)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise HostError(
            f"`{' '.join(cmd)}` failed (exit {proc.returncode}):\n"
            f"{proc.stderr or proc.stdout}"
        )
    return proc


__all__ = [
    "Deployment",
    "EngineError",
    "HostError",
    "container_name",
    "control_paths",
    "deployed_agents",
    "egress_network",
    "find_deployment",
    "internal_network",
    "latest_trace",
    "proxy_name",
    "send_manual_trigger",
    "start_deployment",
    "start_supervisor",
    "stop",
    "undeploy",
]
