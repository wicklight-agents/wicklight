"""The fixed core agent loop.

This is the only place tool calls happen, so safety checks can never be
skipped. The loop is deliberately small and readable; see ``docs/the-loop.md``
for a line-by-line walk-through.

    build context -> call model -> for each tool call: check, then execute
    -> record result -> repeat until the model finishes or the run stops

Every step is written to the trace. Tool errors come back to the model as
structured results; a harness error (such as a provider failure) stops the run
with an ``error`` event.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError

from wicklight.agentfile import AgentFile, PermissionLevel
from wicklight.agentfile.config import EffectiveConfig
from wicklight.contracts import (
    Message,
    ModelRequest,
    ModelResponse,
    Provider,
    ProviderError,
    Role,
    Tool,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolResult,
    ToolRisk,
    Usage,
)
from wicklight.trace import (
    ContextBuilt,
    ContextBuiltPayload,
    Decision,
    ErrorEvent,
    ErrorPayload,
    LimitHit,
    LimitHitPayload,
    ModelCalled,
    ModelCalledPayload,
    ModelResponded,
    ModelRespondedPayload,
    ModelRouted,
    ModelRoutedPayload,
    PolicyChecked,
    PolicyCheckedPayload,
    RunFinished,
    RunFinishedPayload,
    RunStarted,
    RunStartedPayload,
    RunStatus,
    ToolExecuted,
    ToolExecutedPayload,
    ToolProposed,
    ToolProposedPayload,
    TraceEvent,
    TraceWriter,
)

# Permission levels and tool risks share this ordering (off < read < write <
# irreversible). A call is allowed only when the granted level is at least the
# tool's declared risk.
_LEVEL_RANK = {
    PermissionLevel.OFF: 0,
    PermissionLevel.READ: 1,
    PermissionLevel.WRITE: 2,
    PermissionLevel.IRREVERSIBLE: 3,
}
_RISK_RANK = {
    ToolRisk.READ: 1,
    ToolRisk.WRITE: 2,
    ToolRisk.IRREVERSIBLE: 3,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TraceLog:
    """Writes trace events, stamping each with the run id and a timestamp.

    Routing all events through here keeps trace writing fixed in the core: the
    loop and its checks record events, nothing writes the file directly.
    """

    def __init__(self, writer: TraceWriter, run_id: str) -> None:
        self._writer = writer
        self.run_id = run_id

    def emit(
        self,
        event_type: Callable[..., TraceEvent],
        step: int,
        explain: str,
        payload: BaseModel,
    ) -> None:
        event = event_type(
            run_id=self.run_id,
            step=step,
            timestamp=_now(),
            explain=explain,
            payload=payload,
        )
        self._writer.write_event(event)


@dataclass(frozen=True)
class CheckOutcome:
    """A check's verdict on a proposed tool call."""

    allowed: bool
    reason: str = ""


@dataclass(frozen=True)
class ProposedCall:
    """A tool call the model proposed, with everything a check needs."""

    call: ToolCall
    tool: Tool
    tool_input: BaseModel
    step: int
    config: EffectiveConfig
    log: TraceLog


#: A check inspects a proposed call, may emit trace events, and allows or denies.
#: Later milestones supply permission, limit, policy, and approval checks.
ToolCheck = Callable[[ProposedCall], Awaitable[CheckOutcome]]


@dataclass(frozen=True)
class RunResult:
    """The outcome of a run."""

    run_id: str
    status: RunStatus
    steps: int
    output: str
    usage: Usage


