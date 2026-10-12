"""The policy conformance kit.

Checks that a policy honors the Policy contract: a valid typed config schema, a
``check`` that returns an :class:`Allow` or :class:`Deny` (never anything else),
decisions that are deterministic, denials that always carry a reason, no mutation
of the call it inspects, and a fast, side-effect-free decision.

The author supplies the policy *factory* (its class), optional config, and —
to exercise the deny path — a call the policy should block.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any

from pydantic import BaseModel

from wicklight.contracts.policy import (
    Allow,
    Deny,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    PolicyFactory,
)
from wicklight.contracts.version import CONTRACT_VERSION
from wicklight.testing.conformance import CheckResult, ConformanceReport

#: A decision taking longer than this is not the "fast, pure" policy promised.
_FAST_SECONDS = 0.1


def run_policy_conformance(
    factory: PolicyFactory,
    *,
    config: Mapping[str, Any] | None = None,
    sample_call: PolicyCall | None = None,
    deny_call: PolicyCall | None = None,
    ctx: PolicyContext | None = None,
) -> ConformanceReport:
    """Run the policy conformance kit, returning a report of each check.

    ``sample_call`` drives the allow/determinism/no-mutation checks; ``deny_call``
    (optional) must be a call the policy blocks, to prove denials carry a reason.
    """
    context = ctx if ctx is not None else PolicyContext()
    call = sample_call if sample_call is not None else PolicyCall(tool="noop")

    results: list[CheckResult] = []
    policy, config_result = _build_policy(factory, config)
    results.append(config_result)
    if policy is None:
        # Nothing else can run without a constructed policy.
        return ConformanceReport(contract_version=CONTRACT_VERSION, results=results)

    results.append(
        _guard("returns_decision", lambda: _check_decision(policy, call, context))
    )
    results.append(
        _guard("deterministic", lambda: _check_deterministic(policy, call, context))
    )
    results.append(
        _guard("no_mutation", lambda: _check_no_mutation(policy, call, context))
    )
    results.append(_guard("fast", lambda: _check_fast(policy, call, context)))
    if deny_call is not None:
        results.append(
            _guard("reason_on_deny", lambda: _check_reason(policy, deny_call, context))
        )
    else:
        results.append(
            CheckResult("reason_on_deny", "skip", "no deny_call sample supplied")
        )
    return ConformanceReport(contract_version=CONTRACT_VERSION, results=results)


def _build_policy(
    factory: PolicyFactory, config: Mapping[str, Any] | None
) -> tuple[Any | None, CheckResult]:
    # A misbehaving factory may declare config_model as a non-model at runtime,
    # so probe it dynamically rather than trusting the static type.
    probe: Any = factory
    model = probe.config_model
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return None, CheckResult(
            "config_schema", "fail", "config_model must be a Pydantic model"
        )
    try:
        validated = model.model_validate(dict(config or {}))
        policy = factory(validated)
    except Exception as exc:  # noqa: BLE001 - recorded in the report, not swallowed
        return None, CheckResult(
            "config_schema", "fail", str(exc) or type(exc).__name__
        )
    return policy, CheckResult("config_schema", "pass")


def _guard(name: str, check: Callable[[], None]) -> CheckResult:
    try:
        check()
    except Exception as exc:  # noqa: BLE001 - recorded in the report, not swallowed
        return CheckResult(name, "fail", str(exc) or type(exc).__name__)
    return CheckResult(name, "pass")


def _fresh(call: PolicyCall) -> PolicyCall:
    """A pristine copy of the call so one check can't poison another."""
    return replace(call, arguments=dict(call.arguments))


def _decide(policy: Any, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
    decision = policy.check(_fresh(call), ctx)
    if not isinstance(decision, (Allow, Deny)):
        raise AssertionError(
            f"check must return Allow or Deny, got {type(decision).__name__}"
        )
    return decision


def _check_decision(policy: Any, call: PolicyCall, ctx: PolicyContext) -> None:
    _decide(policy, call, ctx)


def _check_deterministic(policy: Any, call: PolicyCall, ctx: PolicyContext) -> None:
    first = _decide(policy, call, ctx)
    second = _decide(policy, call, ctx)
    if first != second:
        raise AssertionError(
            f"check is not deterministic: {first!r} then {second!r} for the same call"
        )


def _check_no_mutation(policy: Any, call: PolicyCall, ctx: PolicyContext) -> None:
    probe = _fresh(call)
    before = dict(probe.arguments)
    policy.check(probe, ctx)
    if dict(probe.arguments) != before:
        raise AssertionError(
            "check mutated the call's arguments; policies must be pure"
        )


def _check_fast(policy: Any, call: PolicyCall, ctx: PolicyContext) -> None:
    start = time.perf_counter()
    _decide(policy, call, ctx)
    elapsed = time.perf_counter() - start
    if elapsed > _FAST_SECONDS:
        raise AssertionError(
            f"check took {elapsed * 1000:.0f}ms (> {_FAST_SECONDS * 1000:.0f}ms); "
            f"policies must be fast and do no I/O"
        )


def _check_reason(policy: Any, deny_call: PolicyCall, ctx: PolicyContext) -> None:
    decision = _decide(policy, deny_call, ctx)
    if not isinstance(decision, Deny):
        raise AssertionError(
            "deny_call was expected to be blocked, but the policy allowed it"
        )
    if not decision.reason.strip():
        raise AssertionError("a Deny decision must carry a non-empty reason")
