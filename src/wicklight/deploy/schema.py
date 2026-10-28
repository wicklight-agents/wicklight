"""Pydantic v2 schema for the deploy file (``deploy.yaml``).

The deploy file is kept separate from the agent file so the same agent runs
unchanged everywhere; the deploy file only says *how* to run it: what triggers
it, which secrets it needs, where traces go, and any extra egress hosts. Unknown
keys are rejected (a typo should be an error, not a silently ignored setting).

    name: inbox-summarizer
    agent: agent.md
    triggers:
      - schedule: "0 8 * * 1-5"
      - webhook: { path: /run }
    secrets:
      EMAIL_TOKEN: { from: env }
    traces: ./runs
    egress:
      extra_hosts: []
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Forbid unknown keys everywhere, like the agent file.
_STRICT = ConfigDict(extra="forbid")


class WebhookConfig(BaseModel):
    """Where a webhook trigger is mounted."""

    model_config = _STRICT

    path: str = "/run"


class TriggerSpec(BaseModel):
    """One trigger: exactly one of a cron ``schedule`` or a ``webhook``.

    A single model (rather than a union of two) keeps the error for a bad
    trigger to one clear message instead of one per union branch.
    """

    model_config = _STRICT

    schedule: str | None = None
    webhook: WebhookConfig | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> TriggerSpec:
        kinds = [
            name
            for name, value in (("schedule", self.schedule), ("webhook", self.webhook))
            if value is not None
        ]
        if len(kinds) != 1:
            raise ValueError("a trigger must have exactly one of: schedule, webhook")
        # A standard cron expression has five whitespace-separated fields. Deeper
        # validation (ranges, step syntax) happens where the schedule is run.
        if self.schedule is not None and len(self.schedule.split()) != 5:
            raise ValueError(
                'schedule must be a 5-field cron expression, e.g. "0 8 * * 1-5"'
            )
        return self


class SecretSource(str, Enum):
    """Where a secret's value is resolved from on the host at start."""

    ENV = "env"
    FILE = "file"
    KEYCHAIN = "keychain"


class SecretSpec(BaseModel):
    """How to resolve one secret. Its value never appears here or in a trace."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: SecretSource = Field(alias="from")
    # Env var name or keychain item; defaults to the secret's key when omitted.
    name: str | None = None
    # Path to the secret file, for ``from: file``.
    path: str | None = None

    @model_validator(mode="after")
    def _source_consistent(self) -> SecretSpec:
        if self.source is SecretSource.FILE and not self.path:
            raise ValueError("a file secret needs a 'path'")
        if self.source is not SecretSource.FILE and self.path is not None:
            raise ValueError("'path' only applies to a file secret")
        return self


class Egress(BaseModel):
    """Network hosts the agent may reach beyond its model and tool hosts."""

    model_config = _STRICT

    extra_hosts: list[str] = []


class OverlapPolicy(str, Enum):
    """What to do when a trigger fires while a run is already in progress."""

    SKIP = "skip"  # drop the new trigger (the safe default)
    QUEUE = "queue"  # run it after the current one finishes
    ALLOW = "allow"  # run it concurrently


class DeployConfig(BaseModel):
    """A validated deploy file."""

    model_config = _STRICT

    name: str
    # Path to the agent file, relative to the deploy file.
    agent: str
    triggers: list[TriggerSpec] = []
    secrets: dict[str, SecretSpec] = {}
    traces: str = "./runs"
    egress: Egress = Egress()
    # What to do when a trigger fires mid-run (DTN-256).
    overlap: OverlapPolicy = OverlapPolicy.SKIP
