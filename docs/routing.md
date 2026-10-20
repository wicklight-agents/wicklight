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

## Fallbacks and sensitivity

The `fallback` list and enforced sensitivity routing (a run that touches
sensitive data may only call sensitivity-allowed models) arrive in DTN-244 and
DTN-245.
