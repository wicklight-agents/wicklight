"""Unit tests for the built-in policies (DTN-218): allow, deny, tricky inputs."""

from __future__ import annotations

from pathlib import Path

from wicklight.contracts import (
    Allow,
    Deny,
    PolicyCall,
    PolicyContext,
    PolicyRegistry,
)
from wicklight.policies import (
    EmailOnlyTo,
    PathsWithin,
    SenderDenylist,
    SpendLimit,
)
from wicklight.policies.email_only_to import EmailOnlyToConfig
from wicklight.policies.paths_within import PathsWithinConfig
from wicklight.policies.sender_denylist import SenderDenylistConfig
from wicklight.policies.spend_limit import SpendLimitConfig
from wicklight.testing import run_policy_conformance

CTX = PolicyContext()


# --- email_only_to ------------------------------------------------------------


def _email(allow: list[str]) -> EmailOnlyTo:
    return EmailOnlyTo(EmailOnlyToConfig(allow=allow))


def _send(to: str) -> PolicyCall:
    return PolicyCall(tool="send_email", arguments={"to": to})


def test_email_domain_allow_and_deny() -> None:
    policy = _email(["@acme.com"])
    assert isinstance(policy.check(_send("amy@acme.com"), CTX), Allow)
    decision = policy.check(_send("attacker@evil.com"), CTX)
    assert isinstance(decision, Deny)
    assert "attacker@evil.com" in decision.reason


def test_email_match_is_case_insensitive() -> None:
    policy = _email(["@Acme.com"])
    assert isinstance(policy.check(_send("AMY@ACME.COM"), CTX), Allow)


def test_email_exact_address_allowlist() -> None:
    policy = _email(["ceo@partner.com"])
    assert isinstance(policy.check(_send("ceo@partner.com"), CTX), Allow)
    assert isinstance(policy.check(_send("intern@partner.com"), CTX), Deny)


def test_email_not_applicable_without_a_recipient() -> None:
    policy = _email(["@acme.com"])
    assert isinstance(policy.check(PolicyCall(tool="read_inbox"), CTX), Allow)


def test_email_bare_list_shorthand() -> None:
    # The agent-file form `email_only_to: ["@acme.com"]`.
    config = EmailOnlyToConfig.model_validate(["@acme.com"])
    assert config.allow == ["@acme.com"]


def test_email_only_to_passes_conformance() -> None:
    run_policy_conformance(
        EmailOnlyTo,
        config={"allow": ["@acme.com"]},
        sample_call=_send("amy@acme.com"),
        deny_call=_send("x@evil.com"),
    ).assert_passed()


# --- paths_within -------------------------------------------------------------


def _read(path: str) -> PolicyCall:
    return PolicyCall(tool="read_file", arguments={"path": path})


