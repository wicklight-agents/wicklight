"""Explain what the model saw at a step (DTN-239).

Given a recorded trace and a step, reconstruct the exact context the model was
given — system instructions, task, history, and tool results — from the request
blob recorded in that step (DTN-236). Untrusted content (tool results and the
model's own turns) is marked so a prompt injection stands out. It then shows
what happened next: the model's response, any proposed tool calls, and each
check's result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from wicklight.contracts import Message, ModelRequest, ModelResponse, Role
from wicklight.trace.console import render_event
from wicklight.trace.events import ModelCalled, ModelResponded, TraceEvent
from wicklight.trace.reader import Trace

# Events, in order, that make up "what happened next" after the model replied.
_OUTCOME_TYPES = (
    "model_responded",
    "tool_proposed",
    "policy_checked",
    "approval_requested",
    "approval_resolved",
    "tool_executed",
    "error",
    "limit_hit",
)


class ExplainError(Exception):
    """Raised when a step has no recorded model call to explain."""


@dataclass(frozen=True)
class Explanation:
    step: int
    model: str
    messages: list[Message]
    response: ModelResponse | None
    outcome: list[TraceEvent]


def explain_step(trace: Trace, step: int) -> Explanation:
    """Reconstruct what the model saw and did at ``step``."""
    called = [e for e in trace.events if isinstance(e, ModelCalled) and e.step == step]
    if not called:
        raise ExplainError(f"no model call was recorded at step {step}")
    request_ref = called[0].payload.request_ref
    if request_ref is None:
        raise ExplainError(
            f"step {step} has no recorded request; the run predates request "
            f"recording (DTN-236)"
        )
    request = ModelRequest.model_validate_json(trace.resolve_blob(request_ref))

    response: ModelResponse | None = None
    responded = [
        e for e in trace.events if isinstance(e, ModelResponded) and e.step == step
    ]
    if responded and responded[0].payload.response_ref is not None:
        response = ModelResponse.model_validate_json(
            trace.resolve_blob(responded[0].payload.response_ref)
        )

    outcome = [e for e in trace.by_step(step) if e.type in _OUTCOME_TYPES]
    return Explanation(
        step=step,
        model=request.model,
        messages=request.messages,
        response=response,
        outcome=outcome,
    )


def _untrusted_label(message: Message) -> str:
    if message.role is Role.TOOL:
        return f"untrusted · tool result from {message.name or 'a tool'}"
    return "untrusted · model turn"


def render_explanation(console: Console, explanation: Explanation) -> None:
    """Render an explanation: the context (untrusted boxed), then the outcome."""
    console.print(
        f"Step {explanation.step} — what the model saw ({explanation.model})",
        style="bold",
    )
    for message in explanation.messages:
        if message.trusted:
            console.print(Text(f"{message.role.value}:", style="bold green"))
            console.print(Text(message.content or "(empty)"))
        else:
            console.print(
                Panel(
                    message.content or "(empty)",
                    title=_untrusted_label(message),
                    border_style="red",
                )
            )

    console.print("\nWhat happened next", style="bold")
    if not explanation.outcome:
        console.print("(nothing recorded for this step)")
    for event in explanation.outcome:
        console.print(render_event(event))


def explanation_json(explanation: Explanation) -> dict[str, Any]:
    """A JSON-ready dict of the explanation, for ``--json``."""
    response = explanation.response
    return {
        "step": explanation.step,
        "model": explanation.model,
        "messages": [
            {
                "role": message.role.value,
                "trusted": message.trusted,
                "name": message.name,
                "content": message.content,
            }
            for message in explanation.messages
        ],
        "response": None
        if response is None
        else {
            "content": response.content,
            "tool_calls": [
                {"name": call.name, "arguments": call.arguments}
                for call in response.tool_calls
            ],
            "stop_reason": response.stop_reason.value,
        },
        "outcome": [
            {"type": event.type, "explain": event.explain}
            for event in explanation.outcome
        ],
    }
