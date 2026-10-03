# Contributing to Wicklight

Thanks for your interest in Wicklight. This guide takes you from a fresh clone
to passing tests, and explains the standards every change is held to.

> **Project status:** Wicklight is in early development (M1). APIs and contracts
> are still moving, and reviews of external pull requests may be slow while the
> core stabilizes. Opening an issue first is the fastest way to align.

## The four values

Every design and review decision is judged against these four priorities, **in
this order**. When a trade-off comes up, the earlier value wins.

1. **Safety by default.** Risky capabilities require explicit opt-in. Enforcement
   lives in the core; plugins can add rules but never remove a check.
2. **Observability.** Nothing happens that isn't in the trace: every model call,
   routing decision, policy check, approval, and tool call is logged.
3. **Debuggability.** Every decision explains itself, any run replays exactly,
   and the CLI can show what the model saw at any step.
4. **Ease of use.** One readable agent file, a loop small enough to read in one
   sitting, and clear errors over clever behavior.

If your change weakens a safety check or makes something happen that the trace
can't explain, expect that to be a blocking review comment.

## Prerequisites

The only prerequisite is [uv](https://docs.astral.sh/uv/). It manages the
virtual environment and dependencies, and will download a suitable Python 3.10+
interpreter automatically — you do not need to install Python yourself.

- Install uv: <https://docs.astral.sh/uv/getting-started/installation/>

## Setup

```bash
git clone https://github.com/wicklight-agents/wicklight.git
cd wicklight
uv sync                       # create .venv and install from uv.lock
```

Verify your environment:

```bash
uv run wicklight --version    # prints the version
uv run pytest                 # the test suite should pass
```

That is the whole path from clone to passing tests. If `uv run pytest` is green,
you are ready to make changes.

## Running the checks

These four commands are exactly what CI runs (on Python 3.10, 3.11, 3.12, and
3.13). All must pass before a change can merge:

```bash
uv run ruff check             # lint
uv run ruff format --check    # formatting
uv run pyright                # strict type checking (src/)
uv run pytest                 # tests with coverage
```

Fix-ups while you work:

```bash
uv run ruff format            # apply the formatter
uv run ruff check --fix       # auto-fix lint issues
```

Optionally, install the Git pre-commit hooks so Ruff runs on every commit:

```bash
uv run pre-commit install
```

## Coding standards

These are enforced by Ruff and Pyright; the list below explains the intent.

- **Type hints everywhere.** `src/` is type-checked by Pyright in **strict**
  mode. Types are documentation and a free static test.
- **Prefer `Protocol`** for interfaces (structural subtyping) over ABCs.
- **Model data with dataclasses or Pydantic**, not raw dicts. Use
  `frozen=True` for value objects.
- **No silent failures.** A bare `except: pass`, an empty `catch`, or a
  swallowed error is always wrong — log it, re-raise it, or convert it to an
  explicit return the caller must handle. Ruff's blind-except rule enforces this
  and it is a blocking review finding.
- **Use `pathlib`**, not `os.path`.
- **Use `logging`**, not `print`, in library code.
- **Explicit dependency injection** over module-level globals or singletons.
- **No mutable default arguments**, and avoid `*args`/`**kwargs` on public
  interfaces — be explicit about the contract.
- Line length is 88; let `ruff format` own formatting.

## Testing standards

- **Favor integration tests over narrow unit tests.** Test behavior through the
  seams a user actually uses, not private implementation details.
- **Test behavior, not implementation.** A refactor that preserves behavior
  should not break tests.
- **Every bug fix gets a regression test** that fails before the fix and passes
  after.
- New observable behavior should assert on the **trace events** it produces —
  the trace is the product's source of truth.

## Making a change

1. Create a branch (we use the Linear issue id, e.g. `git checkout -b dtn-123`).
2. Make your change with tests, and keep the four checks green locally.
3. Open a pull request against `main` and fill in the template, including the
   checklist (tests, trace events, safety impact).
4. CI must be green across all Python versions before merge.

`main` is the default and only long-lived branch; there is no `master`. Please
branch from `main` and target your pull requests at `main`.
