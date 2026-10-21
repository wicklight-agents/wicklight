# Routing in Wicklight

An agent file can send different model calls to different models — a bigger
model for planning, a local model for sensitive data, a large-context model when
the conversation grows (M10).

```yaml
models:
  default: anthropic/claude-sonnet
  routes:
    - when: { step: planning }        # the first model call
      use: anthropic/claude-opus
    - when: { context_tokens: ">100k" }
      use: google/gemini-pro
    - when: { data: sensitive }       # once sensitive content is in context
      use: local/llama
  fallback: [openai/gpt-5, local/llama]
```

## Conditions

A route's `when` is an **AND** of one or more conditions:

| Condition | Meaning |
| --- | --- |
| `step` | the step kind: `planning` (first model call) or `execution` (later) |
| `context_tokens` | a comparison on the estimated context size, e.g. `">100k"`, `">=50000"` |
| `cost_so_far` | a comparison on the dollars spent so far, e.g. `">0.5"` |
| `data` | `sensitive` — matches once sensitive content is in context (DTN-245) |

Unknown conditions, bad step values, or malformed comparisons are rejected at
`check` time with a line-numbered error.

## First match wins

Before each model call the router evaluates the routes top to bottom and uses
the first whose condition holds; if none match, the `default`. Every call is
preceded by a `model_routed` trace event naming the model, the matching rule,
and its agent-file line:

```
model_routed  routed to anthropic/claude-opus by rule 1 (step=planning) (agent.md line 6)
```

`wicklight check` prints the routes in evaluation order, verifies every
referenced model resolves to an installed provider, and warns when a route is
unreachable — shadowed by an earlier, broader rule that always matches first.

## Enforced sensitivity routing

"Never send this data to a hosted model" is a rule the harness enforces
(DTN-245). A tool whose output is sensitive is marked in the agent file:

```yaml
tools:
  read_file: { level: read, sensitive: true }
```

Once a sensitive tool result enters the context, the run **latches** into
sensitive mode for the rest of the run — even if that result is later truncated
out of context. From then on, only models **allowed for sensitive data** may be
called: the models targeted by a `when: { data: sensitive }` route.

Enforcement runs inside the router, not just as route preference:

- A matching route to a model that isn't sensitivity-allowed is **excluded** and
  recorded on the `model_routed` event, not followed.
- If no allowed model is available, the run **stops with an error** rather than
  leak — it never falls through to a hosted model.

`wicklight check` warns up front when an agent declares a sensitive tool but no
`data: sensitive` route, because such a run would stop as soon as it touched
that data.

(Tool output can also be marked sensitive at runtime via `ToolResult.sensitive`;
either source latches the run.)

## Fallbacks

When the chosen model fails after its retry policy (DTN-228), the harness tries
the `fallback` list in order (DTN-244):

```yaml
models:
  default: anthropic/claude-sonnet
  fallback: [openai/gpt-4o, local/llama3.1]
```

Each failure is a trace `error` event (`where: "fallback"`) naming the model
that failed, why, and which model is next — `model X failed (overloaded): …;
falling back to Y`. If every option fails, the run stops with a terminal error
listing what was tried and the last failure's reason.

Fallbacks never bypass sensitivity: in a sensitive run a fallback that isn't
allowed for sensitive data is **skipped** (and the skip is logged), never
called. If that leaves nothing allowed, the run stops rather than leak.
