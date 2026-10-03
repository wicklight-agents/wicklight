# wicklight

A small, open-source Python harness that makes every agent step observable,
every failure debuggable, and safety the default. Define an agent in one
readable file, run it with full tracing, and deploy it with one command.

See [`wicklight-solution-brief.md`](./wicklight-solution-brief.md) for the design.

## Development

Wicklight uses [uv](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync                       # create the venv and install from uv.lock
uv run python -c "import wicklight"
uv run pytest
```

Requires Python 3.10+. `uv` will download a suitable interpreter automatically
if one is not already installed.
