"""The supervisor runs in the real image and handles a manual trigger (DTN-256).

Docker-gated (``pytest -m docker``, deselected by default). Proves the sealed
image runs the supervisor and that a host manual trigger starts a run whose trace
records the trigger. The comprehensive in-container matrix (every trigger type,
approvals, stop/kill, Podman) is DTN-258.
"""

from __future__ import annotations

import contextlib
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from wicklight.deploy import host as hostctl
from wicklight.deploy.build import build_deployment
from wicklight.deploy.engine import remove_image
from wicklight.trace import read_trace

pytestmark = pytest.mark.docker

AGENT = "---\nname: smoke\nmodels: { default: fake/x }\ntools: {}\n---\nAnswer.\n"
FAKE_SCRIPT = "responses:\n  - text: done\n"


@pytest.fixture
def deployment(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")

    (tmp_path / "agent.md").write_text(AGENT, encoding="utf-8")
    deploy = tmp_path / "deploy.yaml"
    deploy.write_text(
        "name: smoke\nagent: agent.md\ntraces: ./runs\n", encoding="utf-8"
    )

    traces = tmp_path / "runs"
    traces.mkdir()
    (traces / "fake.yaml").write_text(FAKE_SCRIPT, encoding="utf-8")

    result = build_deployment(deploy, engine="docker")
    hostctl.start_supervisor(
        name="smoke",
        image=result.tag,
        traces_dir=traces,
        # The container's registry-resolved fake provider reads this script.
        secrets_env={"WICKLIGHT_FAKE_SCRIPT": "/app/runs/fake.yaml"},
        engine="docker",
    )
    try:
        yield "smoke", traces
    finally:
        # Cleanup is best-effort; a missing container/image is fine.
        with contextlib.suppress(Exception):
            hostctl.undeploy("smoke", engine="docker")
        with contextlib.suppress(Exception):
            remove_image(result.tag, engine="docker")


def test_manual_trigger_runs_in_the_container(deployment: tuple[str, Path]) -> None:
    name, traces = deployment

    # The supervisor is up and listed as a deployment.
    names = [d.name for d in hostctl.deployed_agents(engine="docker")]
    assert name in names

    hostctl.send_manual_trigger(traces, "summarize please")

    trace = _wait_for_trace(traces, timeout=20)
    assert trace is not None, "expected a run trace to appear"
    events = read_trace(trace).events
    started = next(e for e in events if e.type == "run_started")
    assert started.payload.trigger == "manual"
    assert any(e.type == "run_finished" for e in events)


def _wait_for_trace(traces: Path, *, timeout: float) -> Path | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = hostctl.latest_trace(traces)
        if found is not None:
            events = read_trace(found).events
            if any(e.type == "run_finished" for e in events):
                return found
        time.sleep(0.5)
    return hostctl.latest_trace(traces)
