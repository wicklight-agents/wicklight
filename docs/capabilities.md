# Capabilities

Every surface Wicklight exposes, in one place: what it does, where it is
enforced, and **how you observe it**. The topic guides explain each area in
depth; this is the inventory.

It is written to be used as a **coverage checklist**. If you are testing the
harness — by hand, with a scenario suite, or with an agent that pokes at it —
this is the list of things to cover, and the "observe it by" column is how you
assert. The milestone column (M1–M12) says when a capability landed.

Legend for enforcement:

- **core** — fixed in the agent loop; a plugin cannot remove, reorder, or
  weaken it.
- **config** — driven by the agent or deploy file.
- **plugin** — supplied by an extension point (provider, tool, policy).

---

## 1. CLI surface

All commands exit `0` on success and non-zero on failure, so each is usable as a
CI gate. `run` exits non-zero when the run does not complete.

| Command | What it does | Key options | Observe it by | M |
| --- | --- | --- | --- | --- |
| `wicklight --version` | prints the version | — | `0.1.0` on stdout | M1 |
| `wicklight --help` | lists commands | — | a Commands panel with all 8 commands | M1 |
| `check <file>` | validates an agent file (`.md`) or deploy file (`.yaml`/`.yml`) and prints the effective config | — | the effective-config block, `api keys`, `capabilities`, `routing` sections; exit 1 on any error | M2 |
| `run <agent> <task>` | runs an agent end to end | `--fake`, `--world`, `--trace`, `--dry-run`, `--runs-dir` | streamed events, final output, the trace path, exit code | M1/M5 |
| `trace show <trace>` | pretty-prints a trace | `--step`, `--type`, `--json` | the rendered run, or one JSON event per line | M3 |
| `replay <trace>` | steps through a past run | `--all`, `--agent <file>` | the interactive cursor, or a counterfactual divergence report | M9 |
| `explain <trace> --step N` | shows what the model saw at a step | `--json` | the reconstructed context, response, and checks | M9 |
| `view [target]` | local web viewer | `--host`, `--port`, `--no-browser`, `--live`, `--runs-dir` | a URL on stdout; the JSON API below | M11 |
| `deploy <deploy.yaml>` | builds a locked-down image | `--engine`, `--print-dockerfile` | `built <tag> with <engine>`, or the generated build file | M12 |
| `providers list` | lists installed provider plugins | — | a table of name, package, version, contract, status, capabilities | M4 |

Things worth probing: a missing file, an unreadable file, a `.yaml` that isn't a
deploy file, `--step` beyond the end of a run, a truncated or corrupt trace
line, and a trace that is gzipped (`.jsonl.gz` is accepted everywhere a
`.jsonl` is).

## 2. The agent file

One Markdown file: YAML frontmatter (**rules the harness enforces**) above the
closing `---`, the prompt (**a request the model may ignore**) below it.

**Unknown keys are errors**, everywhere, at every nesting level — a typo in a
safety rule must never be silently dropped. Errors are line-numbered and
reported all at once.

| Key | Type | Notes | M |
| --- | --- | --- | --- |
| `name` | string | required | M2 |
| `models.default` | `provider/model` | required | M2 |
| `models.routes[]` | `{ when, use }` | first match wins | M10 |
| `models.fallback[]` | list of model ids | tried in order on provider failure | M10 |
| `tools.<name>` | `level` string, or an object | **tools are off unless listed**; `read: level` shorthand expands to `{ level: read }` | M2 |
| `tools.<name>.level` | `off`/`read`/`write`/`irreversible` | ordered; a tool whose risk exceeds its granted level is blocked | M2 |
| `tools.<name>.approval` | `required` | gates the tool regardless of level | M7 |
| `tools.<name>.waive_approval` | bool | lifts the *irreversible* default only; **requires `reason`** | M7 |
| `tools.<name>.reason` | string | the written justification for a waiver | M7 |
| `tools.<name>.sensitive` | bool | its output latches the run into sensitive mode | M10 |
| `policies[]` | list of single-key maps | evaluated in file order | M6 |
| `limits.max_steps` | int | default **20** | M2 |
| `limits.max_cost` | float USD | default **1.00** | M2 |
| `limits.timeout` | float seconds | default **300** | M2 |
| `limits.max_retries` | int | default **2** | M8 |
| `limits.retry_backoff` | float seconds | default **1.0** | M8 |

