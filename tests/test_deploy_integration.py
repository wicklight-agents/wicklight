"""End-to-end: the sealed deployment is controllable and egress-restricted.

Docker-gated (``pytest -m docker``, deselected by default). Builds the image once
and, against one running sealed deployment, asserts the topology (internal
network + egress-proxy sidecar), that a triggered injection run is blocked by
policy with the secret absent from the trace, that a disallowed host is refused
and logged, and that the kill switch stops the deployment. Image hardening
(no-shell / non-root / read-only) is covered in test_deploy_image.py.

Set WICKLIGHT_TEST_ENGINE=podman to run the same suite under Podman.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from wicklight.deploy import host as hostctl
from wicklight.deploy.build import build_deployment
from wicklight.deploy.engine import remove_image
from wicklight.trace import read_trace

pytestmark = pytest.mark.docker

ENGINE = os.environ.get("WICKLIGHT_TEST_ENGINE", "docker")
SECRET = "integration-secret-do-not-leak-7f3a"

AGENT = (
    "---\n"
    "name: inbox\n"
    "models: { default: fake/x }\n"
    "tools:\n  read_inbox: read\n  send_email: write\n"
    'policies:\n  - email_only_to: ["@mycompany.com"]\n'
    "---\nHandle the inbox.\n"
)
DEPLOY = (
    "name: inbox\nagent: inbox.md\ntraces: ./runs\n"
    "secrets:\n  EMAIL_TOKEN: { from: env }\n"
)


@pytest.fixture(scope="module")
def deployment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    if shutil.which(ENGINE) is None:
        pytest.skip(f"{ENGINE} is not installed")

    root = tmp_path_factory.mktemp("deploy")
    (root / "inbox.md").write_text(AGENT, encoding="utf-8")
    (root / "deploy.yaml").write_text(DEPLOY, encoding="utf-8")

    traces = root / "runs"
    traces.mkdir()
    (traces / "world.yaml").write_text(
        Path("examples/worlds/injection.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (traces / "fake.yaml").write_text(
        Path("examples/scripts/injection.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = build_deployment(root / "deploy.yaml", engine=ENGINE)
    hostctl.start_deployment(
        name="inbox",
        image=result.tag,
        traces_dir=traces,
        secrets_env={
            "EMAIL_TOKEN": SECRET,
            "WICKLIGHT_MOCK_WORLD": "/app/runs/world.yaml",
            "WICKLIGHT_FAKE_SCRIPT": "/app/runs/fake.yaml",
        },
        allowlist=[],  # a fake agent needs no hosts: everything is denied
        engine=ENGINE,
    )
    try:
        yield "inbox", traces
    finally:
        with contextlib.suppress(Exception):
            hostctl.undeploy("inbox", engine=ENGINE)
        with contextlib.suppress(Exception):
            remove_image(result.tag, engine=ENGINE)


def _engine(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([ENGINE, *args], capture_output=True, text=True, check=False)


def test_sealed_topology_exists(deployment: tuple[str, Path]) -> None:
    name, _ = deployment
    names = {d.name for d in hostctl.deployed_agents(engine=ENGINE)}
    assert name in names
    # The egress-proxy sidecar and the internal network both exist.
    assert _engine("inspect", hostctl.proxy_name(name)).returncode == 0
    assert _engine("network", "inspect", hostctl.internal_network(name)).returncode == 0


def test_triggered_injection_is_blocked_and_secret_absent(
    deployment: tuple[str, Path],
) -> None:
    _name, traces = deployment
    hostctl.send_manual_trigger(traces, "handle my inbox")

    trace = _wait_for_run(traces, timeout=30)
    if trace is None:  # pragma: no cover - diagnostics on failure
        logs = _engine("logs", hostctl.container_name(_name))
        tfiles = list((traces / "control" / "triggers").glob("*.json"))
        runs = list(traces.glob("run_*.jsonl"))
        raise AssertionError(
            f"no run trace.\nLOGS:\n{logs.stdout}\n{logs.stderr}\n"
            f"triggers left: {[p.name for p in tfiles]}\nruns: {runs}"
        )
    events = read_trace(trace).events
    assert any(
        e.type == "policy_checked" and e.payload.decision.value == "deny"
        for e in events
    ), "the injected send should be blocked by email_only_to"

    # The secret never appears in any trace or blob on the volume.
    blob = "".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in traces.rglob("*")
        if p.is_file()
    )
    assert SECRET not in blob


def test_disallowed_host_is_refused_and_logged(deployment: tuple[str, Path]) -> None:
    name, traces = deployment
    script = (
        "import socket\n"
        "s = socket.create_connection(('" + hostctl.proxy_name(name) + "', 8080), 5)\n"
        "s.sendall(b'CONNECT example.com:443 HTTP/1.1\\r\\n\\r\\n')\n"
        "print(s.recv(100).decode('latin1'))\n"
    )
    out = _engine(
        "run",
        "--rm",
        "--network",
        hostctl.internal_network(name),
        "--entrypoint",
        "/usr/bin/python3.11",
        _image_of(name),
        "-c",
        script,
    )
    assert "403" in out.stdout, out.stdout + out.stderr

    egress = traces / "egress.jsonl"
    denied = _wait_for_egress(egress, timeout=10)
    assert denied, "the refusal should be logged as an egress_denied event"
    assert any(e["payload"]["host"] == "example.com" for e in denied)


def test_stop_halts_the_deployment(deployment: tuple[str, Path]) -> None:
    name, _traces = deployment
    hostctl.stop(name, engine=ENGINE)
    status = _engine(
        "inspect", "-f", "{{.State.Running}}", hostctl.container_name(name)
    ).stdout.strip()
    assert status == "false"  # the supervisor was stopped by the kill switch


# --- helpers ------------------------------------------------------------------


def _image_of(name: str) -> str:
    return _engine(
        "inspect", "-f", "{{.Config.Image}}", hostctl.container_name(name)
    ).stdout.strip()


def _wait_for_run(traces: Path, *, timeout: float) -> Path | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = hostctl.latest_trace(traces)
        if found and any(e.type == "run_finished" for e in read_trace(found).events):
            return found
        time.sleep(0.5)
    return hostctl.latest_trace(traces)


def _wait_for_egress(path: Path, *, timeout: float) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            lines = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if lines:
                return lines
        time.sleep(0.3)
    return []
