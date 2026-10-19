# Replay

A trace is the source of truth for a run, and every run records enough to be
re-run or inspected later with no model calls and no side effects (M9).

## What gets recorded

Each run stores, in the content-addressed blob store (DTN-200):

- the full **request** sent to the model, referenced by `model_called.request_ref`;
- the full **response**, referenced by `model_responded.response_ref`;
- each **tool result**, referenced by `tool_executed.result_ref`.

Identical content is stored once, and a reference is the content's SHA-256 — so
two runs that produce the same request hash it identically.

## Stepping through a run — `wicklight replay`

```bash
uv run wicklight replay runs/<run_id>.jsonl          # interactive
uv run wicklight replay runs/<run_id>.jsonl --all    # print the whole run (CI)
```

Interactive stepping (DTN-237) moves a cursor over the recorded events with the
same renderer as `trace show`:

```
[n]ext · [p]rev · <step#> · [b]lock · [a]pproval · [e]rror · [q]uit
```

`b`/`a`/`e` jump to the next policy denial, approval, or error. It reads the
trace only — no model calls, no tool side effects, ever. `--all` is the
non-interactive form for CI and bug reports.

## Re-running a trace — `ReplayProvider`

`ReplayProvider.from_trace(trace)` serves the recorded responses back through
the core loop in order, so a run can be re-executed offline (DTN-236):

```python
from wicklight.providers import ReplayProvider

agent.run(task, provider=ReplayProvider.from_trace("runs/<run_id>.jsonl"), world=...)
```

If the loop sends a request that differs from the one recorded at that step,
replay stops and reports the first divergence (step, field, recorded vs actual)
rather than returning a stale response — so a replay either reproduces the run
faithfully or tells you exactly where it couldn't. Re-running a FakeProvider
trace through the loop reproduces an identical event sequence.

## Counterfactual replay — `replay --agent`

The "would my fix have caught it?" workflow (DTN-238):

```bash
uv run wicklight replay runs/<run_id>.jsonl --agent tightened_agent.md
```

It re-checks each tool call the model made in the original run against a changed
agent file — new policies, tighter permissions, new approval rules — using the
recorded decisions, with no model call and no tool execution. It reports the
first step whose outcome changed and stops there, because every later model
decision in the original run depended on the old result:

```
step 2: send_email was allowed, now blocked by email_only_to
  reason: send_email to attacker@evil.com is not allowed; …
stopped here: later model decisions depended on the old result.
```

The re-check reuses the same primitives the core loop uses — the effective
config's permission level, the configured policies' `check`, and the approval
requirement — so a counterfactual outcome matches what a real run under the new
file would decide at the check stage. The replay is written as its own trace,
marked `counterfactual` on `run_started`.