`check` prints every effective value tagged `(from file)` or `(default)`, so
provenance is always visible. `agent_config_json_schema()` exports the JSON
Schema for editor autocompletion.

**Validation cases to cover:** an unknown top-level key; an unknown key inside
`tools`/`limits`/`models`; a bad enum (`level: destroy`); a waiver with no
reason (and with an empty/whitespace reason); a malformed route condition; a
model id with no provider prefix; missing frontmatter delimiters; multiple
errors at once (all should be reported, not just the first).

## 3. The loop and its fixed safety stack

`run_agent` in `src/wicklight/core/loop.py` takes every dependency explicitly —
no globals. One step is: build context → route → call model → for each proposed
tool call, check then execute.

The check pipeline runs in this **fixed order**, and every stage is core:

| # | Stage | Blocks when | Observe it by |
| --- | --- | --- | --- |
| 0 | **Limits** | `timeout`, `max_steps`, or (post-call) `max_cost` reached | `limit_hit` event; status `limit` |
| 1 | **Permission check** | tool unlisted, `off`, unknown, or its risk exceeds the granted level | `policy_checked` deny citing the agent-file line |
| 2 | **Argument validation** | args don't match the tool's `input_model` | a structured failure returned to the model |
| 3 | **Policies** | the first `Deny` in file order; a raising policy counts as deny | one `policy_checked` per policy, allow *and* deny |
| 4 | **Plugin checks** | the first denial | `policy_checked` deny; none configured by default |
| 5 | **Approval gate** | approver denies, or none configured | `approval_requested` then `approval_resolved` |
| 6 | **Execute** | — | `tool_executed` with `ok` and `duration_ms` |

A blocked call is **never executed**; the model is told it was blocked and the
run continues. Preflight runs before the first model call and stops the run at
step 0 on a capability mismatch (`error` with `where: "preflight"`).

**Invariants to try to falsify:**

- A tool not listed in the agent file can never run, however the model asks.
- Policies cannot be reordered after the permission check, or skipped.
- A policy that raises blocks the call (fail closed) *and* logs an `error`.
- The approval gate is always last, so a policy denial pre-empts a prompt.
- The loop always terminates: every limit is checked every step.
- Nothing happens that is not an event — there is no path to disk or network
  that bypasses the `TraceLog`.

## 4. Trusted vs. untrusted context

Only the agent file's instructions and the user's task are trusted. **Every**
other message — tool results and the model's own turns — is flagged
`trusted=False`, and tool results are additionally wrapped in a "data, not
instructions" envelope before entering context. Oversized output is truncated
first; the envelope and flag are always applied.

**Observe it by:** `context_built.untrusted` lists the untrusted message
indices; `explain --step N` shows the boxed, source-labeled tool results.

**The headline demo** (`examples/scripts/injection.yaml` +
`examples/worlds/injection.yaml`) is the end-to-end case: a poisoned email, a
model that falls for it, and `email_only_to` blocking the send.

## 5. Policies

A pure, synchronous, deterministic, side-effect-free allow/deny over a proposed
call. It may read the call (`tool`, `arguments`, `risk`) and a read-only
`PolicyContext` (`run_id`, `spent_usd`, `agent_dir`) — nothing else. A `Deny`
always carries a reason.

