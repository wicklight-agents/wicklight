# Deploying an agent

`wicklight deploy` turns an agent and its `deploy.yaml` into a **sealed,
controllable container**: a non-root, shell-less image on an internal network
with no direct route to the internet, an egress proxy as the only way out, and a
host CLI to trigger, inspect, approve, and stop it. The same image runs on your
laptop and on a hosted container service (ECS, Fly, Cloud Run) unchanged.

This page is the end-to-end walkthrough; see [the deploy file](./deploy-file.md)
for the `deploy.yaml` reference.

## Architecture

```
 host (your machine or CI)
 ┌───────────────────────────────────────────────────────────────┐
 │  wicklight CLI                                                 │
 │   deploy / trigger / ps / logs / stop / approve / undeploy     │
 │        │                         ▲                             │
 │        │ docker|podman           │ reads traces + approvals    │
 │        ▼                         │ (shared volume)             │
 │  container engine           ┌────┴───────────┐                 │
 │   ┌─────────────────────────┤  traces volume ├───────────────┐ │
 │   │  internal network (no internet route)    │  ./runs       │ │
 │   │   ┌───────────────┐      └───────┬────────┘               │ │
 │   │   │  agent        │  HTTPS_PROXY  │  run_*.jsonl           │ │
 │   │   │  (supervisor) ├───────────────┼──► egress proxy ───────┼─┼──► allowed
 │   │   │  non-root     │   CONNECT     │    (sidecar)           │ │     hosts
 │   │   │  read-only FS │               │    allowlist-enforced  │ │
 │   │   └───────────────┘               │    egress.jsonl ◄──────┼─┼── denied
 │   └───────────────────────────────────┘    (refused + logged) │ │   (refused)
 │                                                                │ │
 └────────────────────────────────────────────────────────────────┘
```

- The **agent/supervisor** container runs on an **internal** network — it has no
  direct internet route. It stays up between runs and executes each trigger as
  its own trace.
- The **egress proxy** sidecar is on both the internal network and an external
  one, so it is the only path out. The agent is pointed at it via `HTTPS_PROXY`;
  allowed hosts tunnel through, everything else is refused and logged.
- The **traces volume** (`./runs`) is the shared channel: the agent writes
  traces there, the proxy writes refusals there, and the host CLI reads traces
  and exchanges approvals through it.

## Walkthrough

```bash
# 1. Build and start the sealed deployment (see `check` for the egress allowlist).
uv run wicklight check examples/deploy.yaml
uv run wicklight deploy examples/deploy.yaml

# 2. See it running; trigger a run by hand.
uv run wicklight ps
uv run wicklight trigger inbox-summarizer "summarize my inbox"

# 3. Read the latest run; open it in the viewer.
uv run wicklight logs inbox-summarizer
uv run wicklight view runs/<run-id>

# 4. Resolve any pending approval from the host; stop with the kill switch.
uv run wicklight approve inbox-summarizer
uv run wicklight stop inbox-summarizer       # records run_finished: killed
uv run wicklight undeploy inbox-summarizer   # removes containers; keeps traces
```

Triggers (`schedule`, `webhook`, `manual`) are configured in the deploy file and
recorded in each run's `run_started.trigger`. `--no-egress-proxy` runs a single
container without the sealed network — for local development only.

## What's enforced

The integration tests (`pytest -m docker`) prove, against a real deployment:

- the image is **non-root**, has **no shell**, and runs with a **read-only root
  filesystem** (only the trace mount is writable);
- a **disallowed host is refused and logged** (`egress_denied`) by the proxy;
- **secrets never appear** in a trace, even in error paths;
- the **kill switch** stops a run mid-flight and records `run_finished: killed`.

These run in CI with Docker, and a scheduled Podman job runs the same suite.

## Hosted container services

Because the deployment is one self-contained OCI image, the image and its
triggers move to ECS, Fly, Cloud Run, or Kubernetes unchanged — the platform is
the orchestrator. The host control CLI (`ps`/`logs`/`stop`/`approve`) is
Docker/Podman-first today; on a hosted platform you stop and inspect through that
platform's own tooling. A remote control plane is a planned follow-on.
