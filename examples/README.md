# Examples

A curated set of agent files, **one per safety feature**. Each has a commented
header explaining what it teaches and what to look for in the trace, passes
`wicklight check`, and runs on the **fake provider** out of the box — no API key,
no network — using the scripts in [`scripts/`](./scripts) and the mock worlds in
[`worlds/`](./worlds). Each also runs on a real model once you set a key.

| Example | Lesson | What to look for in the trace |
| --- | --- | --- |
| [`inbox.md`](./inbox.md) | Least privilege + a recipient allowlist, with approval | `send_email` is `write` + approval-gated; `email_only_to` cited |
| [`inbox.md` + injection](./scripts/injection.yaml) | Untrusted tagging + a policy block | a poisoned email enters context as **untrusted**; the send to the attacker is **blocked** by `email_only_to` |
| [`payments.md`](./payments.md) | Approvals, a spend limit, and a documented waiver | `spend_limit` denies the over-cap payment **before** approval; the irreversible `make_payment` is gated |
| [`files.md`](./files.md) | A path allowlist + a read-only tool | a read inside `./docs` is allowed; a read outside is **blocked** by `paths_within` |
| [`routed.md`](./routed.md) | Model routing + sensitive data kept local | `model_routed` picks the planning model, then **pins to the local model** once a sensitive file is read |
| [`deploy.yaml`](./deploy.yaml) | A deployable agent (sealed container) | triggers, secret status, and the egress allowlist from `wicklight check` |

## Run them on the fake provider

```bash
# Least privilege + recipient allowlist, with approval.
uv run wicklight check examples/inbox.md
uv run wicklight run examples/inbox.md "summarize my inbox" \
  --fake examples/scripts/summarize.yaml --world examples/worlds/inbox.yaml --trace

# The prompt-injection demo: the send to the attacker is blocked.
uv run wicklight run examples/inbox.md "handle my inbox" \
  --fake examples/scripts/injection.yaml --world examples/worlds/injection.yaml --trace

# Approvals + spend limit (the $150 payment is denied by spend_limit).
uv run wicklight run examples/payments.md "pay the invoice" \
  --fake examples/scripts/pay_invoice.yaml --world examples/worlds/invoice.yaml --trace

# Path allowlist: a read outside ./docs is blocked.
uv run wicklight run examples/files.md "read the roadmap" \
  --fake examples/scripts/read_files.yaml --world examples/worlds/files.yaml --trace

# Model routing: planning on a big model, sensitive data pinned to the local one.
uv run wicklight run examples/routed.md "summarize the revenue file" \
  --fake examples/scripts/routed.yaml --world examples/worlds/routed.yaml --trace

# A deployable agent (see docs/deploying.md).
uv run wicklight check examples/deploy.yaml
```

Open any run in the viewer to see the lesson at a glance:

```bash
uv run wicklight view runs/<run-id>
```

## Running on a real model

Each agent file names real models (e.g. `anthropic/claude-sonnet`). Set the
matching key (`wicklight check <file>` lists which) and drop the `--fake`/`--world`
options; the agent runs unchanged. `inbox_local.md` is a variant that routes to a
local model via Ollama (see [`docs/local-models.md`](../docs/local-models.md)).
