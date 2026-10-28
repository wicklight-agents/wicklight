"""The locked-down image builds and passes a hardening scan (DTN-253).

Marked ``docker`` and deselected by default (see pyproject); run with
``pytest -m docker``. Builds the inbox example once, then checks the image is
non-root, has no shell, runs read-only, bakes no secret, and fails fast when a
required secret is missing.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from wicklight.deploy.build import BuildResult, build_deployment
from wicklight.deploy.engine import remove_image

pytestmark = pytest.mark.docker

DEPLOY = Path("examples/deploy.yaml")


@pytest.fixture(scope="module")
def image() -> Iterator[BuildResult]:
    if shutil.which("docker") is None:
        pytest.skip("docker is not installed")
    result = build_deployment(DEPLOY, engine="docker")
    try:
        yield result
    finally:
        remove_image(result.tag, engine=result.engine)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def test_runs_as_non_root(image: BuildResult) -> None:
    out = _run("inspect", image.tag, "--format", "{{.Config.User}}").stdout.strip()
    assert out == "nonroot"


def test_has_no_shell(image: BuildResult) -> None:
    # No /bin/sh: trying to use it as the entrypoint fails to start the container.
    proc = _run("run", "--rm", "--entrypoint", "/bin/sh", image.tag, "-c", "echo hi")
    assert proc.returncode != 0
    assert "/bin/sh" in (proc.stderr + proc.stdout)


def test_root_filesystem_is_read_only(image: BuildResult) -> None:
    proc = _run(
        "run",
        "--rm",
        "--read-only",
        "--entrypoint",
        "/usr/bin/python3.11",
        image.tag,
        "-c",
        "open('/pwned', 'w')",
    )
    assert proc.returncode != 0
    assert "Read-only file system" in (proc.stderr + proc.stdout)


def test_missing_secret_fails_fast_at_start(image: BuildResult) -> None:
    proc = _run("run", "--rm", "--read-only", image.tag)
    assert proc.returncode == 1
    assert "missing secret(s): EMAIL_TOKEN" in (proc.stderr + proc.stdout)


def test_ready_when_secret_is_injected_at_runtime(image: BuildResult) -> None:
    secret = "runtime-only-secret-value"
    proc = _run("run", "--rm", "--read-only", "-e", f"EMAIL_TOKEN={secret}", image.tag)
    assert proc.returncode == 0
    assert "ready" in proc.stdout
    # The runtime secret is never baked into an image layer.
    history = _run("history", "--no-trunc", image.tag).stdout
    assert secret not in history