| Policy | Applies to | Config | Blocks | M |
| --- | --- | --- | --- | --- |
| `email_only_to` | calls with a recipient (`to`, `recipient`, …) | addresses/domains; `@acme.com` = whole domain, case-insensitive | recipients off the allowlist | M6 |
| `sender_denylist` | calls with a sender (`sender`, `from`, …) | addresses/domains; `@acme.com` = that domain **and its subdomains** | senders on the denylist | — |
| `paths_within` | calls with a path (`path`, `file`, …) | root directories | paths resolving outside the roots — `..` and symlinks resolved first | M6 |
| `spend_limit` | calls with an amount (`amount_usd`, …) | `{ max_usd, per_call_usd }` | over the per-call cap, or pushing the **per-run** total over `max_usd` | M6 |
| `block_tools` | any | tool names | a minimal reference policy | M6 |

Note `max_usd` is per-run and cumulative, which defeats split payments — three
small payments that together exceed the cap are blocked.

**Observe it by:** a `policy_checked` event for every evaluation, allow and
deny. A deny names the policy and its agent-file line. Conformance:
`wicklight.testing.run_policy_conformance` fails a side-effecting or
non-deterministic policy.

**Cases to cover:** case-insensitive domain matching; a recipient field under
each accepted alias; symlink and `..` traversal out of a `paths_within` root;
cumulative spend across calls vs. a single over-cap call; policy ordering (first
deny wins, later policies not evaluated); a policy that raises.

> **Allowlists and denylists are not mirror images.** `email_only_to` does not
> match subdomains (failing closed is safe for an allowlist); `sender_denylist`
> does (not matching them would fail *open*). Worth a test either way — see
> [policies.md](./policies.md).

## 6. Approvals and waivers

A call needs approval if the tool is `approval: required`, **or** it is
`irreversible` and not waived.

| Approver | Behaviour |
| --- | --- |
| `TerminalApprover` | prompts `Approve? [y/N]`; **default deny**; timeout denies; denies immediately when not attached to a TTY |
| `AutoApprove` | approves everything (tests, trusted headless runs) |
| `AutoDeny(note)` | denies everything with a fixed note |
| `ScriptedApprover([...])` | replays decisions in order; **fails closed** when exhausted |

**Fail-closed behaviours to verify:** no approver configured → denied
(`REQUIRE_APPROVER`); non-interactive `wicklight run` → denied with an
explanation, never a hang; library `agent.run()` without an approver → denied.

**Waivers:** `waive_approval: true` requires a written `reason`; `check` rejects
a reasonless waiver and lists every waiver prominently. A waived call skips the
approver but is still recorded — `approval_resolved` with `waived: true`,
`by: "waiver"`, and the reason as its note. A waiver lifts only the irreversible
*default*; an explicit `approval: required` still gates the tool.

**Observe it by:** `approval_requested` (tool, reason) and `approval_resolved`
(`approved`, `by`, `note`, `duration_ms`, `waived`).

## 7. Model routing, fallback, and sensitivity

**Routing (M10).** `models.routes` is evaluated top to bottom before each model
call; first match wins; no match falls through to `default`. A route's `when` is
an **AND** of conditions:

| Condition | Meaning |
| --- | --- |
| `step` | `planning` (the first model call) or `execution` |
| `context_tokens` | comparison on estimated context size, e.g. `">100k"`, `">=50000"` |
| `cost_so_far` | comparison on dollars spent, e.g. `">0.5"` |
| `data` | `sensitive` — once sensitive content is in context |

Unknown conditions, bad step values, and malformed comparisons are rejected at
`check` time with a line number. `check` prints routes in evaluation order,
verifies each referenced model resolves to an installed provider, and **warns
on an unreachable route** shadowed by an earlier, broader one.

**Enforced sensitivity (M10).** Once a sensitive tool result enters context, the
run **latches** into sensitive mode for the rest of the run — even if that
result is later truncated out. From then on only sensitivity-allowed models (the
targets of a `data: sensitive` route) may be called. Enforcement lives inside
the router: a matching route to a non-allowed model is *excluded* and recorded;
if nothing allowed remains the run **stops with an error rather than leak**
(`where: "sensitivity"`). Sensitivity can also be set at runtime via
`ToolResult.sensitive`. `check` warns when an agent declares a sensitive tool
but no `data: sensitive` route.

