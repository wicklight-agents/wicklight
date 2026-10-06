---
# payments-agent — an agent that can move money, carefully.
#
# This example shows the strongest safety controls: an irreversible action
# behind an approval gate, plus a spend cap.
name: payments-agent

models:
  default: anthropic/claude-sonnet

tools:
  read_invoice: read
  # make_payment is IRREVERSIBLE — a payment cannot be undone. Irreversible
  # tools require human approval by default; we state it explicitly here so
  # the rule is visible in the file.
  make_payment: { level: irreversible, approval: required }

policies:
  # Defense in depth: never pay more than this without a human, even if the
  # approval step is somehow bypassed.
  - spend_limit: { max_usd: 100 }

limits:
  max_steps: 10
  max_cost: 0.50
---
You pay only invoices that are on the approved list, and you always wait for
approval before paying.
