# The deploy file

A deploy file (`deploy.yaml`) says *how* to run an agent — what triggers it,
which secrets it needs, where traces go, and any extra network hosts. It is kept
separate from the agent file on purpose: the same `agent.md` runs unchanged
locally and deployed, and the deploy file holds only the operational details.

> For the end-to-end walkthrough and the architecture diagram, see
> [Deploying an agent](./deploying.md). This page is the `deploy.yaml` reference.

```yaml
name: inbox-summarizer
agent: agent.md            # path to the agent file, relative to this file

triggers:
  - schedule: "0 8 * * 1-5"   # a 5-field cron expression
  - webhook: { path: /run }   # a local HTTP endpoint

secrets:
  EMAIL_TOKEN: { from: env }  # from env, file, or keychain

traces: ./runs

egress:
  extra_hosts: []             # beyond the agent's model and tool hosts
```

Validate it the same way as an agent file:

```bash
uv run wicklight check examples/deploy.yaml
```

`check` treats a `.yaml`/`.yml` file as a deploy file: it validates the deploy
file **and** its agent file together, then prints the effective deployment —
triggers, each secret's status (set or missing, **never its value**), and the
egress hosts. Errors read just like agent-file errors, line-numbered and all at
once:

```
deploy.yaml line 3: unexpected key 'triggerz'. Did you mean 'triggers'?
deploy.yaml: 'agent' is required.
```

## Fields

| Field | Meaning |
| --- | --- |
| `name` | A name for the deployment. |
| `agent` | Path to the agent file, relative to the deploy file. Validated too. |
| `triggers` | A list; each entry has **exactly one** of `schedule` (cron) or `webhook` (`{ path }`). |
| `secrets` | A map of name → `{ from: env \| file \| keychain, name?, path? }`. A `file` secret needs a `path`. |
| `traces` | Where run traces are written. |
| `egress.extra_hosts` | Extra hosts the agent may reach, on top of its model-provider and tool hosts. |

## Secrets

Secret *values* are never written in the deploy file and never printed. Each
secret names where its value is resolved from on the host at start:

- `from: env` — an environment variable (`name`, defaulting to the secret's key).
- `from: file` — a file at `path` (relative to the deploy file).
- `from: keychain` — the OS keychain (`name`, defaulting to the key).

`check` reports each as `set`, `MISSING`, or `deferred` (keychain, checked at
start) — never the value. At run time the values are resolved on the host and
injected into the container as **runtime environment**, never baked into the
image. Inside, the harness holds them and hands each secret only to the tools
that declare it via `required_secrets`; redaction keeps every value out of
traces, even in error messages. A missing secret fails fast at start, naming
every one.

## Building the image

`wicklight deploy` builds a locked-down container image for a deployment — no
Dockerfile to write:

```bash
uv run wicklight deploy examples/deploy.yaml                 # build the image
uv run wicklight deploy examples/deploy.yaml --print-dockerfile   # just show it
uv run wicklight deploy examples/deploy.yaml --engine podman      # force an engine
```

It detects Docker or Podman (whichever is installed), then builds a two-stage
image: dependencies are installed with `uv`, then copied into a hardened Google
**distroless** runtime that has **no shell and no package manager**, runs as a
**non-root** user, and is built to run with a **read-only root filesystem** (only
the trace directory is a writable mount). The agent file and deploy file are
baked in read-only; **secret values never are**. The image is a standard OCI
image, tagged `wicklight-<name>:<content-hash>`.

> Building currently needs a Wicklight source checkout; once Wicklight is on
> PyPI (the 0.1 release), the image will install it by version.

## Running and controlling a deployment

`wicklight deploy` builds the image **and starts it** — one long-lived
*supervisor* container per agent that stays up between runs, hosts the webhook
endpoint and the cron scheduler inside the sealed container, and runs each
trigger as its own trace. Because it is the same image everywhere, it runs the
same on your laptop (`docker run`) and on a hosted container service (ECS, Fly,
Cloud Run). `--build-only` stops after the build.

**Triggers** (each run records which one fired, in `run_started.trigger`):

- **manual** — `wicklight trigger <name> "<task>"` starts a run now.
- **schedule** — the cron expressions in `triggers`; the supervisor fires them
  internally (minute granularity).
- **webhook** — a `POST` to the webhook path starts a run with the request body
  as the task; it requires a shared-secret token (`X-Wicklight-Token`,
  `WICKLIGHT_WEBHOOK_TOKEN`) and is published to host loopback with
  `--webhook-port`.

When a trigger fires mid-run, the deploy file's `overlap` policy decides: `skip`
(the default — drop it), `queue` (run it next), or `allow` (run concurrently).

**Host control** (Docker/Podman-first; a remote control plane for ECS/Fly is a
follow-on):

| Command | What |
| --- | --- |
| `wicklight ps` | deployed agents, status, last run, pending approvals |
| `wicklight logs <name>` | the deployment's latest run trace (the `run` renderer) |
| `wicklight stop <name>` | the **kill switch** — stops the run now and records `run_finished` with reason `killed`; traces are kept |
| `wicklight approve <name>` | resolve a deployed run's pending approvals from the terminal (requests time out to deny) |
| `wicklight undeploy <name>` | remove the container; keep the traces |

A deployed run has no terminal, so approvals cross the boundary as files in the
shared trace volume: the run writes a request, `wicklight approve` writes the
decision, and an unanswered request times out to a denial (fail closed).

## Egress

The agent container has **no direct route to the internet**; a small egress
proxy running alongside it is the only way out. Its allowlist is derived
automatically — never hand-maintained:

- the **model-provider hosts** for every model the agent can route to (default,
  routes, and fallback),
- the **hosts each enabled tool declares** via `network_hosts`,
- plus `egress.extra_hosts` from the deploy file.

`wicklight check <deploy>.yaml` prints the full allowlist with each host's source:

```
egress allowlist:
  api.anthropic.com (provider:anthropic)
  hooks.example.com (tool:notify)
  events.example.com (extra_hosts)
  (every other host is refused and logged)
```

Allowed HTTPS connections are tunnelled straight through (`CONNECT`, no TLS
interception). **Any other host is refused** with `403` and recorded as an
`egress_denied` trace event (host, port, time) — something a plain firewall rule
cannot do. The proxy sidecar runs `python -m wicklight.deploy.proxy`, configured
with `WICKLIGHT_EGRESS_ALLOW`; wiring it onto an internal-only container network
lands with the deployment run (later M12 tickets).
