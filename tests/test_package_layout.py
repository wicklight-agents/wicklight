"""Smoke tests for the repo skeleton (DTN-188).

These encode the acceptance criteria: ``import wicklight`` succeeds and every
subpackage from the implementation plan is importable.
"""

from __future__ import annotations

import importlib

import pytest

import wicklight

# Every subpackage listed in the implementation plan for the skeleton.
SUBPACKAGES = [
    "agentfile",
    "trace",
    "contracts",
    "core",
    "providers",
    "tools",
    "policies",
    "routing",
    "viewer",
    "deploy",
    "testing",
]


def test_import_wicklight_exposes_version() -> None:
    assert isinstance(wicklight.__version__, str)
    assert wicklight.__version__


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    module = importlib.import_module(f"wicklight.{name}")
    assert module.__name__ == f"wicklight.{name}"


def test_cli_exposes_callable_entry_point() -> None:
    from wicklight import cli

    assert callable(cli.main)
