"""Tests for the Policy contract, discovery, and conformance kit (DTN-216)."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from wicklight.contracts import (
    ALLOW,
    Allow,
    Deny,
    EmptyConfig,
    Policy,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    PolicyError,
    PolicyRegistry,
    deny,
)
from wicklight.testing import run_policy_conformance

# --- A conforming reference policy, loaded for real from its entry point ------


def test_block_tools_discovers_from_entry_point_and_passes_the_kit() -> None:
    registry = PolicyRegistry.discover()
    assert "block_tools" in registry.names()

    factory = registry.get("block_tools")
    report = run_policy_conformance(
        factory,
        config={"tools": ["make_payment"]},
        sample_call=PolicyCall(tool="read_inbox"),
        deny_call=PolicyCall(tool="make_payment", arguments={"amount": 10}),
    )
    assert report.passed(), report.summary()
    assert report.contract_version == "1.0"
    statuses = {r.name: r.status for r in report.results}
    assert statuses["reason_on_deny"] == "pass"


def test_block_tools_allows_and_denies_as_configured() -> None:
    policy = PolicyRegistry.discover().create("block_tools", {"tools": ["delete_file"]})
    assert isinstance(
        policy.check(PolicyCall(tool="read_file"), PolicyContext()), Allow
    )
    decision = policy.check(PolicyCall(tool="delete_file"), PolicyContext())
    assert isinstance(decision, Deny)
    assert "delete_file" in decision.reason
    # The reference policy satisfies the Policy protocol structurally.
    assert isinstance(policy, Policy)


# --- Registry behaviour -------------------------------------------------------


def test_unknown_policy_raises_with_available_names() -> None:
    registry = PolicyRegistry.discover()
    with pytest.raises(PolicyError, match="unknown policy 'nope'"):
        registry.get("nope")


def test_create_rejects_invalid_config() -> None:
    registry = PolicyRegistry.discover()
    with pytest.raises(PolicyError, match="invalid config for policy 'block_tools'"):
        registry.create("block_tools", {"not_a_field": True})


def test_discover_accepts_injected_entry_points() -> None:
    class _EP:
        name = "conforming"

        def load(self) -> type[ConformingPolicy]:
            return ConformingPolicy

    registry = PolicyRegistry.discover(entry_points_=[_EP()])  # type: ignore[list-item]
    assert registry.names() == ["conforming"]


def test_non_class_entry_point_is_rejected() -> None:
    class _EP:
        name = "bad"

        def load(self) -> object:
            return object()  # an instance, not a policy class

    with pytest.raises(PolicyError, match="must load a policy class"):
        PolicyRegistry.discover(entry_points_=[_EP()])  # type: ignore[list-item]


# --- Decision value objects ---------------------------------------------------


def test_deny_requires_a_non_empty_reason() -> None:
    with pytest.raises(PolicyError, match="non-empty reason"):
        Deny("")
    with pytest.raises(PolicyError, match="non-empty reason"):
        Deny("   ")
    assert deny("blocked").reason == "blocked"


# --- The kit has teeth: non-conforming policies fail --------------------------


class ConformingPolicy:
    name: ClassVar[str] = "conforming"
    config_model: ClassVar[type[BaseModel]] = EmptyConfig

    def __init__(self, config: EmptyConfig) -> None:
        self._config = config

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        if call.tool == "blocked":
            return deny("tool is on the block list")
        return ALLOW


class MutatingPolicy(ConformingPolicy):
    """Has a side effect: it mutates the call's arguments."""

    name: ClassVar[str] = "mutating"

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        call.arguments["injected"] = True  # type: ignore[index]
        return ALLOW


class _Flaky:
    name: ClassVar[str] = "flaky"
    config_model: ClassVar[type[BaseModel]] = EmptyConfig
    _toggle: ClassVar[bool] = False

    def __init__(self, config: EmptyConfig) -> None: ...

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        _Flaky._toggle = not _Flaky._toggle
        return ALLOW if _Flaky._toggle else deny("coin flip")


class _BadDecision:
    name: ClassVar[str] = "bad"
    config_model: ClassVar[type[BaseModel]] = EmptyConfig

    def __init__(self, config: EmptyConfig) -> None: ...

    def check(self, call: PolicyCall, ctx: PolicyContext) -> Any:
        return "nope"  # not an Allow or Deny


def test_side_effecting_policy_fails_no_mutation() -> None:
    report = run_policy_conformance(
        MutatingPolicy, sample_call=PolicyCall(tool="x", arguments={"a": 1})
    )
    assert not report.passed()
    failed = {r.name for r in report.failures}
    assert "no_mutation" in failed
    message = next(r.message for r in report.failures if r.name == "no_mutation")
    assert "mutated" in message


def test_non_deterministic_policy_fails() -> None:
    report = run_policy_conformance(_Flaky, sample_call=PolicyCall(tool="x"))
    assert not report.passed()
    assert "deterministic" in {r.name for r in report.failures}


def test_wrong_return_type_fails_returns_decision() -> None:
    report = run_policy_conformance(_BadDecision, sample_call=PolicyCall(tool="x"))
    assert not report.passed()
    failed = {r.name for r in report.failures}
    assert "returns_decision" in failed


def test_conforming_policy_passes_and_skips_deny_without_sample() -> None:
    report = run_policy_conformance(ConformingPolicy, sample_call=PolicyCall(tool="ok"))
    assert report.passed(), report.summary()
    statuses = {r.name: r.status for r in report.results}
    assert statuses["reason_on_deny"] == "skip"
