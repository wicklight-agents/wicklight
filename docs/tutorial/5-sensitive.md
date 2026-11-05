# Chapter 5: Protect allergy data

To plan safely the agent needs the cook's **allergies** — but that's private
medical information. You might be happy sending "what's in my pantry" to a hosted
model, and *not* happy sending "I'm allergic to peanuts and shellfish." Wicklight
lets you draw that line and **enforces** it: once sensitive data is in play, the
run is pinned to a model you trust with it (here, a local one), and it stops
rather than leak.

## Mark the data sensitive

Create `preferences.yaml`:

```yaml
likes: [Mediterranean, one-pan dinners]
servings: 2
allergies: [peanuts, shellfish]       # sensitive
```

Add a `read_preferences` tool whose output is **sensitive** — note
`sensitive=True`:

```python
@tool(risk=ToolRisk.READ, network_hosts=[], sensitive=True)
async def read_preferences(_input: Empty, _ctx: ToolContext) -> ToolResult:
    """Read the cook's preferences and allergies (sensitive)."""
    p = YAML(typ="safe").load(Path("preferences.yaml").read_text())
    allergies = ", ".join(p.get("allergies", [])) or "none"
    return ToolResult.success(f"Serves {p['servings']}. Allergies: {allergies}.")
```

## Route sensitive runs to a local model

In `planner.md`, declare a **route**: once the data is sensitive, use a local
model. Mark the tool sensitive there too, and grant it:

```yaml
models:
  default: openai/gpt-4o-mini
  routes:
    - when: { data: sensitive }       # once sensitive data is read...
      use: local/llama3.1             # ...pin the rest of the run to a local model
tools:
  read_pantry: read
  read_preferences: { level: read, sensitive: true }
  search_recipes: read
  order_groceries: { level: irreversible, approval: required }
```

Add `read_preferences` to `run.py`'s tools dict. Run the happy path again
(`python run.py scripts/plan.yaml`, with `read_preferences` called first) and
watch the routing in the trace:

```
  model_routed   routed to openai/gpt-4o-mini (default)
  tool_executed  executed read_preferences ... (sensitive: run now restricted ...)
  model_routed   routed to local/llama3.1 by rule 1 (data=sensitive) ...
```

Before the allergy read, the run used the default (hosted) model. The instant
`read_preferences` returns, the run **latches** into sensitive mode, and every
later model call goes to `local/llama3.1`. The allergy data never reaches a
hosted model.

And it's enforced, not just preferred: if no model were allowed for sensitive
data, the run would **stop** rather than send it somewhere it shouldn't go.

## The lesson

- A tool can mark its output **sensitive**; reading it latches the whole run.
- A `when: { data: sensitive }` **route** says which models may handle it — and
  Wicklight refuses to call any other, stopping rather than leaking.
- The latch sticks for the rest of the run, even if the sensitive text later
  scrolls out of context.

Your planner is now capable *and* careful. So far you've written all the tools
yourself — next we'll look closely at the tool contract you've been using, and
give `order_groceries` a secret it needs. **[Chapter 6: The tool contract →](6-your-tools.md)**