**Fallback (M10).** On a model failure that survives its retry policy, the
`fallback` list is tried in order. Each failure or skip is a recoverable `error`
with `where: "fallback"`; exhausting the list is a terminal error listing what
was tried. **Fallbacks never bypass sensitivity** — a non-allowed fallback is
skipped and the skip is logged.

**Observe it by:** `model_routed` (`model`, `matched_rule`, `source` line) on
every call, and the `error` events above.

## 8. Providers

Installed via the provider entry point; `providers list` shows name, package,
version, contract version, status, and declared capabilities.

| Provider | Notes | M |
| --- | --- | --- |
| `fake/<model>` | replays a YAML script of responses in order — deterministic, offline | M4 |
| `anthropic/<model>` | `ANTHROPIC_API_KEY`; streaming, parallel tools, 200k ctx | M8 |
| `openai/<model>` | `OPENAI_API_KEY`; streaming, parallel tools, structured output, 128k ctx | M8 |
| `local/<model>` | OpenAI-compatible (Ollama, vLLM, LM Studio) via `OPENAI_BASE_URL`; **no key**; conservative capabilities | M8 |
| `ReplayProvider` | serves a past run's recorded responses back through the loop | M9 |

**Error mapping (M8).** Provider failures map to neutral kinds: `rate_limit`,
`overloaded`, `timeout`, `auth`, `invalid_request`, `context_too_long`,
`unknown`. Retryable kinds (rate limit, overloaded) are retried with **visible**
backoff — one recoverable `error` per attempt carrying `kind`, `attempt`, and
`wait_seconds`, up to `max_retries`. Nothing retries silently. Anything else, or
exhausted retries, is terminal and carries a `suggestion` where one exists.

**Preflight (M8).** `check` and run start compare the agent's static needs
(tools enabled, estimated context size) against the provider's declared
capabilities and fail *before* the first model call.

**Contract:** `wicklight.contracts.CONTRACT_VERSION` is `1.0`; the previous
major is supported for six months after a new one ships. Conformance:
`run_provider_conformance`, also exposed as a pytest plugin
(`pytest --wicklight-provider=<name> -m conformance`).

## 9. Tools

A tool is a named action with a typed Pydantic input schema, a declared risk
(`read`/`write`/`irreversible`), the network hosts it needs, and whether its
output is sensitive. `run` receives validated input plus a `ToolContext`
carrying injected secrets **the model never sees**, and returns a `ToolResult`
(`ok`, `output`, `error`, `sensitive`) — errors are *returned*, not raised.

Register via the `wicklight.tools` entry point, or use the `@tool` decorator on
an async function. Built-in mocks (`ReadInbox`, `SendEmail`, `ReadFile`,
`DeleteFile`, `MakePayment`) act on a `MockWorld` seeded from YAML —
deterministic, in-memory, used by examples, tests, and the game.

**Observe it by:** `tool_proposed` (arguments) and `tool_executed` (`ok`,
`result_ref`, `duration_ms`, `dry_run`). Conformance: `run_tool_conformance`.

**Cases to cover:** a tool that raises (surfaced to the model as a failure, run
survives); invalid arguments; a tool returning `ok=False`; a tool returning
`sensitive=True` at runtime; oversized output (truncated, still enveloped and
flagged); a tool asking for a secret it didn't declare.

## 10. The trace

Append-only JSONL, one event per line, in order — the source of truth for
everything the CLI and viewer show. Readable with `grep` and `jq`.

Every line carries `v` (format version, currently `1`), `run_id`, `step`,
`timestamp`, `type`, `payload`, and `explain` (a human sentence). `v` is on
every line so a reader can decide per line how to interpret it.

