"""Sender denylist: never act on mail from these senders.

The inverse of :mod:`wicklight.policies.email_only_to`. Where that policy asks
"is this recipient on the allowlist?", this one asks "is this *sender* on the
denylist?" — for tools that act on a message the agent did not choose, such as
unsubscribing from a mailing list.

Applies to any tool call carrying a sender argument (``sender``, ``from``,
``from_address``, or ``from_addr``). An entry starting with ``@`` matches a
whole domain **and its subdomains** (case-insensitive); any other entry is an
exact address match. A call to a tool with no sender argument is not this
policy's concern and is allowed.

    policies:
      - sender_denylist: ["@mybank.com", "alerts@myairline.com"]

**Why subdomains match here but not in ``email_only_to``.** For an allowlist,
refusing to match ``x@mail.acme.com`` against ``@acme.com`` fails closed — the
call is blocked, which is the safe direction. For a denylist the same rule
fails *open*: ``@mybank.com`` would not stop ``deals@mail.mybank.com``, and bulk
senders routinely mail from a subdomain. So a domain entry here matches the
domain itself and anything beneath it.

**What this policy cannot do.** It allows any call that carries no sender
argument, because policies run against *every* proposed call and must not block
unrelated tools. A tool that acts on a message therefore has to take the sender
as an argument for this policy to protect it — if the sender is resolved inside
the tool, there is nothing here to check.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar, cast

from pydantic import BaseModel, ConfigDict, model_validator

from wicklight.contracts.policy import (
    ALLOW,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    deny,
)

_DEFAULT_SENDER_ARGS = ("sender", "from", "from_address", "from_addr")


class SenderDenylistConfig(BaseModel):
    """Denied senders, and which arguments carry a sender."""

    model_config = ConfigDict(extra="forbid")

    deny: list[str] = []
    sender_args: list[str] = list(_DEFAULT_SENDER_ARGS)

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, data: Any) -> Any:
        # Agent-file shorthand: `sender_denylist: ["@bank.com"]` -> {"deny": [...]}.
        if isinstance(data, list):
            return {"deny": cast("list[Any]", data)}
        return data


class SenderDenylist:
    """Deny calls whose sender is on the denylist."""

    name: ClassVar[str] = "sender_denylist"
    config_model: ClassVar[type[BaseModel]] = SenderDenylistConfig

    def __init__(self, config: SenderDenylistConfig) -> None:
        self._deny = [entry.lower() for entry in config.deny]
        self._sender_args = config.sender_args

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        for sender in self._senders(call.arguments):
            entry = self._matching_entry(sender)
            if entry is not None:
                return deny(
                    f"{call.tool} from {sender} is blocked; {entry} is on the "
                    f"sender denylist"
                )
        return ALLOW  # no sender argument, or no sender on the denylist

    def _senders(self, arguments: Mapping[str, Any]) -> Iterable[str]:
        for key in self._sender_args:
            value = arguments.get(key)
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in cast("list[Any]", value):
                    if isinstance(item, str):
                        yield item

    def _matching_entry(self, sender: str) -> str | None:
        """The denylist entry this sender matches, or ``None``."""
        target = sender.lower().strip()
        for entry in self._deny:
            if entry.startswith("@"):
                domain = entry[1:]
                _, _, sender_domain = target.rpartition("@")
                if sender_domain == domain or sender_domain.endswith("." + domain):
                    return entry
            elif target == entry:
                return entry
        return None
