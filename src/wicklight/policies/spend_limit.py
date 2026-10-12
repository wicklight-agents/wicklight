"""Spend caps: limit how much a run can pay, per call and per run.

Applies to any tool call carrying a monetary amount argument (``amount_usd``,
``amount``, or ``usd``). ``per_call_usd`` caps a single payment; ``max_usd``
caps the running total, which the core loop accumulates across calls — so three
small payments that together exceed the cap are blocked (defeating split
payments). A call with no amount argument is not this policy's concern.

    policies:
      - spend_limit: { max_usd: 100, per_call_usd: 50 }
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from wicklight.contracts.policy import (
    ALLOW,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    deny,
)

_DEFAULT_AMOUNT_ARGS = ("amount_usd", "amount", "usd")


class SpendLimitConfig(BaseModel):
    """Per-call and per-run spend caps, and which arguments carry an amount."""

    model_config = ConfigDict(extra="forbid")

    max_usd: float | None = None
    per_call_usd: float | None = None
    amount_args: list[str] = list(_DEFAULT_AMOUNT_ARGS)


class SpendLimit:
    """Deny payments that breach the per-call or per-run spend cap."""

    name: ClassVar[str] = "spend_limit"
    config_model: ClassVar[type[BaseModel]] = SpendLimitConfig

    def __init__(self, config: SpendLimitConfig) -> None:
        self._max_usd = config.max_usd
        self._per_call_usd = config.per_call_usd
        self._amount_args = config.amount_args

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        amount = self._amount(call.arguments)
        if amount is None:
            return ALLOW  # no amount argument: not applicable

        if self._per_call_usd is not None and amount > self._per_call_usd:
            return deny(
                f"{call.tool} of ${amount:.2f} exceeds the per-call limit of "
                f"${self._per_call_usd:.2f}"
            )

        if self._max_usd is not None and ctx.spent_usd + amount > self._max_usd:
            return deny(
                f"{call.tool} of ${amount:.2f} would exceed the per-run limit of "
                f"${self._max_usd:.2f} (already spent ${ctx.spent_usd:.2f})"
            )
        return ALLOW

    def _amount(self, arguments: Mapping[str, Any]) -> float | None:
        for key in self._amount_args:
            value = arguments.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None