The 14 event types: `run_started`, `context_built`, `model_routed`,
`model_called`, `model_responded`, `tool_proposed`, `policy_checked`,
`approval_requested`, `approval_resolved`, `tool_executed`, `limit_hit`,
`error`, `run_finished`, and `egress_denied` (§14, in progress). Full payload
tables are in [trace-events.md](./trace-events.md) — which currently documents
the first 13.

Run statuses: `completed`, `stopped`, `limit`, `error`.

**Blob store (M9).** Large payloads are content-addressed by SHA-256 and
referenced from events: `model_called.request_ref`, `model_responded.response_ref`,
`tool_executed.result_ref`, `context_built.content_ref`. Identical content is
stored once.

**Redaction (M8).** The trace writer runs a redactor over every line and blob
**before it touches disk**: the exact value of every set API-key variable, plus
any key-shaped string (`sk-…`, `sk-ant-…`, `Bearer …`). A provider error that
echoes a key back is written `… REDACTED`. Shared with the cassette scrubber, so
one definition protects both paths.

**Reading is forgiving:** a corrupt line is reported as an issue rather than
failing the whole run — the CLI and the viewer behave the same way.

## 11. Replay, explain, dry-run, counterfactual

| Capability | What it gives you | M |
| --- | --- | --- |
| `replay <trace>` | interactive stepping: `[n]ext · [p]rev · <step#> · [b]lock · [a]pproval · [e]rror · [q]uit`; reads the trace only — **never** a model call or tool side effect | M9 |
| `replay --all` | the whole run non-interactively, for CI and bug reports | M9 |
| `ReplayProvider.from_trace()` | re-executes a past run offline; **stops at the first divergence** (step, field, recorded vs actual) rather than returning a stale response | M9 |
| `explain --step N` | the context the model saw, untrusted spans marked, the response, every check with its reason and agent-file line; `--json` for a structured form | M9 |
| `run --dry-run` | every tool stubbed: checks still run and **blocked calls are still blocked**, but a passing call is recorded `would have run <tool> (dry run)`. `run_started` and `tool_executed` carry `dry_run`. The CLI assumes approvals granted (it's a what-if); automatic checks block for real | M9 |
| `replay --agent <file>` | counterfactual: re-checks the original run's tool calls against a changed agent file, reports the **first** changed outcome and stops (later model decisions depended on the old result). Written as its own trace, marked `counterfactual` | M9 |

The counterfactual re-check reuses the same primitives the loop uses — the
effective config's permission level, the configured policies' `check`, and the
approval requirement — so its verdict matches what a real run would decide at
the check stage.

**A good round-trip test:** re-running a `FakeProvider` trace through the loop
must reproduce an identical event sequence.

## 12. The viewer

Offline by design: binds `127.0.0.1`, no account, never runs an agent, reads
only trace files already on disk.

| Endpoint | Returns |
| --- | --- |
| `GET /api/meta` | run count, and whether a run is being followed live |
| `GET /api/runs` | one summary per run: agent, outcome, steps, cost, models, blocked/approved counts |
| `GET /api/runs/{run_id}/events` | the run's events (same JSON as `trace show --json`) plus read issues |
| `GET /api/runs/{run_id}/blobs/{hash}` | a blob by sha256 (lazy — large payloads fetched on demand) |
| `GET /api/runs/{run_id}/stream` | server-sent events: events so far, then new ones, then `end` (powers `--live`) |

A run id is the trace file's stem. **Blob hashes are validated as 64-char sha256
digests, so a crafted reference cannot escape the blob directory** — worth a
test (`../`, a short hash, a non-hex hash).

The page renders a run header over a timeline, with badges for blocked,
approved, waived, retried, limit, dry-run, and sensitive. Every badge pairs an
icon *and* a label with its color, so status never depends on color alone.
Expanding a step gives the browser version of `explain`. The frontend is Svelte
+ Vite + TypeScript, **prebuilt** into `assets/` and committed, so users never
need Node; CI rebuilds to verify the committed assets are current.

## 13. Deploy

`deploy.yaml` says *how* to run an agent, kept separate from the agent file so
the same `agent.md` runs unchanged locally and deployed.

| Field | Meaning |
| --- | --- |
| `name` | deployment name |
| `agent` | path to the agent file, relative to the deploy file; validated too |
| `triggers[]` | each entry has **exactly one** of `schedule` (5-field cron) or `webhook` (`{ path }`) |
| `secrets` | name → `{ from: env \| file \| keychain, name?, path? }`; a `file` secret needs `path` |
| `traces` | where run traces are written |
| `egress.extra_hosts` | hosts beyond the agent's model and tool hosts |

`check` on a `.yaml` validates the deploy file **and** its agent file together,
then prints triggers, each secret's status (`set` / `MISSING` / `deferred` for
keychain) — **never a value** — and the egress hosts.

