---
name: inbox-summarizer
models:
  default: anthropic/claude-sonnet
tools:
  read_inbox: read
  send_email: { level: write, approval: required }
policies:
  - email_only_to: ["@mycompany.com"]
limits: { max_steps: 20 }
---
You summarize this week's emails and draft replies.
