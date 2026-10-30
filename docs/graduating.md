# Graduating

Wicklight is a learning harness. It favors clarity over power, and at some point
you may outgrow it — needing richer orchestration, a managed control plane, or a
team's existing observability stack. That is the intended path. The habits
Wicklight builds carry over, and its concepts map cleanly onto bigger tools.

## The habits worth keeping

- **Trace everything.** Treat every model call, tool call, and safety decision
  as an event you can inspect later. If a system can't tell you *why* it did
  something, that's a gap.
- **Least privilege by default.** Grant the smallest permission that works;
  make dangerous actions explicit and gated.
- **Separate rules from instructions.** Keep enforced policy out of the prompt,
  where the model can't argue with it.
- **Test on a fake first.** A deterministic replay of a scenario catches far
  more than a live run, and costs nothing.
- **Mark untrusted data as data.** Never let fetched content become
  instructions by accident.

## Concept map

| Wicklight | In a larger system |
| --- | --- |
| The fixed core loop | An agent framework's run loop / executor |
| Agent file (`agent.md`) | A declarative agent/graph config, or code wiring |
| Provider / tool / policy contracts | The framework's model, tool, and guardrail interfaces |
| Policies (allow/deny before a call) | Guardrails / policy engines (e.g. input/output filters, OPA-style rules) |
| Approvals & waivers | Human-in-the-loop / approval queues |
| JSONL trace + blob store | Spans and events in an observability backend |
| Replay / explain / dry-run | Offline evaluation, tracing replay, "what-if" tooling |
| The viewer | A trace UI (LangSmith, Phoenix, Jaeger, …) |
| `deploy.yaml` + sealed container | A deployment manifest + your container platform |
| Egress allowlist proxy | A network policy / service mesh egress rule |

## To OpenTelemetry

Wicklight's trace is deliberately close to the shape of
[OpenTelemetry](https://opentelemetry.io/): a run is a trace, each step is a
span, and each event (`model_called`, `policy_checked`, `tool_executed`, …) maps
to a span event with attributes. The envelope fields line up directly:

| Wicklight trace | OpenTelemetry |
| --- | --- |
| `run_id` | trace id |
| `step` | a span per step (child of the run span) |
| event `type` + `payload` | span event name + attributes |
| `model_responded` tokens / `cost_usd` | span attributes (`gen_ai.usage.*`) |
| `error` with `kind` | span status + exception event |

A thin exporter can map the JSONL trace onto OTel spans so a Wicklight run shows
up in your existing tracing backend — tracked as a post-0.1 plugin
(`wicklight.exporters`). Because the trace is the source of truth and is plain
JSONL, you can also export it yourself with a few lines of `jq`.

## When to move on

Reach for a bigger harness when you need: multi-agent orchestration or complex
graphs, a hosted/managed control plane, horizontal scale, or integration with a
team observability and policy stack you already run. Keep the agent files,
scenarios, and safety mindset — re-express them in the new tool, and you'll be
starting from a much safer place than a blank page.
