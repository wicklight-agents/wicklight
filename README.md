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

## Development

Wicklight uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync                       # create the venv and install from uv.lock
uv run python -c "import wicklight"
```

Requires Python 3.10+. `uv` will download a suitable interpreter automatically
if one is not already installed.

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
