# Chapter 1: Suggest meals

An LLM call is one turn: you send text, you get text back. An **agent** is a
loop: the model can call *tools* (actions in the world), see the results, and
decide what to do next — until it's done. Wicklight runs that loop for you, and
records every step.

Let's build the smallest possible version: a planner that reads your pantry and
suggests a few dinners. One tool, read-only.

## The pantry (data)

Create `pantry.yaml` — the only thing this agent can see:

```yaml
items:
  - rice
  - eggs
  - spinach
  - chicken thighs
  - pasta
  - canned tomatoes
  - onions
  - garlic
```

## A tool (what the agent can *do*)

A tool is a Python function with a declared **risk level** and a typed input.
Create `tools.py`:

```python
from pathlib import Path
from pydantic import BaseModel
from ruamel.yaml import YAML
from wicklight.contracts import ToolContext, ToolResult, ToolRisk, tool


class Empty(BaseModel):
    pass


@tool(risk=ToolRisk.READ, network_hosts=[], sensitive=False)
async def read_pantry(_input: Empty, _ctx: ToolContext) -> ToolResult:
    """List what is currently in the pantry."""
    data = YAML(typ="safe").load(Path("pantry.yaml").read_text())
    return ToolResult.success("Pantry: " + ", ".join(data["items"]))
```

`risk=ToolRisk.READ` says this tool only reads — it can't change anything. That
declaration isn't a comment; the harness enforces it. `network_hosts=[]` says it
touches no network. Errors are *returned* as a failed `ToolResult`, never raised.

## The agent file (the rules)

An agent lives in one Markdown file: YAML frontmatter for the rules, a Markdown
body for the instructions. Create `planner.md`:

```markdown
---
name: meal-planner
models:
  default: openai/gpt-4o-mini
tools:
  read_pantry: read
---
You plan a week of simple dinners from what's already in the pantry. Suggest
three dinners that mostly use what's on hand.
```

`tools.read_pantry: read` grants the tool at the `read` level. A tool the file
doesn't list is **off** — the model can't call it even if it tries. This is least
privilege, and it's the default.

Validate the file:

```bash
wicklight check planner.md
```

It prints the effective config — every setting, tagged `(from file)` or
`(default)` — and which API key the model would need for a real run.

## Run it (offline)

You won't use a real model yet. The **fake provider** replays a script you write,
so you can watch the whole loop with no API key. Create `scripts/plan.yaml`:

```yaml
responses:
  - tool_calls:
      - name: read_pantry
  - text: >
      Three dinners: tomato pasta, a chicken-and-rice bowl, and a spinach
      frittata — all from what you have.
```

And a runner, `run.py`:

```python
import sys
from pathlib import Path
from tools import read_pantry
from wicklight.agent import Agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.trace import read_trace

agent = Agent.load("planner.md")
fake = FakeProvider(FakeScript.from_path(sys.argv[1]))
result = agent.run(
    "plan my dinners for the week",
    providers=dict.fromkeys(agent.model_ids, fake),  # fake stands in for the model
    tools={"read_pantry": read_pantry},
    runs_dir="runs",
)
for event in read_trace(result.trace_path).events:
    print(f"  {event.type:<16} {event.explain}")
```

Run it:

```bash
python run.py scripts/plan.yaml
```

## Read the trace

You'll see the loop, step by step:

```
  run_started      run started for agent meal-planner
  context_built    built context with 2 messages
  model_called     called openai/gpt-4o-mini
  model_responded  model responded (tool_use) ...
  tool_proposed    model proposed read_pantry
  tool_executed    executed read_pantry in 1ms
  context_built    built context with 4 messages
  model_called     called openai/gpt-4o-mini
  model_responded  model responded (stop) ...
  run_finished     run finished: completed in 2 steps
```

That's the agent loop: **model → tool → model**. The model asked to read the
pantry; the tool ran; its result went back into the context; the model wrote the
plan and stopped. Open the same run in the viewer to click through it:

```bash
wicklight view runs/<run-id>      # the run-id is printed in the trace path
```

## The lesson

- An **agent** is a loop of model calls and tool calls, not a single prompt.
- Tools declare what they can do (`risk`, `network_hosts`); the agent file grants
  them explicitly, and everything else is **off** — least privilege by default.
- Every step is one line in the **trace** — the source of truth you'll lean on
  for the rest of this tutorial.

Next, we'll let the planner build a shopping list — and put a cap on what it can
spend. **[Chapter 2: Shop on a budget →](2-budget.md)**
