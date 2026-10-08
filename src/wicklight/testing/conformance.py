"""The provider conformance kit.

A reusable set of checks that any provider plugin must pass to prove it honors
the Provider contract. The checks are driven by a *factory* the plugin author
supplies: given a scenario, it returns a fresh provider primed for that scenario
(for the FakeProvider that means a scripted provider; for a real provider, a
recorded fixture — DTN-226). ``run_provider_conformance`` runs every applicable
check, skips capability-gated ones a provider doesn't declare, and returns a
report that names which contract version was tested and exactly what failed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from wicklight.contracts import (
    ModelRequest,
    Provider,
    ProviderError,
    StopReason,
    StreamDone,
)
from wicklight.contracts.provider import check_contract_version


class Scenario(str, Enum):
    """The situations a conforming provider must handle."""

    PLAIN = "plain"
    SINGLE_TOOL = "single_tool"
    PARALLEL_TOOLS = "parallel_tools"
    STREAMING = "streaming"
    ERROR = "error"


@dataclass(frozen=True)
class ConformanceCase:
    """A provider primed for one scenario, plus the request to send it."""

    provider: Provider
    request: ModelRequest


#: Produces a fresh :class:`ConformanceCase` for a scenario.
ConformanceFactory = Callable[[Scenario], ConformanceCase]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Literal["pass", "fail", "skip"]
    message: str = ""


@dataclass(frozen=True)
class ConformanceReport:
    """The outcome of running the conformance kit against a provider."""

    contract_version: str
    results: list[CheckResult]

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == "fail"]

    def passed(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        lines = [f"provider conformance (contract v{self.contract_version}):"]
        marks = {"pass": "ok", "fail": "FAIL", "skip": "skip"}
        for result in self.results:
            suffix = f" — {result.message}" if result.message else ""
            lines.append(f"  [{marks[result.status]}] {result.name}{suffix}")
        return "\n".join(lines)

    def assert_passed(self) -> None:
        if self.failures:
            detail = "\n".join(f"  - {r.name}: {r.message}" for r in self.failures)
            raise AssertionError(
                f"provider failed {len(self.failures)} conformance check(s) "
                f"(contract v{self.contract_version}):\n{detail}"
            )


async def run_provider_conformance(factory: ConformanceFactory) -> ConformanceReport:
    """Run the conformance kit, returning a report of every check's outcome."""
    probe = factory(Scenario.PLAIN)
    capabilities = probe.provider.capabilities
    version = probe.provider.contract_version

    results = [_version_result(version)]
    results.append(await _run("plain_completion", _check_plain(factory)))
    results.append(await _run("usage_reporting", _check_usage(factory)))
    results.append(await _run("single_tool_call", _check_single_tool(factory)))

    if capabilities.parallel_tool_calls:
        results.append(await _run("parallel_tool_calls", _check_parallel(factory)))
    else:
        results.append(
            CheckResult("parallel_tool_calls", "skip", "capability not declared")
        )

    if capabilities.streaming:
        results.append(await _run("streaming", _check_streaming(factory)))
    else:
        results.append(CheckResult("streaming", "skip", "capability not declared"))

    results.append(await _run("error_mapping", _check_error_mapping(factory)))
    return ConformanceReport(contract_version=version, results=results)


def _version_result(version: str) -> CheckResult:
    try:
        check_contract_version(version)
    except ProviderError as exc:
        return CheckResult("contract_version", "fail", str(exc))
    return CheckResult("contract_version", "pass")


async def _run(name: str, check: Awaitable[None]) -> CheckResult:
    try:
        await check
    except Exception as exc:  # noqa: BLE001 - recorded in the report, not swallowed
        return CheckResult(name, "fail", str(exc) or type(exc).__name__)
    return CheckResult(name, "pass")


async def _check_plain(factory: ConformanceFactory) -> None:
    case = factory(Scenario.PLAIN)
    # The contract guarantee here is simply that a plain completion succeeds;
    # response shape is covered by the usage and tool-call checks.
    await case.provider.complete(case.request)


async def _check_usage(factory: ConformanceFactory) -> None:
    case = factory(Scenario.PLAIN)
    usage = (await case.provider.complete(case.request)).usage
    if usage.input_tokens < 0 or usage.output_tokens < 0:
        raise AssertionError(f"usage reports negative tokens: {usage!r}")


async def _check_single_tool(factory: ConformanceFactory) -> None:
    case = factory(Scenario.SINGLE_TOOL)
    response = await case.provider.complete(case.request)
    if not response.tool_calls:
        raise AssertionError("expected at least one tool call, got none")
    if response.stop_reason is not StopReason.TOOL_USE:
        raise AssertionError(
            f"stop_reason should be tool_use, got {response.stop_reason}"
        )
    for call in response.tool_calls:
        if not call.id or not call.name:
            raise AssertionError(f"tool call is missing an id or name: {call!r}")


async def _check_parallel(factory: ConformanceFactory) -> None:
    case = factory(Scenario.PARALLEL_TOOLS)
    response = await case.provider.complete(case.request)
    if len(response.tool_calls) < 2:
        raise AssertionError(
            f"declared parallel_tool_calls but returned {len(response.tool_calls)} "
            f"tool call(s) for a parallel scenario"
        )


async def _check_streaming(factory: ConformanceFactory) -> None:
    case = factory(Scenario.STREAMING)
    events = [event async for event in case.provider.stream(case.request)]
    if not events:
        raise AssertionError("stream yielded no events")
    if not isinstance(events[-1], StreamDone):
        last = type(events[-1]).__name__
        raise AssertionError(f"a stream must end with a done event, ended with {last}")


async def _check_error_mapping(factory: ConformanceFactory) -> None:
    case = factory(Scenario.ERROR)
    try:
        await case.provider.complete(case.request)
    except ProviderError:
        return
    raise AssertionError("provider did not raise ProviderError for the error scenario")
