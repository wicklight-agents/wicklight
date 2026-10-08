"""Reference tool plugins implementing the Tool contract.

Each tool is a named action with a typed input schema and a declared risk
level (read, write, irreversible). The harness applies permission checks,
approval gates, and untrusted tagging of results around every call.

The mock tools and ``MockWorld`` provide deterministic, in-memory tools for
tests, examples, and the game.
"""

from __future__ import annotations

from wicklight.tools.mock import (
    DeleteFile,
    Email,
    MakePayment,
    MockWorld,
    Payment,
    ReadFile,
    ReadInbox,
    SendEmail,
    SentEmail,
    mock_tools,
)

__all__ = [
    "DeleteFile",
    "Email",
    "MakePayment",
    "MockWorld",
    "Payment",
    "ReadFile",
    "ReadInbox",
    "SendEmail",
    "SentEmail",
    "mock_tools",
]
