"""A minimal reference policy: deny a configured set of tools by name.

This is the smallest policy that exercises the whole contract — a typed config
schema, a deny with a reason, and a plain allow — and it is what the harness
discovers through the ``wicklight.policies`` entry point. The richer built-in
policies (recipient allowlist, path allowlist, spend limit) arrive in DTN-218.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from wicklight.contracts.policy import (
    ALLOW,
    PolicyCall,
    PolicyContext,
    PolicyDecision,
    deny,
)


class BlockToolsConfig(BaseModel):
    """Which tools this policy blocks, by name."""

    model_config = ConfigDict(extra="forbid")

    tools: list[str] = []


class BlockTools:
    """Deny any proposed call to a tool named in the configured block list."""

    name: ClassVar[str] = "block_tools"
    config_model: ClassVar[type[BaseModel]] = BlockToolsConfig

    def __init__(self, config: BlockToolsConfig) -> None:
        self._blocked = set(config.tools)

    def check(self, call: PolicyCall, ctx: PolicyContext) -> PolicyDecision:
        if call.tool in self._blocked:
            return deny(f"tool {call.tool!r} is blocked by the block_tools policy")
        return ALLOW
