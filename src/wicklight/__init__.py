"""Wicklight — a small, observable, safe-by-default agent harness.

Define an agent in one readable file, run it with full tracing, and deploy it
with one command.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Single source of truth for the package version (read by Hatchling at build
#: time via ``[tool.hatch.version]`` in ``pyproject.toml``).
__version__ = "0.1.0"
