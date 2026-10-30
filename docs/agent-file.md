# Agent file reference

An agent file is YAML frontmatter (the rules the harness enforces) followed by a
Markdown body (the instructions the model may or may not follow):

```markdown
---
name: inbox-summarizer
models:
  default: anthropic/claude-sonnet
tools:
  read_inbox: read
  send_email: { level: write, approval: required }
policies:
  - email_only_to: ["@mycompany.com"]
limits:
  max_steps: 20
---
You summarize this week's emails and draft replies. Only send mail to
colleagues, and ask before sending anything.
```

`wicklight check <file>` validates the file and prints its **effective config**
— every value tagged `(from file)` or `(default)` — plus the API keys each model
needs and any capability/routing issues. Validation reports every problem in one
pass, each with the source line and a suggested fix. The machine-readable JSON
Schema is available from `wicklight.agentfile.agent_config_json_schema()`.

## Top-level fields

| Field | Required | Type | Meaning |
| --- | --- | --- | --- |
| `name` | **yes** | string | A name for the agent. |
| `models` | **yes** | mapping | The model(s) to call — see [Models](#models). |
| `tools` | no | mapping | The tools the agent may use — see [Tools](#tools). Default: none (every tool is `off`). |
| `policies` | no | list | Allow/deny [policies](policies.md) — see [Policies](#policies). Default: none. |
| `limits` | no | mapping | Run limits — see [Limits](#limits). All have safe defaults. |

Unknown keys are rejected (a typo is an error, not a silently ignored setting).

## Models

```yaml
models:
  default: anthropic/claude-sonnet      # required: provider/model
  routes:                               # optional, first match wins
    - when: { step: planning }
      use: anthropic/claude-opus
    - when: { data: sensitive }
      use: local/llama3.1
  fallback: [openai/gpt-4o, local/llama3.1]   # optional
```

| Field | Required | Meaning |
| --- | --- | --- |
| `default` | **yes** | The `provider/model` used when no route matches. |
| `routes` | no | A list of `{ when: <conditions>, use: provider/model }`, evaluated top to bottom; the first whose conditions all hold wins. |
| `fallback` | no | Models tried in order when the chosen model fails after its retries. |

A route's `when` is an AND of: `step` (`planning` or `execution`),
`context_tokens` (a comparison, e.g. `">100k"`), `cost_so_far` (e.g. `">0.5"`),
and `data` (`sensitive`). See [model routing](routing.md) for the full semantics
and enforced sensitivity routing.

## Tools

A tool is either a bare permission level or a mapping:

```yaml
tools:
  read_inbox: read
  send_email: { level: write, approval: required }
  purge_cache: { level: irreversible, waive_approval: true, reason: "idempotent cleanup" }
  read_file: { level: read, sensitive: true }
```

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `level` | **yes** | — | `off`, `read`, `write`, or `irreversible` (least to most dangerous). A tool not listed is `off`. |
| `approval` | no | `null` | `required` to gate the tool behind a human approver. Irreversible tools require approval by default. |
| `waive_approval` | no | `false` | Lift the approval an irreversible tool would otherwise require. **Must** carry a `reason`. |
| `reason` | no | `null` | The written reason for a waiver; shown by `check` and recorded in the trace. |
| `sensitive` | no | `false` | Mark the tool's output sensitive: reading one latches the run to sensitivity-allowed models. |

See the [safety model](safety-model.md) for how levels, approvals, and waivers
are enforced.

## Policies

A list of single-key mappings, `<policy-name>: <config>`, evaluated before every
tool call in the order written:

```yaml
policies:
  - email_only_to: ["@mycompany.com"]
  - paths_within: ["./docs"]
  - spend_limit: { max_usd: 100 }
  - sender_denylist: ["@mybank.com"]
```

Built-in policies and their config are documented in [policies](policies.md).
Unknown policy names are a validation error.

## Limits

```yaml
limits:
  max_steps: 20
  max_cost: 1.00
  timeout: 300
  max_retries: 2
  retry_backoff: 1.0
```

| Field | Default | Meaning |
| --- | --- | --- |
| `max_steps` | `20` | Maximum loop steps before the run stops with a `limit_hit`. |
| `max_cost` | `1.00` | Maximum estimated USD spent before stopping. |
| `timeout` | `300` | Maximum wall-clock seconds for the run. |
| `max_retries` | `2` | Retries for a retryable provider error before falling back. |
| `retry_backoff` | `1.0` | Base seconds between retries. |

## Errors

`check` reports every problem in one pass, each line-numbered with a fix:

```
broken.md line 3: unexpected key 'modles'. Did you mean 'models'?
broken.md line 6: tools.send_email.level: "writ" is not a valid level. Use one of: off, read, write, irreversible.
broken.md: 'models' is required.
```

It exits non-zero on any error (usable in CI) and zero when the file is valid.
