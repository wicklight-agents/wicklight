# The local web viewer

`wicklight view` opens a run trace in a local web page. It is offline by design:
it binds to `127.0.0.1`, needs no account or external service, never runs an
agent, and only reads trace files already on disk.

```bash
uv run wicklight view examples/sample.jsonl       # a specific trace file
uv run wicklight view run_123                      # a run id under ./runs
```

The server picks a free port, prints its URL, and opens your browser. Press
**Ctrl+C** to stop it. `--no-browser` skips opening a browser; `--port` pins a
port; `--host` changes the bind address (loopback by default — only change this
if you understand the exposure).

## What it serves

A small read-only JSON API over the trace and its content-addressed blob store:

| Endpoint | Returns |
| --- | --- |
| `GET /api/runs` | one summary per run: agent, outcome, steps, cost, models, and counts of blocked and approved actions |
| `GET /api/runs/{run_id}/events` | the run's events (the same JSON as `trace show --json`) plus any read issues |
| `GET /api/runs/{run_id}/blobs/{hash}` | a blob by its sha256 hash (lazy; the viewer fetches large context/result payloads on demand) |

A run id is the trace file's stem (`run_123.jsonl` → `run_123`), matching the
blob directory name. Blob hashes are validated as 64-char sha256 digests, so a
crafted reference cannot escape the blob directory. A corrupt trace line is
reported in `issues` rather than failing the whole run — the same forgiving read
the CLI uses.

Everything else is served from the prebuilt frontend; `/` returns the app.

## Frontend (for contributors)

The frontend is a small **Svelte + Vite + TypeScript** app under
`src/wicklight/viewer/frontend/`. It is **prebuilt** into
`src/wicklight/viewer/assets/`, which ships in the wheel — so `pip install
wicklight` is enough and **users never need Node**.

```bash
cd src/wicklight/viewer/frontend
npm install            # once
npm run check          # svelte-check (type-check)
npm run build          # writes ../assets/ (committed)
npm run dev            # hot-reload dev server; proxies /api to a running `wicklight view`
```

The built `assets/` are committed so a source checkout works without a Node
build step; CI rebuilds them to verify they are current (DTN-251). The frontend
source and `node_modules/` are excluded from the wheel — only `assets/` ships.

> The timeline and step-detail components are built on this API in DTN-248 and
> DTN-249; the run list and live view in DTN-250.
