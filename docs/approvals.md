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
| `AutoApprove` | approves everything — tests and trusted headless runs |
| `AutoDeny(note)` | denies everything, with a fixed note |
| `ScriptedApprover([True, False, …])` | replays decisions in order; fails closed when it runs out |

The interactive terminal approver arrives in DTN-222.

## Fail closed

If a call needs approval and **no approver is configured**, the gate denies it
(`REQUIRE_APPROVER`) rather than running it unapproved. A bare `wicklight run`
therefore blocks approval-required calls until an approver is wired in.

## The events

- `approval_requested` — the call paused; carries the tool and the reason.
- `approval_resolved` — the decision; carries `approved`, `by` (the approver's
  name), `note` (on denial), and `duration_ms`.

A denied call is never executed; the model is told it was not approved and the
run continues. See `docs/the-loop.md` for where this sits in the pipeline.
