# API keys and trace redaction

Real provider adapters (M8) need credentials. Wicklight keeps them out of the
model's reach and out of every trace (DTN-227).

## Keys come from the environment, never the agent file

An agent file names a model like `anthropic/claude-sonnet`; the provider prefix
maps to a well-known environment variable:

| Provider | Variable |
| --- | --- |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |

Adapters read the key with `resolve_key(provider)`, which raises a clear error
naming the variable to set (never a value) when it is missing. A provider with
no key (`fake`, or a local OpenAI-compatible server) simply has no entry.

## `wicklight check` reports what's needed

`check` ends with an **api keys** section listing the variables the config's
models require and whether each is set — without printing any value:

```
api keys:
  ANTHROPIC_API_KEY: MISSING (for anthropic)
```

## Keys can never land in a trace

The trace writer runs a redactor over every line and blob before it touches
disk (`TraceWriter(redactor=...)`, DTN-200). The harness installs a redactor
(`trace_redactor()`) that removes:

- the exact value of every set API-key variable, and
- any key-shaped string (`sk-…`, `sk-ant-…`, `Bearer …`, …).

So even a provider error that echoes the key back — `upstream rejected key
sk-ant-…` — is written as `… REDACTED` in the JSONL. The patterns live in
`wicklight.redaction`, shared with the test-cassette scrubber (DTN-226) so one
definition protects both paths.
