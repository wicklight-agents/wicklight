"""In-memory mock tools backed by a seeded MockWorld.

For tests, examples, and later the game: deterministic tools that never touch
the real world. A :class:`MockWorld` holds an inbox, files, sent mail, and a
payment ledger; it can be seeded from YAML so a scenario can plant content
(e.g. a poisoned email). The tools read and mutate that world, so a scenario
can assert on the resulting state. Every tool passes the tool conformance kit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from ruamel.yaml import YAML

from wicklight.contracts import Tool, ToolContext, ToolResult, ToolRisk


class Email(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str
    subject: str = ""
    body: str = ""


class SentEmail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str
    subject: str = ""
    body: str = ""


class Payment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payee: str
    amount_usd: float
    memo: str = ""


class MockWorld(BaseModel):
    """Seedable in-memory state the mock tools read and mutate."""

    model_config = ConfigDict(extra="forbid")

    inbox: list[Email] = []
    files: dict[str, str] = {}
    sent: list[SentEmail] = []
    ledger: list[Payment] = []

    @classmethod
    def from_yaml(cls, text: str) -> MockWorld:
        yaml: Any = YAML(typ="safe")
        return cls.model_validate(yaml.load(text) or {})


# --- tool input schemas -------------------------------------------------------


class ReadInboxInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SendEmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str
    subject: str = ""
    body: str = ""


class PathInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str


class MakePaymentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payee: str
    amount_usd: float
    memo: str = ""


# --- tools --------------------------------------------------------------------


class _MockTool:
    """Shared base: holds the world and declares no network or sensitivity."""

    def __init__(self, world: MockWorld) -> None:
        self._world = world
        self.network_hosts: list[str] = []

    def is_sensitive(self, tool_input: BaseModel) -> bool:
        return False


class ReadInbox(_MockTool):
    name = "read_inbox"
    description = "Read the messages in the inbox."
    risk = ToolRisk.READ
    input_model = ReadInboxInput

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        if not self._world.inbox:
            return ToolResult.success("(inbox empty)")
        rendered = "\n\n".join(
            f"From {email.sender}: {email.subject}\n{email.body}"
            for email in self._world.inbox
        )
        return ToolResult.success(rendered)


class SendEmail(_MockTool):
    name = "send_email"
    description = "Send an email (recorded, never actually sent)."
    risk = ToolRisk.WRITE
    input_model = SendEmailInput

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(tool_input, SendEmailInput)
        self._world.sent.append(
            SentEmail(
                to=tool_input.to, subject=tool_input.subject, body=tool_input.body
            )
        )
        return ToolResult.success(f"email queued to {tool_input.to}")


class ReadFile(_MockTool):
    name = "read_file"
    description = "Read a file's contents."
    risk = ToolRisk.READ
    input_model = PathInput

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(tool_input, PathInput)
        content = self._world.files.get(tool_input.path)
        if content is None:
            return ToolResult.failure(f"no such file: {tool_input.path}")
        return ToolResult.success(content)


class DeleteFile(_MockTool):
    name = "delete_file"
    description = "Delete a file (cannot be undone)."
    risk = ToolRisk.IRREVERSIBLE
    input_model = PathInput

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(tool_input, PathInput)
        if tool_input.path not in self._world.files:
            return ToolResult.failure(f"no such file: {tool_input.path}")
        del self._world.files[tool_input.path]
        return ToolResult.success(f"deleted {tool_input.path}")


class MakePayment(_MockTool):
    name = "make_payment"
    description = "Pay an invoice (recorded to a ledger; cannot be undone)."
    risk = ToolRisk.IRREVERSIBLE
    input_model = MakePaymentInput

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(tool_input, MakePaymentInput)
        self._world.ledger.append(
            Payment(
                payee=tool_input.payee,
                amount_usd=tool_input.amount_usd,
                memo=tool_input.memo,
            )
        )
        return ToolResult.success(
            f"paid ${tool_input.amount_usd:.2f} to {tool_input.payee}"
        )


def mock_tools(world: MockWorld) -> dict[str, Tool]:
    """Build all mock tools bound to ``world``, keyed by tool name."""
    tools: list[Tool] = [
        ReadInbox(world),
        SendEmail(world),
        ReadFile(world),
        DeleteFile(world),
        MakePayment(world),
    ]
    return {tool.name: tool for tool in tools}
