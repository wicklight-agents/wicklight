# Approvals

Approval is the **final stage** of the check pipeline (`wicklight.core.approval`,
DTN-221). After permissions and policies pass, a call that needs human sign-off
pauses the loop until an `Approver` decides.

## When a call needs approval

A tool needs approval if the agent file lists it `approval: required`, or if it
is `irreversible` and not explicitly waived (the safe default). `wicklight check`
shows which tools require approval, and the approval reason is recorded on the
`approval_requested` event.

## The `Approver` interface

```python
class Approver(Protocol):
    name: str  # who/what decided, recorded on approval_resolved

    async def request(self, request: ApprovalRequest) -> Approved | Denied: ...
```

An approver is a pure decision maker: given an `ApprovalRequest` (the tool, its
arguments, and why approval is needed) it returns `Approved()` or
`Denied(note)`. It cannot run tools or change arguments. `request` is async so
an interactive approver (a terminal prompt, a webhook) fits the same interface
as the instant test approvers.

## Built-in approvers

| Approver | Behaviour |
| --- | --- |
| `TerminalApprover` | the v1 human approver (DTN-222): prompts `Approve? [y/N]` at the terminal, default deny, with a timeout that also defaults to deny; used by `wicklight run` |
| `AutoApprove` | approves everything — tests and trusted headless runs |
| `AutoDeny(note)` | denies everything, with a fixed note |
| `ScriptedApprover([True, False, …])` | replays decisions in order; fails closed when it runs out |

### `TerminalApprover`

`wicklight run` uses it by default. It shows the tool, its pretty-printed
arguments, risk level, and why approval is needed, then asks for a decision; a
denial can carry an optional note back to the model. When the run is **not
attached to a TTY** (piped output, CI), it denies immediately and says why
rather than blocking on a prompt that can't appear. The library `agent.run()`
default stays fail-closed (below); pass `TerminalApprover()` explicitly to opt in.

## Waivers

An irreversible tool requires approval by default. The agent file can waive that
default for a specific tool — but only with a **written reason** (DTN-223):

```yaml
tools:
  purge: { level: irreversible, waive_approval: true, reason: "nightly scratch cleanup" }
```

`wicklight check` rejects a waiver with no reason and lists every waiver (with
its reason) prominently. A waived call is **not** sent to an approver, but it is
still recorded: the trace gets an `approval_resolved` event with `waived: true`,
`by: "waiver"`, and the reason as its note — so a waiver is always auditable.

A waiver only lifts the irreversible **default**. A tool marked
`approval: required` is gated regardless, and an explicit requirement wins over a
waiver on the same tool.

## Fail closed

If a call needs approval and **no approver is configured**, the gate denies it
(`REQUIRE_APPROVER`) rather than running it unapproved. So `agent.run()` without
an approver blocks approval-required calls, and a non-interactive `wicklight run`
denies them with a clear message.

## The events

- `approval_requested` — the call paused; carries the tool and the reason.
- `approval_resolved` — the decision; carries `approved`, `by` (the approver's
  name), `note` (on denial), and `duration_ms`.

A denied call is never executed; the model is told it was not approved and the
run continues. See `docs/the-loop.md` for where this sits in the pipeline.

## The payment-approval demo

The worked example (DTN-224) pays an invoice from the inbox with
`examples/payments.md`, whose `make_payment` is irreversible and
`approval: required`:

```bash
uv run wicklight run examples/payments.md "pay the invoice" \
  --fake examples/scripts/pay_invoice.yaml \
  --world examples/worlds/invoice.yaml --trace
```

At a terminal this pauses for `Approve? [y/N]`: `y` records the $50 payment in
the ledger; `N` (or a non-interactive run) blocks it and tells the model. A
payment over the `spend_limit` is denied by the policy before approval is ever
requested, since policies run before the gate.
