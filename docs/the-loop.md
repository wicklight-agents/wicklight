# The loop

The core agent loop lives in `wicklight.core` (`src/wicklight/core/loop.py`).
It is intentionally small: it should read in one sitting, because it is the only
place tool calls happen, so every safety check lives on this one path.

```
build context -> call model -> for each tool call: check, then execute
-> record result -> repeat until the model finishes or the run stops
```

## `run_agent(...)`

The entry point is `run_agent`, which takes its dependencies explicitly (no
globals): a `run_id`, the agent's `instructions` and the user's `task`, the
`EffectiveConfig` (DTN-195), a resolved `provider` (DTN-205), the `tools` to
offer, a `TraceWriter` (DTN-200), an optional list of `checks`, and a
`ToolContext` carrying secrets. It returns a `RunResult` (status, steps, final
output, usage).

## Setup

- A `TraceLog` wraps the writer and stamps every event with the run id and a
  timestamp. **Everything** is written through it — the loop and its checks
  record events; nothing writes the trace file directly. That is how "nothing
  happens that isn't in the trace" is enforced.
- The model id comes from `config.models.default`, the step budget from
  `config.limits.max_steps`, and the tool definitions (name, description, JSON
  Schema) are built once from the offered tools.
- A `run_started` event is emitted at step 0.

## The loop body

Each iteration is one step:

1. **Limits.** Before anything else, the fixed limit checks run: wall-clock
   `timeout`, `max_steps`, and (after the model call) `max_cost` from the
   accumulated `Usage`. Hitting any one emits a `limit_hit` event and stops the
   run cleanly with status `limit`, so the loop always terminates. These are
   fixed in the core; a plugin cannot remove them.
2. **Build context** (`context_built`). The messages are the system
   instructions, the user's task, then the conversation so far (assistant turns
   and tool results). Tool results are tagged `trusted=False`.
3. **Route and call** (`model_routed`, `model_called`). The loop routes to the
   default model (first-match routing arrives in M10) and calls the provider's
   `complete`. If the provider raises a `ProviderError`, that is a **harness
   error**: emit an `error` event and stop with status `error`.
4. **Record the response** (`model_responded`): usage is accumulated and the
   assistant turn is appended to the history.
5. **Finish?** If the model proposed no tool calls, the run is done: capture its
   text as the output and stop with status `completed`.
6. **Otherwise, handle each proposed tool call** (`tool_proposed`), via
   `_handle_call`, and append the result to the history as a `tool` message so
   the model sees it on the next turn.

## `_handle_call(...)` — the one place tools run

1. **Permission check (fixed, always first).** A call is blocked if the tool is
   not listed in the agent file (tools are off unless listed), is listed as
   `off`, is unknown, or its declared risk exceeds the granted level
   (`off < read < write < irreversible`). A block emits a `policy_checked` deny
   with the reason and the agent-file line, and returns a failure to the model —
   the tool is **never executed**. Plugins cannot remove or reorder this check.
2. **Validate** the arguments against the tool's `input_model`. Invalid
   arguments are returned to the model as a structured failure.
3. **Plugin checks.** Any additional checks run in order (policies in M6,
   approvals in M7); the first denial blocks the call the same way. By default
   there are none.
4. **Execute** the tool and record `tool_executed` with its result and duration.
   If a tool misbehaves and raises, that is surfaced to the model as a failure
   rather than taking down the run.

## Errors, in two kinds

- **Tool errors** (unknown tool, bad arguments, a tool returning a failure, or a
  misbehaving tool) go back to the model as structured `ToolResult` failures, so
  it can recover. The run continues.
- **Harness errors** (a provider failure today) stop the run with an `error`
  event and status `error`.

## The end

Whatever the exit — completed, limit, or error — the loop emits a single
`run_finished` event with the final status, step count, and cost, and returns
the `RunResult`.