**Secrets never touch the image.** Values are resolved on the host at start and
injected as runtime environment. Inside, the harness hands each secret only to
tools that declare it via `required_secrets`, and redaction keeps values out of
traces even in error messages. A missing secret fails fast at start, naming
every one.

**The image (M12).** `wicklight deploy` detects Docker or Podman and builds a
two-stage image: deps installed with `uv`, then copied into a Google
**distroless** runtime with **no shell and no package manager**, running as a
**non-root** user, built for a **read-only root filesystem** (only the trace
directory is a writable mount). Agent and deploy files are baked in read-only.
Standard OCI image, tagged `wicklight-<name>:<content-hash>` — so the tag is
reproducible for identical input, which is itself testable.

> Building currently needs a Wicklight source checkout; it will install by
> version once Wicklight is on PyPI.

## 14. Egress control (DTN-254, M12)

> Note: `docs/deploy-file.md` still describes the egress proxy as belonging to a
> later milestone. It shipped in `243174b`; that line is stale.

**The allowlist is derived, never hand-maintained** (`deploy/egress.py`). It is
the union of:

- the hosts of every model provider the agent can route to — `default`, every
  `routes[].use`, and every `fallback` entry (source `provider:<name>`);
- the `network_hosts` each **enabled** tool declares — tools at level `off` are
  skipped, and a listed-but-not-installed tool is ignored (source
  `tool:<name>`);
- the deploy file's `egress.extra_hosts` (source `extra_hosts`).

Order is stable and de-duplicated; the first source to introduce a host wins.

**`check` prints it.** `check <deploy.yaml>` now renders an `egress allowlist:`
section listing each host with its source, followed by
`(every other host is refused and logged)`. When the allowlist can't be computed
it falls back to showing only the author's `extra_hosts`.

**The proxy enforces it** (`deploy/proxy.py`). The deployed container has no
direct route out; a CONNECT-only HTTP proxy alongside it is the only path.
Allowed hosts are piped straight through with **no TLS interception**; anything
else is refused with `403` and recorded as an `egress_denied` event (`host`,
`port`, `reason`, optional `component`). `WICKLIGHT_EGRESS_TRACE` points at a
path to append those events to.

That recording is the point: a plain firewall rule drops the packet silently,
whereas **a blocked exfiltration attempt here is visible in the trace**.

**Cases to cover:** a host reachable only via a fallback model; a sensitive-route
model's host; a tool at `off` whose host must *not* appear; an uninstalled tool;
a denied CONNECT producing exactly one `egress_denied`; a non-CONNECT verb;
allowlist determinism across runs.

## 15. Python API and test kits

```python
from wicklight import Agent

agent = Agent.load("agent.md")
result = agent.run(task, provider=..., world=..., approver=..., dry_run=...)
```

