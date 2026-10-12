# Policies

A **policy** is a pure allow/deny decision over a tool call the model proposed.
Policies are the third extension point (`wicklight.policies`), alongside
providers and tools, and live in `wicklight.policies`. The contract is in
`src/wicklight/contracts/policy.py` (DTN-216); evaluation in the core loop is
DTN-217; the built-ins are DTN-218.

## The contract

```python
class Policy(Protocol):
    name: str
    config_model: type[BaseModel]            # typed, validated config
    def check(self, call: PolicyCall, ctx: PolicyContext) -> Allow | Deny: ...
```

A policy is a **pure decision**: `check` is synchronous, side-effect free, and
deterministic. It may inspect the call (`tool`, `arguments`, `risk`) and the
read-only `PolicyContext` (`run_id`, `spent_usd`, `agent_dir`), but it must not
execute tools, change arguments, or disable other checks. A `Deny` always
carries a human-readable reason. Every policy must pass the conformance kit
(`wicklight.testing.run_policy_conformance`), which checks exactly these
guarantees — a side-effecting or non-deterministic policy fails it.

## How the loop evaluates them

Policies are configured by name in the agent file's `policies:` list and run as
a fixed step in the core loop, **after** the permission check and **before** a
tool executes:

```
permission check -> validate arguments -> policies (in file order) -> execute
```

- Policies run in the order they appear in the agent file.
- The **first deny blocks the call**; later policies are not evaluated.
- Every result — allow and deny — is recorded as a `policy_checked` event. A
  deny cites the policy and its agent-file line, e.g.
  `blocked: send_email by policy email_only_to — … (agent.md line 22)`.
- **Fail closed:** a policy that raises counts as a deny and is also recorded as
  an `error`. A buggy policy can never silently let a call through.

A blocked call is never executed; the model is told it was blocked and the run
continues.

## Built-in policies

| Policy | Applies to | Config | Blocks |
| --- | --- | --- | --- |
| `email_only_to` | calls with a recipient (`to`, `recipient`, …) | list of addresses/domains (`@acme.com` = whole domain, case-insensitive) | recipients not on the allowlist |
| `paths_within` | calls with a path (`path`, `file`, …) | list of root directories | paths resolving outside the roots (`..` and symlinks resolved first) |
| `spend_limit` | calls with an amount (`amount_usd`, …) | `{ max_usd, per_call_usd }` | a payment over the per-call cap, or one that pushes the running total over `max_usd` |

`max_usd` is a **per-run** cap: the loop accumulates the amount of each executed
call, so three small payments that together exceed the cap are blocked
(defeating split payments).

### Agent-file examples

```yaml
policies:
  - email_only_to: ["@acme.com", "ceo@partner.com"]
  - paths_within: ["./docs"]
  - spend_limit: { max_usd: 100, per_call_usd: 50 }
```

See `examples/inbox.md`, `examples/files.md`, and `examples/payments.md` for
complete agent files. A minimal reference policy, `block_tools`, lives in
`src/wicklight/policies/block_tools.py`.
