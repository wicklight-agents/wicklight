# Recorded HTTP fixtures (cassettes)

Real provider adapters (M8) talk to the Anthropic / OpenAI APIs over HTTP. Their
tests must still run in CI with **no network and no API keys**, so each adapter
records real HTTP exchanges once into a *cassette* and replays them. The harness
lives in `wicklight.testing.cassettes` (DTN-226).

## Replaying (the default, and CI)

```python
from wicklight.testing import cassette_client

async with cassette_client("tests/cassettes/anthropic_plain.json") as client:
    response = await client.post(url, json=payload)
```

Each outgoing request is matched to the next recorded interaction with the same
method and URL, in order. An unmatched request raises `CassetteError` rather than
falling through to the network — a replayed test can never accidentally go live.

## Recording (maintainers)

When a provider API changes, refresh its cassette with real requests:

```bash
uv run pytest tests/test_<adapter>.py --record
```

A test opts into recording via the `record_mode` fixture (see
`tests/conftest.py`) and passes it to `cassette_client(path, record=record_mode)`.
In record mode the real requests go out and are written back when the client
closes.

## Secrets never reach disk

Recording scrubs before it writes:

- request headers (which carry the API key) are **not stored** at all;
- sensitive response headers (`authorization`, `x-api-key`, `openai-organization`,
  `set-cookie`, …) are dropped;
- the whole cassette is run through `scrub_text`, which redacts key-shaped
  strings (`sk-…`, `sk-ant-…`, `Bearer …`, …);
- `Cassette.save()` refuses to write a file that still matches a secret pattern.

As a backstop, `tests/test_cassettes.py` scans every committed cassette with
`scan_for_secrets` and fails in CI if anything key-shaped slips through.