def test_paths_within_allows_inside_and_denies_traversal(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    policy = PathsWithin(PathsWithinConfig(roots=["./docs"]))
    ctx = PolicyContext(agent_dir=tmp_path)

    assert isinstance(policy.check(_read("docs/report.md"), ctx), Allow)
    traversal = policy.check(_read("docs/../../etc/passwd"), ctx)
    assert isinstance(traversal, Deny)
    assert "outside" in traversal.reason


def test_paths_within_denies_absolute_outside(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    policy = PathsWithin(PathsWithinConfig(roots=["./docs"]))
    ctx = PolicyContext(agent_dir=tmp_path)
    assert isinstance(policy.check(_read("/etc/hosts"), ctx), Deny)


def test_paths_within_resolves_symlinks(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()
    # A symlink inside docs pointing out of the allowed tree must not escape it.
    (docs / "link").symlink_to(outside)
    policy = PathsWithin(PathsWithinConfig(roots=["./docs"]))
    ctx = PolicyContext(agent_dir=tmp_path)

    escaped = policy.check(_read("docs/link/passwd"), ctx)
    assert isinstance(escaped, Deny)


def test_paths_within_not_applicable_without_a_path() -> None:
    policy = PathsWithin(PathsWithinConfig(roots=["./docs"]))
    assert isinstance(policy.check(PolicyCall(tool="read_inbox"), CTX), Allow)


def test_paths_within_passes_conformance(tmp_path: Path) -> None:
    ctx = PolicyContext(agent_dir=tmp_path)
    run_policy_conformance(
        PathsWithin,
        config={"roots": ["./docs"]},
        sample_call=_read("docs/ok.md"),
        deny_call=_read("../escape.md"),
        ctx=ctx,
    ).assert_passed()


# --- spend_limit --------------------------------------------------------------


def _pay(amount: float) -> PolicyCall:
    return PolicyCall(tool="make_payment", arguments={"amount_usd": amount})


def test_spend_limit_per_call_cap() -> None:
    policy = SpendLimit(SpendLimitConfig(per_call_usd=100))
    assert isinstance(policy.check(_pay(50), CTX), Allow)
    decision = policy.check(_pay(150), CTX)
    assert isinstance(decision, Deny)
    assert "per-call" in decision.reason


def test_spend_limit_per_run_cap_is_a_boundary() -> None:
    policy = SpendLimit(SpendLimitConfig(max_usd=100))
    # Exactly at the cap is allowed; a cent over is not.
    assert isinstance(policy.check(_pay(100), PolicyContext(spent_usd=0)), Allow)
    assert isinstance(policy.check(_pay(30), PolicyContext(spent_usd=80)), Deny)


def test_spend_limit_catches_split_payments() -> None:
    policy = SpendLimit(SpendLimitConfig(max_usd=100))
    # Three $40 payments: the running total is what trips the third.
    assert isinstance(policy.check(_pay(40), PolicyContext(spent_usd=0)), Allow)
    assert isinstance(policy.check(_pay(40), PolicyContext(spent_usd=40)), Allow)
    assert isinstance(policy.check(_pay(40), PolicyContext(spent_usd=80)), Deny)


def test_spend_limit_not_applicable_without_an_amount() -> None:
    policy = SpendLimit(SpendLimitConfig(max_usd=100))
    assert isinstance(policy.check(PolicyCall(tool="read_inbox"), CTX), Allow)


def test_spend_limit_passes_conformance() -> None:
    run_policy_conformance(
        SpendLimit,
        config={"max_usd": 100, "per_call_usd": 50},
        sample_call=_pay(10),
        deny_call=_pay(999),
    ).assert_passed()


# --- sender_denylist ----------------------------------------------------------


def _denylist(entries: list[str]) -> SenderDenylist:
    return SenderDenylist(SenderDenylistConfig(deny=entries))


def _unsub(sender: str) -> PolicyCall:
    return PolicyCall(tool="unsubscribe", arguments={"sender": sender})


def test_sender_denylist_blocks_exact_address() -> None:
    policy = _denylist(["alerts@mybank.com"])
    decision = policy.check(_unsub("alerts@mybank.com"), CTX)
    assert isinstance(decision, Deny)
    assert "alerts@mybank.com" in decision.reason
    assert isinstance(policy.check(_unsub("deals@shop.com"), CTX), Allow)


def test_sender_denylist_blocks_whole_domain() -> None:
    policy = _denylist(["@mybank.com"])
    assert isinstance(policy.check(_unsub("marketing@mybank.com"), CTX), Deny)
    assert isinstance(policy.check(_unsub("anyone@other.com"), CTX), Allow)


def test_sender_denylist_blocks_subdomains() -> None:
    # The inverse of email_only_to: a denylist that misses a subdomain fails
    # open, and bulk senders routinely mail from one.
    policy = _denylist(["@mybank.com"])
    assert isinstance(policy.check(_unsub("deals@mail.mybank.com"), CTX), Deny)
    assert isinstance(policy.check(_unsub("x@a.b.mybank.com"), CTX), Deny)


def test_sender_denylist_does_not_match_lookalike_domains() -> None:
    policy = _denylist(["@mybank.com"])
    # Neither a suffix trick nor a prefix trick should match.
    assert isinstance(policy.check(_unsub("x@notmybank.com"), CTX), Allow)
    assert isinstance(policy.check(_unsub("x@mybank.com.evil.net"), CTX), Allow)


def test_sender_denylist_match_is_case_insensitive() -> None:
    policy = _denylist(["@MyBank.com"])
    assert isinstance(policy.check(_unsub("DEALS@MYBANK.COM"), CTX), Deny)


def test_sender_denylist_checks_every_sender_argument() -> None:
    policy = _denylist(["@mybank.com"])
    call = PolicyCall(tool="unsubscribe", arguments={"from": "x@mybank.com"})
    assert isinstance(policy.check(call, CTX), Deny)


def test_sender_denylist_checks_lists_of_senders() -> None:
    policy = _denylist(["@mybank.com"])
    call = PolicyCall(
        tool="unsubscribe",
        arguments={"sender": ["ok@shop.com", "alerts@mybank.com"]},
    )
    assert isinstance(policy.check(call, CTX), Deny)


def test_sender_denylist_not_applicable_without_a_sender() -> None:
    # Policies run against every proposed call; one with no sender argument is
    # not this policy's concern.
    policy = _denylist(["@mybank.com"])
    assert isinstance(policy.check(PolicyCall(tool="read_inbox"), CTX), Allow)


def test_sender_denylist_empty_config_allows_everything() -> None:
    policy = _denylist([])
    assert isinstance(policy.check(_unsub("anyone@anywhere.com"), CTX), Allow)


def test_sender_denylist_bare_list_shorthand() -> None:
    # The agent-file form `sender_denylist: ["@mybank.com"]`.
    config = SenderDenylistConfig.model_validate(["@mybank.com"])
    assert config.deny == ["@mybank.com"]


def test_sender_denylist_passes_conformance() -> None:
    run_policy_conformance(
        SenderDenylist,
        config={"deny": ["@mybank.com"]},
        sample_call=_unsub("deals@shop.com"),
        deny_call=_unsub("alerts@mybank.com"),
    ).assert_passed()


# --- all four are discoverable from their entry points ------------------------


def test_builtin_policies_are_discoverable() -> None:
    names = set(PolicyRegistry.discover().names())
    assert {
        "email_only_to",
        "paths_within",
        "sender_denylist",
        "spend_limit",
    } <= names
