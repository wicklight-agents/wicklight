# Chapter 3: Order with approval

A spend cap stops a *too-big* order, but an in-budget order still happens with no
human in the loop. Ordering groceries can't be undone — so it should wait for
**you** to say yes. That's what the approval gate is for, and Wicklight turns it
on automatically for **irreversible** tools.

## Mark the tool irreversible

Bump `order_groceries` from `write` to `irreversible` in `tools.py`:

```python
@tool(
    risk=ToolRisk.IRREVERSIBLE, network_hosts=["api.grocery.example"], sensitive=False
)
async def order_groceries(order: Order, _ctx: ToolContext) -> ToolResult: ...
```

and in `planner.md` grant it at that level, explicitly requiring approval:

```yaml
tools:
  read_pantry: read
  order_groceries: { level: irreversible, approval: required }
```

`wicklight check planner.md` now lists `order_groceries` under **irreversible
tools** — Wicklight surfaces the dangerous ones so they're easy to review.

## Approve (or don't)

An irreversible call pauses for an **approver**. In a real terminal you'd get a
`Approve? [y/N]` prompt. For an unattended demo, pass an auto-approver in
`run.py`:

```python
from wicklight.core import AutoApprove

...
result = agent.run(
    "plan my dinners for the week",
    providers=dict.fromkeys(agent.model_ids, fake),
    tools={"read_pantry": read_pantry, "order_groceries": order_groceries},
    approver=AutoApprove(),  # a terminal would prompt y/N instead
    runs_dir="runs",
)
```

Write `scripts/plan.yaml` — a sensible, in-budget order:

```yaml
responses:
  - tool_calls:
      - name: read_pantry
  - tool_calls:
      - name: order_groceries
        arguments:
          items: ["bell peppers", "feta", "lemons"]
          amount_usd: 14.50
  - text: I ordered the three missing items for $14.50.
```

Run it:

```bash
python run.py scripts/plan.yaml
```

The trace now shows the gate:

```
  policy_checked      allowed: order_groceries by policy spend_limit
  approval_requested  approval requested for order_groceries
  approval_resolved   order_groceries approved by auto-approve
  tool_executed       executed order_groceries ...
```

The order passed the budget policy, **then** paused for approval, and only ran
once approved. Remove `approver=AutoApprove()` and run again: with no approver, a
non-interactive run **fails closed** — the order is denied rather than run
unattended.

> **Waivers.** If some irreversible tool is genuinely safe to auto-run, you can
> waive its approval in the agent file — but only with a written reason, which
> `check` surfaces and the trace records. Approval is the default; a waiver is a
> deliberate, documented exception.

## The lesson

- **Irreversible** tools require human approval by default; policies run first,
  so an over-budget order is blocked before anyone is even asked.
- With no approver, the gate **fails closed** — safer to do nothing than to act
  unattended.
- The whole decision — requested, by whom, approved or denied — is in the trace.

Our planner only knows the pantry so far. Let's let it look up recipes online —
and meet the risk that comes with reading the open web.
**[Chapter 4: Recipes from the web →](4-injection.md)**
