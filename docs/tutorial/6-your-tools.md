# Chapter 6: The tool contract

You've written four tools without dwelling on how they work. Let's slow down,
because the `@tool` decorator is a small, deliberate **contract** — and getting it
right is most of what makes an agent safe. Then we'll give `order_groceries` the
one thing it's still missing: a credential, handled so the model never sees it.

## What every tool declares

```python
@tool(
    risk=ToolRisk.IRREVERSIBLE,  # read < write < irreversible
    network_hosts=["api.grocery.example"],  # hosts it may reach
    sensitive=False,  # does its output latch the run?
    required_secrets=["STORE_TOKEN"],  # secrets the harness hands it
)
async def order_groceries(order: Order, ctx: ToolContext) -> ToolResult: ...
```

Each field is a promise the harness enforces:

- **`risk`** gates the tool behind the agent file's permission level and the
  approval rules. An `irreversible` tool can't run without approval or a waiver.
- **`network_hosts`** is the set of hosts the tool legitimately needs. In
  [chapter 7](7-deploy.md) this becomes the deployment's egress allowlist —
  anything else is refused and logged.
- **`sensitive`** (chapter 5) latches the run to sensitivity-allowed models.
- **`required_secrets`** names the credentials the tool needs. The harness hands
  it **only** those, the model never sees them, and redaction keeps their values
  out of the trace — even inside an error message.
- The **input** is a Pydantic model (`Order` here), so arguments are validated
  before your code runs. Invalid arguments are refused automatically.

Errors are **returned**, never raised: a tool that fails returns
`ToolResult.failure("...")`, which the model sees and can react to. A tool that
raises is caught and surfaced to the model, not crashed into the user.

## Give the tool its secret

`order_groceries` needs a store token to place an order. It asks for it by name,
and reads it from the context the harness provides:

```python
@tool(
    risk=ToolRisk.IRREVERSIBLE,
    network_hosts=["api.grocery.example"],
    sensitive=False,
    required_secrets=["STORE_TOKEN"],
)
async def order_groceries(order: Order, ctx: ToolContext) -> ToolResult:
    token = ctx.secret("STORE_TOKEN")  # the model never sees this value
    cart = ", ".join(order.items)
    # ... use `token` to call the store API ...
    return ToolResult.success(f"Ordered {cart} for ${order.amount_usd:.2f}.")
```

Supply the secret when you run — the harness holds it and hands it only to tools
that declared it:

```python
result = agent.run(
    "plan my dinners for the week",
    providers=dict.fromkeys(agent.model_ids, fake),
    tools={
        "read_pantry": read_pantry,
        "read_preferences": read_preferences,
        "search_recipes": search_recipes,
        "order_groceries": order_groceries,
    },
    secrets={"STORE_TOKEN": "test-token"},  # held by the harness, not the model
    approver=AutoApprove(),
    runs_dir="runs",
)
```

Run any scenario and inspect the trace: the token appears **nowhere** in it, even
though `order_groceries` used it. A tool that *doesn't* declare `STORE_TOKEN`
would be handed nothing — it can't reach a secret it didn't ask for.

## The lesson

- The tool contract — `risk`, `network_hosts`, `sensitive`, `required_secrets`,
  and a typed input — is where you decide exactly what a tool may do.
- Secrets are **held by the harness**: handed only to tools that declare them,
  never shown to the model, never written to a trace.
- These declarations aren't paperwork — the next chapter turns them directly into
  a deployment's network and secret policy.

Your project is complete and safe. Let's ship it: a container that plans your
week every Sunday, sealed off from everything it doesn't need. **[Chapter 7:
Deploy it →](7-deploy.md)**
