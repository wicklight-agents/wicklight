# Neutral model types

These Pydantic types, in `wicklight.contracts`, are the harness's own
vocabulary for talking to models. A provider plugin translates between one
vendor's API and these types; the core and the trace only ever see the neutral
shapes. Every type round-trips to JSON, so a model request or response can be
stored in a trace (large ones go in the blob store).

They are part of the provider/tool/policy contract, versioned by
`wicklight.contracts.CONTRACT_VERSION` (currently `1.0`, semantic versioning;
the previous major is supported for six months after a new one ships).

## Messages

`Message` — one message in a conversation.

| Field | Type | Notes |
| --- | --- | --- |
| `role` | `Role` | `system`, `user`, `assistant`, or `tool` |
| `content` | string | defaults to `""` (an assistant turn may only call tools) |
| `trusted` | bool | `True` for the harness's own instructions; `False` for external data |
| `tool_call_id` | string? | for a tool-result message, the call it answers |
| `name` | string? | for a tool-result message, the tool's name |

The `trusted` flag is the heart of untrusted-content handling: tool results and
other external data are created with `trusted=False` and are never treated as
instructions by the core (enforced in M6).

## Tools

`ToolDefinition` — a tool offered to the model: `name`, `description`, and
`parameters` (a JSON Schema for the arguments).

`ToolCall` — a tool invocation the model requested: `id`, `name`, `arguments`.

## Requests and responses

`ModelRequest` — a neutral request: `model` (id), `messages`, `tools`,
`max_tokens`, `temperature`, `stop`.

`ModelResponse` — a neutral response: `content`, `tool_calls`, `stop_reason`
(`stop`, `tool_use`, `length`, or `error`), and `usage`.

`Usage` — `input_tokens`, `output_tokens`, and an optional `cost_usd`, plus a
`total_tokens` convenience.

## Streaming

`ModelEvent` is a discriminated union (on `type`) of the events a stream emits:

- `text_delta` (`TextDelta`) — a chunk of assistant text.
- `tool_call` (`ToolCallDelta`) — a fully-formed `ToolCall`.
- `done` (`StreamDone`) — the final event, carrying `stop_reason` and `usage`.

`parse_model_event` / `dump_model_event` convert a streaming event to and from a
JSON-ready dict, returning the right concrete type from the `type` discriminator.