`Agent.run` is a sync wrapper over `Agent.arun` that also works inside a running
event loop (it uses a worker thread, so it never fights a notebook's loop).
Both accept `provider`, `providers` (a map, for routing), `tools`, `world`,
`approver`, `checks`, `policies`, `dry_run`, `on_event`, `run_id`, `runs_dir`,
and `secrets`. `RunResult` carries `status`, `steps`, `output`, `usage`,
`run_id`, and `trace_path`.

**The library default is fail-closed on approvals** — pass an approver
explicitly.

From `wicklight.testing`:

| Kit | Purpose |
| --- | --- |
| `Scenario` / `ScenarioResult` | an agent + script + world (as **inline text**, not paths) with `assert_completed`, `assert_stopped`, `assert_ran`, `assert_not_ran`, `assert_approved`, `assert_approval_denied`, `assert_blocked(tool=, by=, reason=)`, `assert_limit` |
| `run_provider_conformance` | the Provider contract kit (also a pytest plugin) |
| `run_tool_conformance` | the Tool contract kit |
| `run_policy_conformance` | the Policy contract kit — catches side effects and non-determinism |
| `cassette_client`, `Cassette`, `scrub_text`, `scan_for_secrets` | recorded-HTTP fixtures for provider tests |

**Cassettes (M8).** Requests match the next recorded interaction by method and
URL, in order; an unmatched request **raises rather than falling through to the
network**, so a replayed test can never go live. Recording scrubs before
writing: request headers aren't stored at all, sensitive response headers are
dropped, the whole cassette goes through `scrub_text`, and `save()` refuses to
write a file still matching a secret pattern. `tests/test_cassettes.py` scans
every committed cassette in CI as a backstop.

## 16. Credentials

Keys come from the **environment, never the agent file**: `anthropic` →
`ANTHROPIC_API_KEY`, `openai` → `OPENAI_API_KEY`. `resolve_key(provider)` raises
an error naming the variable to set — never a value. `fake` and `local` have no
entry and need no key. `check` ends with an `api keys` section listing what's
needed and whether it's set.

---

## Cross-cutting invariants

The properties that hold across every surface. These are the highest-value
things to attack, because each one is a claim the whole project rests on:

1. **Nothing happens that isn't in the trace.** Every model call, routing
   decision, check, approval, and tool call is an event, written through a
   single `TraceLog`.
2. **Tools are off unless listed.** Absence is denial, not permission.
3. **Every gate fails closed.** A raising policy denies. A missing approver
   denies. A non-interactive approval denies. An unmatched cassette raises.
   Exhausted scripted approvals deny.
4. **Secrets never reach disk or the model.** Not in a trace, not in a blob, not
   in an error message, not in an image layer, not in a cassette.
5. **Sensitive data never reaches a non-allowed model.** The run stops instead —
   including on the fallback path.
6. **Offline commands stay offline.** `check`, `trace show`, `explain`,
   `replay`, and `view` make no model call and cause no tool side effect, ever.
7. **A typo is an error.** Unknown keys are rejected everywhere, with a line
   number, and all errors are reported at once.
8. **The loop always terminates.** Step, cost, and time limits are checked every
   step and cannot be removed by a plugin.
9. **Replay is faithful or loud.** It reproduces the run exactly, or reports the
   first divergence — never a stale response.
10. **A block is visible.** Nothing is silently dropped: every denial — a
    policy, a permission, an approval, a skipped fallback, a refused host —
    produces an event that names what was blocked and why.

## See also

- [Getting started](./getting-started.md) — the guided tour
- [The loop](./the-loop.md) · [Trace events](./trace-events.md)
- [Policies](./policies.md) · [Approvals](./approvals.md) · [Routing](./routing.md)
- [Replay](./replay.md) · [Viewer](./viewer.md) · [Deploy file](./deploy-file.md)
- [Credentials](./credentials.md) · [Local models](./local-models.md) ·
  [Recorded HTTP](./recorded-http.md) · [Model types](./model-types.md)
- `docs/user-tests.md` — the manual acceptance suite (currently covers M1–M10)
