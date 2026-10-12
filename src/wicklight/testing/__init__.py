"""Conformance test kits every plugin must pass.

The kits are what make the Provider, Tool, and Policy contracts enforceable:
a plugin is only compliant if it passes the kit for the contract it claims to
implement.
"""

from __future__ import annotations

from wicklight.core import AutoApprove, AutoDeny, ScriptedApprover
from wicklight.testing.conformance import (
    CheckResult,
    ConformanceCase,
    ConformanceFactory,
    ConformanceReport,
    ProviderScenario,
    run_provider_conformance,
)
from wicklight.testing.policy_conformance import run_policy_conformance
from wicklight.testing.scenarios import Scenario, ScenarioResult
from wicklight.testing.tool_conformance import run_tool_conformance

__all__ = [
    "AutoApprove",
    "AutoDeny",
    "CheckResult",
    "ConformanceCase",
    "ConformanceFactory",
    "ConformanceReport",
    "ProviderScenario",
    "Scenario",
    "ScenarioResult",
    "ScriptedApprover",
    "run_policy_conformance",
    "run_provider_conformance",
    "run_tool_conformance",
]
