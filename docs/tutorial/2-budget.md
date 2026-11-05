# Chapter 2: Shop on a budget

Suggesting meals is safe — nothing happens in the world. Now we'll let the
planner build a **grocery list and order it**, which spends money. The first
question any sensible system should ask: *what stops it from spending too much?*

In Wicklight the answer is a **policy** — a pure allow/deny check that runs
before every tool call. We'll add the `spend_limit` policy and watch it block an
over-budget cart.

## Add an ordering tool

Add `order_groceries` to `tools.py`. For now it's a `write` tool (it changes the
world, but we'll make it safer in the next chapter):

```python
class Order(BaseModel):
    items: list[str]
    amount_usd: float


@tool(risk=ToolRisk.WRITE, network_hosts=["api.grocery.example"], sensitive=False)
async def order_groceries(order: Order, _ctx: ToolContext) -> ToolResult:
    """Place a grocery order."""
    cart = ", ".join(order.items)
    return ToolResult.success(f"Ordered {cart} for ${order.amount_usd:.2f}.")
```

Notice `amount_usd` in the input — the `spend_limit` policy looks for exactly
that.

## Add the tool and the policy

Update `planner.md`:

```markdown
---
name: meal-planner
models:
  default: openai/gpt-4o-mini
tools:
  read_pantry: read
  order_groceries: write
policies:
  - spend_limit: { max_usd: 60 }
limits:
  max_steps: 15
---
You plan a week of simple dinners from what's in the pantry, then build a
grocery list for anything missing. Stay within the grocery budget.
```

`wicklight check planner.md` now shows the `spend_limit` policy under
`policies:`.

Register the new tool in `run.py` by passing both to `tools=`:

```python
tools = {"read_pantry": read_pantry, "order_groceries": order_groceries}
```

## Watch it get blocked

Write `scripts/over_budget.yaml` — the model proposes a lavish cart:

```yaml
responses:
  - tool_calls:
      - name: read_pantry
  - tool_calls:
      - name: order_groceries
        arguments:
          items: ["wagyu beef", "saffron", "truffle oil"]
          amount_usd: 180.00
  - text: That cart was over budget, so it was blocked. Nothing was ordered.
```

Run it:

```bash
python run.py scripts/over_budget.yaml
```

In the trace:

```
  tool_proposed    model proposed order_groceries
  policy_checked   blocked: order_groceries by policy spend_limit —
                   order_groceries of $180.00 would exceed the per-run limit of $60.00 ...
```

The order **never ran**. The policy denied it, the denial names the rule and the
dollar amounts, and the model is told so it can choose a cheaper plan.

## The lesson

- A **policy** is a pure allow/deny check that runs *before* a tool call; the
  first `deny` stops it, and the trace cites the policy.
- Policies **fail closed** and run on *every* call — `spend_limit` even tracks the
  running total, so three small carts can't sneak past the cap.
- The rule lives in the agent file, not the prompt. The model can't talk its way
  around a `spend_limit`.

The cart is capped — but the agent still placed an order on its own. Next, we'll
require a human to sign off first. **[Chapter 3: Order with approval →](3-approval.md)**
