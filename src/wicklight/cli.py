"""Command-line entry point for Wicklight.

This module exposes the ``wicklight`` console script registered in
``pyproject.toml``. The full Typer-based CLI (``check``, ``run``, ``replay``,
``explain``, ``view``, ...) is implemented in DTN-191; for now ``main`` only
reports that the CLI is not yet available so the entry point never fails
silently.
"""

from __future__ import annotations


def main() -> None:
    """Entry point for the ``wicklight`` console script."""
    raise SystemExit("The wicklight CLI is not implemented yet (see DTN-191).")


if __name__ == "__main__":
    main()
