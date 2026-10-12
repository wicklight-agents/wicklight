"""Recipient allowlist: mail may only go to approved addresses or domains.

Applies to any tool call carrying a recipient argument (``to``, ``recipient``,
``recipients``, or ``email``). An allowlist entry starting with ``@`` matches a
whole domain (case-insensitive); any other entry is an exact address match.
A call to a tool with no recipient argument is not this policy's concern and is
allowed.

    policies:
      - email_only_to: ["@acme.com", "ceo@partner.com"]
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

_DEFAULT_RECIPIENT_ARGS = ("to", "recipient", "recipients", "email")


class EmailOnlyToConfig(BaseModel):
    """Allowed recipients, and which arguments carry a recipient."""

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = []
    recipient_args: list[str] = list(_DEFAULT_RECIPIENT_ARGS)

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, data: Any) -> Any:
        # Agent-file shorthand: `email_only_to: ["@acme.com"]` -> {"allow": [...]}.
        if isinstance(data, list):
            return {"allow": cast("list[Any]", data)}
        return data


class EmailOnlyTo:
    """Deny recipients that are not on the allowlist."""

    name: ClassVar[str] = "email_only_to"
    config_model: ClassVar[type[BaseModel]] = EmailOnlyToConfig

    def __init__(self, config: EmailOnlyToConfig) -> None:
        self._allow = [entry.lower() for entry in config.allow]
        self._recipient_args = config.recipient_args

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        recipients = list(self._recipients(call.arguments))
        if not recipients:
            return ALLOW  # no recipient argument: not applicable
        for recipient in recipients:
            if not self._is_allowed(recipient):
                allowed = ", ".join(self._allow) or "(none)"
                return deny(
                    f"{call.tool} to {recipient} is not allowed; recipients must "
                    f"match one of: {allowed}"
                )
        return ALLOW

    def _recipients(self, arguments: Mapping[str, Any]) -> Iterable[str]:
        for key in self._recipient_args:
            value = arguments.get(key)
            if isinstance(value, str):
                yield value
            elif isinstance(value, list):
                for item in cast("list[Any]", value):
                    if isinstance(item, str):
                        yield item

    def _is_allowed(self, recipient: str) -> bool:
        target = recipient.lower()
        for entry in self._allow:
            if entry.startswith("@"):
                if target.endswith(entry):
                    return True
            elif target == entry:
                return True
        return False
