"""The tool conformance kit.

Checks that a tool honors the Tool contract: a valid input schema, a declared
risk and network-hosts/sensitivity, and a ``run`` that returns a structured
:class:`ToolResult` rather than raising. The author supplies a sample valid
input to drive the check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from pydantic import BaseModel

from wicklight.contracts.tool import Tool, ToolContext, ToolResult, ToolRisk
from wicklight.contracts.version import CONTRACT_VERSION
from wicklight.testing.conformance import CheckResult, ConformanceReport


async def run_tool_conformance(
    tool: Tool, sample_input: BaseModel, *, ctx: ToolContext | None = None
) -> ConformanceReport:
    """Run the tool conformance kit, returning a report of each check."""
    probe: Any = tool
    context = ctx if ctx is not None else ToolContext()

    results = [
        _guard("risk_declared", lambda: _check_risk(probe)),
        _guard("network_hosts_declared", lambda: _check_hosts(probe)),
        _guard("input_schema", lambda: _check_schema(probe, sample_input)),
        _guard("sensitive_declared", lambda: _check_sensitive(probe, sample_input)),
        await _guard_async("returns_result", probe, sample_input, context),
    ]
    return ConformanceReport(contract_version=CONTRACT_VERSION, results=results)


def _guard(name: str, check: Callable[[], None]) -> CheckResult:
    try:
        check()
    except Exception as exc:  # noqa: BLE001 - recorded in the report, not swallowed
        return CheckResult(name, "fail", str(exc) or type(exc).__name__)
    return CheckResult(name, "pass")


async def _guard_async(
    name: str, probe: Any, sample_input: BaseModel, ctx: ToolContext
) -> CheckResult:
    try:
        result = await probe.run(sample_input, ctx)
        if not isinstance(result, ToolResult):
            raise AssertionError(
                f"run must return a ToolResult, got {type(result).__name__}"
            )
    except Exception as exc:  # noqa: BLE001 - recorded in the report, not swallowed
        return CheckResult(name, "fail", str(exc) or type(exc).__name__)
    return CheckResult(name, "pass")


def _check_risk(probe: Any) -> None:
    if not isinstance(probe.risk, ToolRisk):
        raise AssertionError(
            "risk must be declared as a ToolRisk (read/write/irreversible)"
        )


def _check_hosts(probe: Any) -> None:
    hosts = probe.network_hosts
    if not isinstance(hosts, list):
        raise AssertionError("network_hosts must be a list of hostnames")
    if not all(isinstance(host, str) for host in cast("list[object]", hosts)):
        raise AssertionError("network_hosts must be a list of hostnames")


def _check_schema(probe: Any, sample_input: BaseModel) -> None:
    model = probe.input_model
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise AssertionError("input_model must be a Pydantic model")
    if not isinstance(sample_input, model):
        raise AssertionError("the sample input does not match the tool's input_model")


def _check_sensitive(probe: Any, sample_input: BaseModel) -> None:
    result = probe.is_sensitive(sample_input)
    if not isinstance(result, bool):
        raise AssertionError("is_sensitive must return a bool")
