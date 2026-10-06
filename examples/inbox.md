---
# inbox-summarizer — read this week's inbox and draft replies.
#
# Everything above the closing `---` is a RULE the harness enforces.
# The Markdown below it is only a request the model may or may not follow.
name: inbox-summarizer

models:
  # The model that handles the run. Swap in any provider/model id.
  default: anthropic/claude-sonnet

tools:
  # Tools are OFF unless listed here. read_inbox is read-only, so it is safe.
  read_inbox: read
  # send_email can affect the outside world, so it is a "write" tool and must
  # be approved by a human before every call.
  send_email: { level: write, approval: required }

policies:
  # Checked before every tool call: email may only go to company addresses.
  # Anything else is blocked and the reason is recorded in the trace.
  - email_only_to: ["@mycompany.com"]

limits:
  # Always-on guardrail: the run stops after this many steps.
  max_steps: 20
---
You summarize this week's emails and draft replies. Only send mail to
colleagues, and ask before sending anything.
