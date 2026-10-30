# Wicklight

**A small, observable, safe-by-default agent harness.** Wicklight is for
developers building their first agent: it makes every step observable, every
failure debuggable, and safety the default. You define an agent in one readable
file, run it with full tracing, and deploy it with one command.

```bash
pip install wicklight            # or: uv add wicklight
wicklight check examples/inbox.md
wicklight run examples/inbox.md "summarize my inbox" \
  --fake examples/scripts/summarize.yaml --world examples/worlds/inbox.yaml --trace
wicklight view runs/<run-id>     # open the run in the local viewer
```

## What makes it different

- **Safe by default.** A fixed core enforces permissions, policies, approvals,
  and untrusted-content tagging in a set order that plugins cannot bypass. See
  the [safety model](safety-model.md).
- **Everything is observable.** Every model call, routing decision, policy
  check, approval, and tool call is one line in an append-only JSONL
  [trace](trace-events.md) — readable with `grep`, `jq`, or the
  [viewer](viewer.md).
- **One readable file.** An [agent file](agent-file.md) holds the rules
  (model, tools, permissions, policies, limits); the Markdown body holds the
  instructions.
- **Debuggable offline.** [Replay, explain, and dry-run](replay.md) let you
  re-inspect any run with no model calls and no side effects.
- **Extensible by contract.** Providers, tools, and policies are
  [plugins](plugins.md) built against small, versioned contracts with a
  conformance kit.
- **Deployable.** [`wicklight deploy`](deploying.md) builds a locked-down,
  non-root, shell-less container with an egress allowlist.

## A learning harness by design

Wicklight favors clarity over power. We expect you to graduate to more advanced
harnesses, carrying habits of tracing, testing, and least privilege with you —
see [graduating](graduating.md) for how the concepts map.

## Start here

1. **[Quickstart](getting-started.md)** — install, run the inbox example on the
   fake provider, then on a real model, then open the viewer. Under 10 minutes.
2. **[The loop](the-loop.md)** and **[safety model](safety-model.md)** — how a
   run is structured and what protects you.
3. **[Agent file reference](agent-file.md)** — every field and default.
