# Chapter 7: Deploy it

Your planner works. The last step is to make it *run on its own* — every Sunday
morning, sealed in a container that can reach only the hosts it needs, with its
secret injected at start and never baked in. That's `wicklight deploy`.

> **This chapter needs Docker** (or Podman). Everything before it ran offline
> with no container. If you don't have Docker, read along — the concepts are the
> payoff of everything you declared in the earlier chapters.

## Package your tools

A deployed container discovers tools through **entry points**, so your tools need
to be an installable package. Put `tools.py` in a package and add a tiny
`pyproject.toml`:

```toml
[project]
name = "meal-planner"
version = "0.1.0"
dependencies = ["wicklight"]

[project.entry-points."wicklight.tools"]
read_pantry = "meal_planner.tools:read_pantry"
read_preferences = "meal_planner.tools:read_preferences"
search_recipes = "meal_planner.tools:search_recipes"
order_groceries = "meal_planner.tools:order_groceries"
```

Now `wicklight` can find your tools by name — the same names your agent file
grants — without you injecting them in Python.

## Describe the deployment

A `deploy.yaml` says *how* to run the agent, kept separate from the agent itself:

```yaml
name: meal-planner
agent: planner.md

triggers:
  - schedule: "0 8 * * 0"        # every Sunday at 08:00

secrets:
  STORE_TOKEN: { from: env }     # resolved on the host, injected at start

traces: ./runs
```

Check it — and notice the **egress allowlist**, derived automatically from your
models and your tools' `network_hosts`:

```bash
wicklight check deploy.yaml
```

```
egress allowlist:
  api.openai.com (provider:openai)
  localhost (provider:local)
  recipes.example.com (tool:search_recipes)
  api.grocery.example (tool:order_groceries)
  (every other host is refused and logged)
```

Every host comes from a declaration you already wrote. Anything else the agent
tries to reach is refused and recorded as an `egress_denied` event.

## Deploy and control it

```bash
export STORE_TOKEN=...            # the real store credential
wicklight deploy deploy.yaml      # builds a locked-down image and starts it
```

`deploy` builds a **non-root, shell-less** container with a **read-only root
filesystem** (only the trace volume is writable), on an **internal network** with
no direct internet route — the egress proxy is its only way out. Then control it
from the host:

```bash
wicklight ps                      # deployed agents, status, pending approvals
wicklight trigger meal-planner "plan this week"   # run it now, by hand
wicklight logs meal-planner       # read the latest run's trace
wicklight approve meal-planner    # resolve a pending order approval
wicklight stop meal-planner       # the kill switch — records a killed run
wicklight undeploy meal-planner   # remove it; your traces are kept
```

The schedule fires every Sunday; `trigger` runs it on demand; and because it's
the same image everywhere, you can hand it to a hosted container service (ECS,
Fly, Cloud Run) unchanged. See [Deploying an agent](../deploying.md) for the full
architecture.

## You built an agent

Look back at what you assembled — and the safety feature each step demanded:

| You added | It's safe because |
| --- | --- |
| A read-only planner | least privilege — tools are **off** unless granted |
| A grocery order | a **policy** (`spend_limit`) caps the spend, failing closed |
| An irreversible order | an **approval gate** — a human signs off |
| Reading the web | **untrusted tagging** — injected text is data, not orders |
| Allergy data | **sensitivity routing** — private data stays on a local model |
| Your own tools | the **tool contract** — risk, hosts, and secrets, enforced |
| A deployment | a **sealed container** with an egress allowlist and a kill switch |

None of it lived in the prompt. The model can be wrong, slow, or outright
manipulated, and the blast radius is still contained — and every decision is one
line in a trace you can read.

That's the whole idea of Wicklight. When you outgrow it, take these habits with
you: see [Graduating](../graduating.md) for how each concept maps onto bigger
tools. Happy building.