async def run_agent(
    *,
    run_id: str,
    instructions: str,
    task: str,
    config: EffectiveConfig,
    provider: Provider,
    tools: Mapping[str, Tool],
    writer: TraceWriter,
    checks: Sequence[ToolCheck] = (),
    ctx: ToolContext | None = None,
    agent_file: AgentFile | None = None,
) -> RunResult:
    """Run an agent to completion, recording every step to the trace."""
    log = TraceLog(writer, run_id)
    ctx = ctx if ctx is not None else ToolContext(run_id=run_id)
    model_id = config.models.default.value
    max_steps = config.limits.max_steps.value
    max_cost = config.limits.max_cost.value
    timeout = config.limits.timeout.value
    tool_defs = _tool_definitions(tools)
    started = time.perf_counter()

    log.emit(
        RunStarted,
        0,
        f"run started for agent {config.name.value}",
        RunStartedPayload(agent=config.name.value),
    )

    history: list[Message] = []
    usage = Usage()
    output = ""
    status = RunStatus.COMPLETED
    step = 0

    while True:
        step += 1
        # Limits are fixed in the core and checked every step. Any one stops the
        # run cleanly with a limit_hit event.
        elapsed = time.perf_counter() - started
        if elapsed > timeout:
            log.emit(
                LimitHit,
                step,
                f"hit limit timeout ({timeout:g}s)",
                LimitHitPayload(limit="timeout", limit_value=timeout, observed=elapsed),
            )
            status = RunStatus.LIMIT
            break
        if step > max_steps:
            log.emit(
                LimitHit,
                step,
                f"hit limit max_steps ({max_steps})",
                LimitHitPayload(
                    limit="max_steps", limit_value=max_steps, observed=step
                ),
            )
            status = RunStatus.LIMIT
            break

        # 1. Build context: instructions, the task, then the conversation so far.
        messages = [
            Message(role=Role.SYSTEM, content=instructions),
            Message(role=Role.USER, content=task),
            *history,
        ]
        log.emit(
            ContextBuilt,
            step,
            f"built context with {len(messages)} messages",
            ContextBuiltPayload(message_count=len(messages)),
        )

        # 2. Route to a model and call it through the provider.
        log.emit(
            ModelRouted,
            step,
            f"routed to {model_id}",
            ModelRoutedPayload(model=model_id),
        )
        log.emit(
            ModelCalled, step, f"called {model_id}", ModelCalledPayload(model=model_id)
        )
        try:
            response = await provider.complete(
                ModelRequest(model=model_id, messages=messages, tools=tool_defs)
            )
        except ProviderError as exc:
            # A harness error stops the run.
            log.emit(
                ErrorEvent,
                step,
                f"error: {exc}",
                ErrorPayload(message=str(exc), where="model_called"),
            )
            status = RunStatus.ERROR
            break

        usage = _add_usage(usage, response.usage)
        log.emit(
            ModelResponded,
            step,
            _responded_explain(response),
            _responded_payload(model_id, response),
        )

        if usage.cost_usd is not None and usage.cost_usd > max_cost:
            log.emit(
                LimitHit,
                step,
                f"hit limit max_cost (${max_cost:.2f})",
                LimitHitPayload(
                    limit="max_cost", limit_value=max_cost, observed=usage.cost_usd
                ),
            )
            status = RunStatus.LIMIT
            break

        # The model's turn is part of the history either way.
        history.append(Message(role=Role.ASSISTANT, content=response.content))

        # 4. If the model asked for no tools, it has finished.
        if not response.tool_calls:
            output = response.content
            status = RunStatus.COMPLETED
            break

        # 3. For each proposed tool call: check, then execute, then record.
        for call in response.tool_calls:
            log.emit(
                ToolProposed,
                step,
                f"model proposed {call.name}",
                ToolProposedPayload(
                    tool=call.name, call_id=call.id, arguments=call.arguments
                ),
            )
            result = await _handle_call(
                call, tools, checks, config, ctx, log, step, agent_file
            )
            history.append(
                Message(
                    role=Role.TOOL,
                    content=result.output if result.ok else (result.error or ""),
                    tool_call_id=call.id,
                    name=call.name,
                    trusted=False,
                )
            )

    log.emit(
        RunFinished,
        step,
        f"run finished: {status.value} in {step} steps",
        RunFinishedPayload(status=status, steps=step, cost_usd=usage.cost_usd),
    )
    return RunResult(
        run_id=run_id, status=status, steps=step, output=output, usage=usage
    )


