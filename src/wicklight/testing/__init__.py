"""Conformance test kits every plugin must pass.

The kits are what make the Provider, Tool, and Policy contracts enforceable:
a plugin is only compliant if it passes the kit for the contract it claims to
implement.
"""

from __future__ import annotations

from wicklight.testing.conformance import (
    CheckResult,
    ConformanceCase,
    ConformanceFactory,
    ConformanceReport,
    Scenario,
    run_provider_conformance,
)

__all__ = [
    "CheckResult",
    "ConformanceCase",
    "ConformanceFactory",
    "ConformanceReport",
    "Scenario",
    "run_provider_conformance",
]
