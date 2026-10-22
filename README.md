# wicklight

[![CI](https://github.com/wicklight-agents/wicklight/actions/workflows/ci.yml/badge.svg)](https://github.com/wicklight-agents/wicklight/actions/workflows/ci.yml)

Wicklight is a small, open-source Python harness that is many developers'
first agent harness: it makes every step observable, every failure debuggable,
and safety the default. Developers define an agent in one readable file, run it
with full tracing, and deploy it with one command. The harness owns a few
strict contracts (model providers, tools, policies) so anyone can extend it
with plugins, while safety enforcement stays fixed in the core.

It is a learning harness by design. It favors clarity over power, and we expect
users to graduate to more advanced harnesses, carrying habits of tracing,
testing, and least privilege with them. The same engine powers a companion web
game that teaches agent safety hands-on.

## Getting started

Wicklight isn't on PyPI yet, so install from source. It uses
[uv](https://docs.astral.sh/uv/) for environment and dependency management —
`uv` downloads a suitable Python 3.10+ automatically, so that's the only
prerequisite ([install uv](https://docs.astral.sh/uv/getting-started/installation/)).

```bash
git clone https://github.com/wicklight-agents/wicklight.git
cd wicklight
uv sync                       # create .venv and install from uv.lock
```

Then run the CLI with `uv run` (no venv activation needed):

```bash
uv run wicklight --version              # 0.1.0
uv run wicklight --help                 # list commands
uv run wicklight check examples/inbox.md                 # validate an agent file
uv run wicklight run examples/inbox.md "summarize my inbox" \
  --fake examples/scripts/summarize.yaml \
  --world examples/worlds/inbox.yaml --trace              # run it (offline, scripted)
uv run wicklight view examples/sample.jsonl              # open a run in the web viewer
```

Prefer a bare `wicklight` command? Either activate the venv
(`source .venv/bin/activate`) or install it as a tool
(`uv tool install --editable .`).

> `wicklight --help` lists every command: `check` (validate an agent file),
> `run` (run an agent with full tracing), `trace show`, `replay` and `explain`
> (inspect a past run offline), `view` (the local web viewer), and `providers`.
> The guides below go deeper.

## Examples

Commented example agent files live in [`examples/`](./examples). Each teaches
one concept and passes `wicklight check`:

- [`inbox.md`](./examples/inbox.md) — read an inbox and draft replies; send
  email only to a recipient allowlist, with approval.
- [`files.md`](./examples/files.md) — read-only file access confined to a path
  allowlist (least privilege).
- [`payments.md`](./examples/payments.md) — an irreversible `make_payment` tool
  behind an approval gate, plus a spend cap.

```bash
uv run wicklight check examples/payments.md
```

## Documentation

Topic guides live in [`docs/`](./docs):

- [The loop](./docs/the-loop.md) — the fixed agent loop and its safety stack.
- [Trace events](./docs/trace-events.md) — the JSONL trace, event by event.
- [Policies](./docs/policies.md) and [Approvals & waivers](./docs/approvals.md)
  — the allow/deny and human-in-the-loop gates.
- [Model routing](./docs/routing.md) — per-step model choice, fallback, and
  enforced sensitivity routing.
- [Replay, explain & dry-run](./docs/replay.md) — re-inspect a run offline.
- [The local web viewer](./docs/viewer.md) — `wicklight view`, the browser UI
  for a run's timeline and step details.
- Providers: [credentials](./docs/credentials.md),
  [local models](./docs/local-models.md),
  [recorded HTTP](./docs/recorded-http.md),
  [model types](./docs/model-types.md).

## Development

The checks below (and CI) run through the same `uv`-managed environment created
by `uv sync` above.

### Checks

These three must pass before a change is merged:

```bash
uv run ruff check             # lint
uv run pyright                # strict type checking (src/)
uv run pytest                 # tests with coverage
```

`uv run ruff format` applies the formatter (`uv run ruff check --fix`
auto-fixes lint issues).

### Pre-commit hooks (optional)

Contributors can install Git hooks that run Ruff lint + format on commit:

```bash
uv run pre-commit install
```
