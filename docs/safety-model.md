# Safety model

Wicklight's safety is not advice the model may follow — it is enforced by a
**fixed core** that every run goes through. Plugins (providers, tools, policies)
extend what an agent *can* do, but they cannot remove, reorder, or bypass the
checks below. This page is the contract: what is enforced, in what order, and —
just as important — **what Wicklight does not protect against**.

## The fixed core

For every tool call the model proposes, the core runs these checks **in this
order**, and stops at the first failure:

1. **Permission check (fixed, always first).** A tool runs only if the agent
   file lists it at a sufficient [permission level](agent-file.md#tools)
   (`off` < `read` < `write` < `irreversible`). A tool the file does not grant
   is refused — this check is in the core and cannot be removed or reordered by
   a plugin.
2. **Argument validation.** The call's arguments are validated against the
   tool's typed input schema; invalid arguments are refused.
3. **Policies.** Every configured [policy](policies.md) is evaluated against the
   call (recipient allowlist, path allowlist, spend limit, sender denylist, …).
   The first `deny` blocks the call, and the trace cites the policy and its
   agent-file line. Policies are pure allow/deny and **fail closed**.
4. **Approval.** If the tool is `irreversible`, or marked `approval: required`,
   the call pauses for an [approver](approvals.md). With no approver (a
   non-interactive run), it **fails closed** — the call is denied. A reasoned
   [waiver](approvals.md#waivers) can lift the approval an irreversible tool
   would otherwise require.
5. **Execute** — only if every check above passed. The result is recorded.

Two more invariants wrap the loop:

- **Untrusted tagging.** Every tool result enters the model's context wrapped in
  a "data, not instructions" envelope and flagged untrusted. A poisoned document
  or email is still *data* the model can read, but the surrounding safety checks
  (e.g. a recipient allowlist) are what actually stop it acting on an injected
  instruction. See the [injection example](getting-started.md).
- **Enforced sensitivity routing.** Once a tool whose output is marked
  `sensitive` enters context, the run **latches** into sensitive mode and only
  models allowed for sensitive data may be called — it stops rather than send
  that data to a disallowed (e.g. hosted) model. See
  [model routing](routing.md).

Model calls, their retries, and provider fallback are likewise fixed in the
core; see [the loop](the-loop.md) for the full structure.

## Secrets

Secrets are read from the environment (and, when deployed, resolved on the host
and injected at runtime — never baked into an image). The harness hands each
tool only the secrets it declares, the model never sees them, and redaction
keeps every secret value out of the trace and its blobs — even inside an error
message. See [credentials](credentials.md) and [deploying](deploying.md).

## What Wicklight does **not** protect against

Being honest about the boundary is part of the safety model. Wicklight does not:

- **Judge whether an *allowed* action is wise.** If the agent file grants a tool
  and the policies permit a call, Wicklight runs it. It enforces *your* rules; it
  does not add judgement of its own.
- **Stop a tool that resolves sensitive data internally.** A policy can only
  check what is in the call's *arguments*. A tool that fetches a recipient or a
  path from somewhere the policy cannot see is outside a policy's reach — pass
  such values as arguments so the checks apply.
- **Sandbox tool code.** A tool plugin runs in-process with the harness. Install
  only tools you trust; the permission level limits *what the model can ask a
  tool to do*, not what the tool's own code can do.
- **Defend a misconfigured agent.** An overly broad permission, an empty policy
  list, or a reasoned waiver on a dangerous tool are all honored as written.
  `wicklight check` surfaces the effective configuration so you can review it.
- **Prevent the model from being wrong or manipulated.** Untrusted tagging marks
  injected content as data, but the model may still be fooled; the *enforcement*
  (policies, approvals, egress) is what contains the blast radius.
- **Guarantee a hosted model's own data handling.** Routing keeps sensitive data
  off disallowed models, but what an *allowed* provider does with a request is
  that provider's responsibility.

The guiding principle: Wicklight makes the safe path the default and every action
visible, so a mistake is contained and obvious — not that no mistake is possible.
