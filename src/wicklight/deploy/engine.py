"""Detect and drive the container engine — Docker or Podman, whichever is here.

Both speak the same build/run verbs and the same OCI image format, so Wicklight
detects whichever is installed and shells out to it. Failures are never silent:
a non-zero command raises :class:`EngineError` carrying the engine's output.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Preference order when none is requested: Docker first (ubiquitous), then Podman.
_ENGINES = ("docker", "podman")


class EngineError(Exception):
    """Raised when no engine is found or an engine command fails."""


def detect_engine(preferred: str | None = None) -> str:
    """Return the container engine to use, or raise if none is available."""
    if preferred:
        if shutil.which(preferred) is None:
            raise EngineError(f"container engine {preferred!r} is not on PATH")
        return preferred
    for name in _ENGINES:
        if shutil.which(name) is not None:
            return name
    raise EngineError(
        "no container engine found; install Docker or Podman (or pass --engine)."
    )


def build_image(
    context_dir: Path, *, tag: str, engine: str, containerfile: str
) -> None:
    """Build ``context_dir`` into image ``tag`` with ``engine``."""
    _run(
        [engine, "build", "-f", containerfile, "-t", tag, str(context_dir)],
        cwd=context_dir,
    )


def image_history(tag: str, *, engine: str) -> str:
    """Return the image's layer history (used to check nothing secret is baked)."""
    return _run([engine, "history", "--no-trunc", tag]).stdout


def remove_image(tag: str, *, engine: str) -> None:
    """Remove an image, ignoring the case where it is already gone."""
    proc = subprocess.run(
        [engine, "rmi", "-f", tag],
        capture_output=True,
        text=True,
        check=False,
    )
    # Removal is best-effort cleanup; a missing image is fine, but log anything else.
    if proc.returncode != 0 and "No such image" not in (proc.stderr + proc.stdout):
        raise EngineError(f"{engine} rmi {tag} failed:\n{proc.stderr or proc.stdout}")


def _run(
    cmd: list[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
        check=False,
    )
    if proc.returncode != 0:
        raise EngineError(
            f"`{' '.join(cmd)}` failed (exit {proc.returncode}):\n"
            f"{proc.stderr or proc.stdout}"
        )
    return proc
