"""Replay a past run against a changed agent file (DTN-238).

The "would my fix have caught it?" workflow. Given an original trace and a new
agent file, re-check each tool call the model made — using the recorded model
decisions, no model and no tool execution — against the new file's permissions,
policies, and approval rules. Report the first step whose outcome changed and
stop there, because every later model decision in the original run depended on
the old result.

The evaluation reuses the same primitives the core loop uses: the effective
config's permission level, the configured policies' ``check``, and the config's
approval requirement — so a counterfactual outcome matches what a real run under
the new file would decide at the check stage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from wicklight.agentfile import (
    PermissionLevel,
    build_effective_config,
    parse_and_validate,
)
from wicklight.agentfile.config import EffectiveConfig
from wicklight.contracts import (
    Deny,
    PolicyCall,
    PolicyContext,
    PolicyRegistry,
)
from wicklight.core import ConfiguredPolicy
from wicklight.core.loop import TraceLog
from wicklight.trace import (
    RunFinished,
    RunFinishedPayload,
    RunStarted,
    RunStartedPayload,
    RunStatus,
    ToolProposed,
    TraceWriter,
)
from wicklight.trace.events import Decision, PolicyChecked, PolicyCheckedPayload
from wicklight.trace.reader import Trace, read_trace

# Amount-carrying argument names, for feeding spend policies a running total
# (mirrors the loop's spend tracking).
_AMOUNT_ARGS = ("amount_usd", "amount", "usd")


@dataclass(frozen=True)
class Outcome:
    """Whether a tool call would run, and if not, what stopped it."""

    allowed: bool
    by: str | None = None  # the check/policy name when not allowed
    reason: str | None = None

    def describe(self) -> str:
        if self.allowed:
            return "allowed"
        return f"blocked by {self.by}" if self.by else "blocked"


@dataclass(frozen=True)
class Divergence:
    step: int
    tool: str
    arguments: dict[str, Any]
    original: Outcome
    counterfactual: Outcome

    def describe(self) -> str:
        return (
            f"step {self.step}: {self.tool} was {self.original.describe()}, "
            f"now {self.counterfactual.describe()}"
        )


@dataclass(frozen=True)
class CounterfactualResult:
    divergence: Divergence | None
    evaluated_steps: int
    trace_path: Path | None


def counterfactual_replay(
    original: str | Trace,
    new_agent_path: str | Path,
    *,
    runs_dir: str | Path = "runs",
    run_id: str | None = None,
) -> CounterfactualResult:
    """Re-check a run's recorded tool calls against a new agent file."""
    trace = original if isinstance(original, Trace) else read_trace(original)
    new_agent_path = Path(new_agent_path)
    config, policies = _load(new_agent_path)
    agent_dir = new_agent_path.parent
    run_id = run_id or f"cf_{uuid4().hex[:12]}"

    with TraceWriter(run_id, root=runs_dir) as writer:
        log = TraceLog(writer, run_id)
        log.emit(
            RunStarted,
            0,
            f"counterfactual replay against {new_agent_path.name}",
            RunStartedPayload(agent=config.name.value, counterfactual=True),
        )

        spent_usd = 0.0
        evaluated = 0
        divergence: Divergence | None = None
        for event in trace.events:
            if not isinstance(event, ToolProposed):
                continue
            evaluated += 1
            name = event.payload.tool
            arguments = dict(event.payload.arguments)
            original_outcome = _original_outcome(trace, event.step, name)
            new_outcome = _new_outcome(
                name, arguments, config, policies, spent_usd, agent_dir
            )
            _emit_outcome(log, event.step, name, new_outcome)

            if _changed(original_outcome, new_outcome):
                divergence = Divergence(
                    step=event.step,
                    tool=name,
                    arguments=arguments,
                    original=original_outcome,
                    counterfactual=new_outcome,
                )
                log.emit(
                    RunFinished,
                    event.step,
                    f"stopped at the first changed outcome: {divergence.describe()} "
                    f"(later model decisions depended on the old result)",
                    RunFinishedPayload(status=RunStatus.STOPPED, steps=event.step),
                )
                break
            if new_outcome.allowed:
                spent_usd += _amount(arguments)
        else:
            log.emit(
                RunFinished,
                0,
                "counterfactual replay finished: no outcomes changed",
                RunFinishedPayload(status=RunStatus.COMPLETED, steps=evaluated),
            )

        return CounterfactualResult(
            divergence=divergence,
            evaluated_steps=evaluated,
            trace_path=writer.path,
        )


