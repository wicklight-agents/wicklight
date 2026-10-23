# The deploy file

A deploy file (`deploy.yaml`) says *how* to run an agent — what triggers it,
which secrets it needs, where traces go, and any extra network hosts. It is kept
separate from the agent file on purpose: the same `agent.md` runs unchanged
locally and deployed, and the deploy file holds only the operational details.

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
start) — never the value. The harness later hands each secret only to the tools
or providers that declare a need, and redaction keeps every value out of traces.

## Egress

`egress.extra_hosts` lists hosts beyond what the agent already needs. The full
allowlist — the agent's model-provider hosts and each tool's declared hosts,
plus these extras — is assembled when the container is built and enforced by the
egress proxy (M12, later milestones). Everything else is refused and logged.
