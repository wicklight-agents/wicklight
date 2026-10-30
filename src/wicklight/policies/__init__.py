"""Reference policy plugins implementing the Policy contract.

A policy inspects a proposed tool call and returns allow or deny with a
reason. Every policy runs before every call; denials are logged with the rule
and its source line (e.g. recipient allowlists, spend limits).
"""

from __future__ import annotations

from wicklight.policies.block_tools import BlockTools, BlockToolsConfig
from wicklight.policies.email_only_to import EmailOnlyTo, EmailOnlyToConfig
from wicklight.policies.paths_within import PathsWithin, PathsWithinConfig
from wicklight.policies.sender_denylist import SenderDenylist, SenderDenylistConfig
from wicklight.policies.spend_limit import SpendLimit, SpendLimitConfig

__all__ = [
    "BlockTools",
    "BlockToolsConfig",
    "EmailOnlyTo",
    "EmailOnlyToConfig",
    "PathsWithin",
    "PathsWithinConfig",
    "SenderDenylist",
    "SenderDenylistConfig",
    "SpendLimit",
    "SpendLimitConfig",
]
