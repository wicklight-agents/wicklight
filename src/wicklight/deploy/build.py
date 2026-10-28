"""Build a deployment image from a deploy file.

Orchestrates: validate the deploy file and its agent file, build the Wicklight
wheel, assemble a small build context (wheel + agent file + deploy file +
generated Containerfile), and run the container engine. The image is tagged with
the deployment name and a content hash of its inputs.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wicklight.agentfile import parse_and_validate
from wicklight.deploy.dockerfile import render_containerfile
from wicklight.deploy.engine import build_image, detect_engine
from wicklight.deploy.errors import parse_and_validate_deploy
from wicklight.deploy.schema import DeployConfig

_CONTAINERFILE = "Containerfile"
_AGENT_IN_CONTEXT = "agent.md"
_DEPLOY_IN_CONTEXT = "deploy.yaml"


class BuildError(Exception):
    """Raised when a deployment image cannot be prepared or built."""


@dataclass(frozen=True)
class BuildResult:
    """The outcome of building a deployment image."""

    tag: str
    engine: str


def _load(deploy_path: Path) -> tuple[DeployConfig, Path, str]:
    """Validate the deploy file and its agent file; return config + agent path."""
    text = deploy_path.read_text(encoding="utf-8")
    _file, config = parse_and_validate_deploy(text, filename=deploy_path.name)
    agent_path = deploy_path.parent / config.agent
    if not agent_path.is_file():
        raise BuildError(f"agent file not found: {config.agent}")
    # Validate the agent file too (raises AgentFileValidationError on problems).
    parse_and_validate(agent_path.read_text(encoding="utf-8"), filename=agent_path.name)
    return config, agent_path, text


def generate_containerfile(deploy_path: Path) -> str:
    """Render the Containerfile for a deploy file (``deploy --print-dockerfile``)."""
    _config, _agent_path, _text = _load(deploy_path)
    from wicklight import __version__

    return render_containerfile(
        wheel_filename=f"wicklight-{__version__}-py3-none-any.whl",
        agent_filename=_AGENT_IN_CONTEXT,
        deploy_filename=_DEPLOY_IN_CONTEXT,
    )


def build_deployment(deploy_path: Path, *, engine: str | None = None) -> BuildResult:
    """Build the deployment image for ``deploy_path`` and return its tag."""
    config, agent_path, deploy_text = _load(deploy_path)
    chosen = detect_engine(engine)

    with tempfile.TemporaryDirectory(prefix="wicklight-build-") as tmp:
        context = Path(tmp)
        wheel_name = _build_wheel(context)
        shutil.copyfile(agent_path, context / _AGENT_IN_CONTEXT)
        shutil.copyfile(deploy_path, context / _DEPLOY_IN_CONTEXT)
        containerfile = render_containerfile(
            wheel_filename=wheel_name,
            agent_filename=_AGENT_IN_CONTEXT,
            deploy_filename=_DEPLOY_IN_CONTEXT,
        )
        (context / _CONTAINERFILE).write_text(containerfile, encoding="utf-8")

        tag = image_tag(
            config.name,
            agent_text=agent_path.read_text(encoding="utf-8"),
            deploy_text=deploy_text,
        )
        build_image(context, tag=tag, engine=chosen, containerfile=_CONTAINERFILE)
    return BuildResult(tag=tag, engine=chosen)


def image_tag(name: str, *, agent_text: str, deploy_text: str) -> str:
    """``wicklight-<name>:<hash>`` — the hash covers the agent and deploy inputs."""
    digest = hashlib.sha256(f"{agent_text}\0{deploy_text}".encode()).hexdigest()[:12]
    safe = re.sub(r"[^a-z0-9_.-]+", "-", name.lower()).strip("-") or "agent"
    return f"wicklight-{safe}:{digest}"


def _build_wheel(into: Path) -> str:
    """Build the Wicklight wheel into ``into`` and return its filename."""
    root = _repo_root()
    if root is None:
        raise BuildError(
            "building a deployment image currently needs a Wicklight source "
            "checkout (installing from PyPI lands in the 0.1 release)."
        )
    proc = subprocess.run(
        ["uv", "build", "--wheel", "-o", str(into)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise BuildError(f"failed to build the wheel:\n{proc.stderr or proc.stdout}")
    wheels = sorted(into.glob("wicklight-*.whl"))
    if not wheels:
        raise BuildError("wheel build produced no .whl file")
    return wheels[-1].name


def _repo_root() -> Path | None:
    """The Wicklight source checkout root (holds pyproject.toml), or None."""
    for parent in Path(__file__).resolve().parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.is_file() and 'name = "wicklight"' in pyproject.read_text(
            encoding="utf-8"
        ):
            return parent
    return None
