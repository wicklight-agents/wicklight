# Trace events

A run's trace is an append-only JSONL file: one event per line, in order. The
trace is the source of truth for everything the CLI and viewer show, so every
model call, routing decision, policy check, approval, and tool call is one
event. Plain JSONL means a beginner can read it, and it works with `grep` and
`jq`.

The models live in `wicklight.trace` (`src/wicklight/trace/events.py`).

## The envelope

Every event shares these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `v` | int | Trace format version (currently `1`). Written on every line so each line is self-describing. |
| `run_id` | string | Identifies the run this event belongs to. |
| `step` | int | The step number within the run. |
| `timestamp` | string (ISO-8601) | When the event occurred. |
| `type` | string | The event type — the discriminator a reader uses to parse `payload`. |
| `payload` | object | The type-specific body, described below. |
| `explain` | string | A human-readable sentence explaining the event. |

A reader parses the `type` field and deserializes `payload` into the matching
model (a discriminated union), so it always gets the right concrete type back.

Example line:

```json
{"v": 1, "run_id": "run_abc123", "step": 2, "timestamp": "2026-10-06T12:00:00Z", "type": "policy_checked", "payload": {"tool": "send_email", "policy": "email_only_to", "decision": "deny", "reason": "recipient not allowed", "source": "inbox.md line 9"}, "explain": "blocked: send_email by policy email_only_to (inbox.md line 9)"}
```

## Event types

Each section lists the payload fields and an example `explain`.

### `run_started`
A run has begun. **Payload:** `agent` (name), `agent_file` (path, optional).
*explain:* `run started for agent inbox-summarizer`

### `context_built`
The context (instructions plus history) was assembled for a step. **Payload:**
`message_count`, `content_ref` (hash of the full context in the blob store,
optional). *explain:* `built context with 4 messages`

### `model_routed`
The router chose a model and logged which rule matched. **Payload:** `model`,
`matched_rule` (optional). *explain:* `routed to anthropic/claude-opus by rule
step=planning`

### `model_called`
A model was called through a provider. **Payload:** `model`, `provider`
(optional), `request_ref` (blob hash, optional). *explain:* `called
anthropic/claude-opus`

### `model_responded`
The model returned a response. **Payload:** `model`, `finish_reason`,
`input_tokens`, `output_tokens`, `cost_usd`, `response_ref` (all optional).
*explain:* `model responded (stop) using 1200 in / 80 out tokens`

### `tool_proposed`
The model proposed a tool call. **Payload:** `tool`, `call_id` (optional),
`arguments` (object). *explain:* `model proposed send_email`

### `policy_checked`
A policy was evaluated against a proposed tool call. **Payload:** `tool`,
`policy`, `decision` (`allow` or `deny`), `reason` (optional), `source` (where
the rule came from, e.g. `inbox.md line 9`). *explain:* `blocked: send_email by
policy email_only_to (inbox.md line 9)`

### `approval_requested`
A tool call paused for human approval. **Payload:** `tool`, `call_id`
(optional), `reason` (optional). *explain:* `approval requested for send_email`

### `approval_resolved`
A human approved or rejected a pending call. **Payload:** `tool`, `call_id`
(optional), `approved` (bool), `by` (optional). *explain:* `approval granted for
send_email by user`

### `tool_executed`
A tool ran and its result was recorded. **Payload:** `tool`, `call_id`
(optional), `ok` (bool), `result_ref` (blob hash, optional), `duration_ms`
(optional). *explain:* `executed send_email in 42ms`

### `limit_hit`
A step, cost, or time limit was reached. **Payload:** `limit` (name),
`limit_value`, `observed`. *explain:* `hit limit max_steps (20)`

### `error`
Something went wrong. **Payload:** `message`, `where` (optional),
`recoverable` (bool). *explain:* `error: provider timeout while calling the
model`

### `run_finished`
The run ended. **Payload:** `status` (`completed`, `stopped`, `limit`, or
`error`), `steps`, `cost_usd` (optional). *explain:* `run finished: completed in
4 steps`

## Versioning

`v` is the trace format version. It starts at `1` and is bumped only when the
event schema changes in a way older readers cannot handle. Because `v` is on
every line, a reader can decide per line how to interpret it.