def _load(path: Path) -> tuple[EffectiveConfig, list[ConfiguredPolicy]]:
    agent_file, agent_config = parse_and_validate(
        path.read_text(encoding="utf-8"), path=path
    )
    config = build_effective_config(agent_config, provided=agent_file.frontmatter)
    registry = PolicyRegistry.discover()
    policies: list[ConfiguredPolicy] = []
    for entry in config.policies.value:
        for policy_name, policy_config in entry.items():
            policies.append(
                ConfiguredPolicy(
                    name=policy_name,
                    policy=registry.create(policy_name, policy_config),
                )
            )
    return config, policies


def _original_outcome(trace: Trace, step: int, tool: str) -> Outcome:
    """What the original run did with this call: ran (allowed) or was blocked."""
    for event in trace.by_step(step):
        if (
            event.type == "tool_executed"
            and event.payload.tool == tool
            and event.payload.ok
        ):
            return Outcome(allowed=True)
    for event in trace.by_step(step):
        if (
            event.type == "policy_checked"
            and event.payload.tool == tool
            and event.payload.decision is Decision.DENY
        ):
            return Outcome(False, by=event.payload.policy, reason=event.payload.reason)
        if event.type == "approval_resolved" and not event.payload.approved:
            return Outcome(False, by="approval", reason=event.payload.note)
    return Outcome(False, by="unknown")


def _new_outcome(
    tool: str,
    arguments: dict[str, Any],
    config: EffectiveConfig,
    policies: list[ConfiguredPolicy],
    spent_usd: float,
    agent_dir: Path,
) -> Outcome:
    """What the new agent file would decide for this call, at the check stage."""
    if config.tool_level(tool) is PermissionLevel.OFF:
        return Outcome(
            False, by="permissions", reason=f"tool {tool!r} is not permitted"
        )

    pcall = PolicyCall(tool=tool, arguments=arguments)
    pctx = PolicyContext(spent_usd=spent_usd, agent_dir=agent_dir)
    for configured in policies:
        decision = configured.policy.check(pcall, pctx)
        if isinstance(decision, Deny):
            return Outcome(False, by=configured.name, reason=decision.reason)

    if config.requires_approval(tool):
        return Outcome(False, by="approval", reason="now requires approval")
    return Outcome(allowed=True)


def _changed(original: Outcome, new: Outcome) -> bool:
    return original.allowed != new.allowed or original.by != new.by


def _emit_outcome(log: TraceLog, step: int, tool: str, outcome: Outcome) -> None:
    if outcome.allowed:
        log.emit(
            PolicyChecked,
            step,
            f"allowed: {tool} (unchanged under the new agent file)",
            PolicyCheckedPayload(
                tool=tool, policy="counterfactual", decision=Decision.ALLOW
            ),
        )
    else:
        log.emit(
            PolicyChecked,
            step,
            f"blocked: {tool} by {outcome.by}"
            + (f" — {outcome.reason}" if outcome.reason else ""),
            PolicyCheckedPayload(
                tool=tool,
                policy=outcome.by or "counterfactual",
                decision=Decision.DENY,
                reason=outcome.reason,
            ),
        )


def _amount(arguments: dict[str, Any]) -> float:
    for key in _AMOUNT_ARGS:
        value = arguments.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return 0.0