async def _handle_call(
    call: ToolCall,
    tools: Mapping[str, Tool],
    checks: Sequence[ToolCheck],
    config: EffectiveConfig,
    ctx: ToolContext,
    log: TraceLog,
    step: int,
    agent_file: AgentFile | None,
) -> ToolResult:
    # The permission check is fixed in the core and always runs first; plugin
    # checks cannot remove or reorder it.
    permission = _check_permission(call, tools, config, agent_file, log, step)
    if not permission.allowed:
        return ToolResult.failure(f"blocked: {permission.reason}")
    tool = tools[call.name]  # the permission check confirmed it is present

    try:
        tool_input = tool.input_model.model_validate(call.arguments)
    except ValidationError as exc:
        detail = exc.errors()[0]["msg"]
        return _failed(log, step, call, f"invalid arguments for {call.name}: {detail}")

    # Then any plugin checks (policies in M6, approvals in M7). A denied call is
    # never executed; the check records why in the trace.
    proposed = ProposedCall(call, tool, tool_input, step, config, log)
    for check in checks:
        outcome = await check(proposed)
        if not outcome.allowed:
            return ToolResult.failure(f"blocked: {outcome.reason}")

    # Execute the tool and record the result.
    start = time.perf_counter()
    try:
        result = await tool.run(tool_input, ctx)
    except Exception as exc:  # noqa: BLE001 - a tool bug is surfaced to the model, not raised
        result = ToolResult.failure(f"tool {call.name} raised: {exc}")
    duration_ms = (time.perf_counter() - start) * 1000
    log.emit(
        ToolExecuted,
        step,
        _executed_explain(call.name, result, duration_ms),
        ToolExecutedPayload(
            tool=call.name, call_id=call.id, ok=result.ok, duration_ms=duration_ms
        ),
    )
    return result


def _failed(log: TraceLog, step: int, call: ToolCall, error: str) -> ToolResult:
    log.emit(
        ToolExecuted,
        step,
        f"blocked: {error}",
        ToolExecutedPayload(tool=call.name, call_id=call.id, ok=False),
    )
    return ToolResult.failure(error)


def _check_permission(
    call: ToolCall,
    tools: Mapping[str, Tool],
    config: EffectiveConfig,
    agent_file: AgentFile | None,
    log: TraceLog,
    step: int,
) -> CheckOutcome:
    """The fixed permission check: tools are off unless granted a high enough level."""
    source = _permission_source(agent_file, call.name)
    granted = config.tools.get(call.name)
    if granted is None:
        reason = f"tool '{call.name}' is not listed in the agent file (tools are off)"
        return _deny(log, step, call, reason, source)

    level = granted.level.value
    if level is PermissionLevel.OFF:
        return _deny(log, step, call, f"tool '{call.name}' is turned off", source)

    tool = tools.get(call.name)
    if tool is None:
        return _deny(log, step, call, f"unknown tool '{call.name}'", source)

    if _RISK_RANK[tool.risk] > _LEVEL_RANK[level]:
        reason = (
            f"tool '{call.name}' needs '{tool.risk.value}' but is granted "
            f"'{level.value}'"
        )
        return _deny(log, step, call, reason, source)

    return CheckOutcome(allowed=True)


def _deny(
    log: TraceLog, step: int, call: ToolCall, reason: str, source: str | None
) -> CheckOutcome:
    log.emit(
        PolicyChecked,
        step,
        f"blocked: {call.name} by permissions — {reason}",
        PolicyCheckedPayload(
            tool=call.name,
            policy="permission",
            decision=Decision.DENY,
            reason=reason,
            source=source,
        ),
    )
    return CheckOutcome(allowed=False, reason=reason)


def _permission_source(agent_file: AgentFile | None, tool_name: str) -> str | None:
    if agent_file is None:
        return None
    line = agent_file.line_of("tools", tool_name)
    if line is None:
        return None
    filename = agent_file.path.name if agent_file.path else "agent.md"
    return f"{filename} line {line}"


def _tool_definitions(tools: Mapping[str, Tool]) -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name=tool.name,
            description=tool.description,
            parameters=tool.input_model.model_json_schema(),
        )
        for tool in tools.values()
    ]


def _add_usage(a: Usage, b: Usage) -> Usage:
    cost = (
        None
        if a.cost_usd is None and b.cost_usd is None
        else (a.cost_usd or 0.0) + (b.cost_usd or 0.0)
    )
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cost_usd=cost,
    )


def _responded_explain(response: ModelResponse) -> str:
    return (
        f"model responded ({response.stop_reason.value}) using "
        f"{response.usage.input_tokens} in / {response.usage.output_tokens} out tokens"
    )


def _responded_payload(model_id: str, response: ModelResponse) -> ModelRespondedPayload:
    return ModelRespondedPayload(
        model=model_id,
        finish_reason=response.stop_reason.value,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cost_usd=response.usage.cost_usd,
    )


def _executed_explain(name: str, result: ToolResult, duration_ms: float) -> str:
    verb = "executed" if result.ok else "failed"
    return f"{verb} {name} in {duration_ms:.0f}ms"
