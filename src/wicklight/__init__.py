"""Wicklight — a small, observable, safe-by-default agent harness.

Define an agent in one readable file, run it with full tracing, and deploy it
with one command.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["Agent", "RunResult", "__version__"]

#: Single source of truth for the package version (read by Hatchling at build
#: time via ``[tool.hatch.version]`` in ``pyproject.toml``).
__version__ = "0.1.0"

if TYPE_CHECKING:
    from wicklight.agent import Agent, RunResult


def __getattr__(name: str) -> Any:
    # Resolve the public API lazily so importing the package stays light
    # (it is imported very early, e.g. by the pytest plugin).
    if name in {"Agent", "RunResult"}:
        from wicklight import agent

        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
