---
# routed — one agent, several models, chosen per step.
#
# Planning (the first model call) goes to a larger model; later execution steps
# use a smaller, cheaper one; anything touching sensitive files is pinned to a
# local model and may never leave the machine. A fallback list covers provider
# outages — but a fallback is skipped if it isn't allowed for sensitive data.
name: routed-assistant

models:
  default: anthropic/claude-sonnet
  routes:
    # The first call is planning — spend a bigger model on it.
    - when: { step: planning }
      use: anthropic/claude-opus
    # Once a sensitive file is read, pin the rest of the run to the local model.
    - when: { data: sensitive }
      use: local/llama3.1
  fallback: [openai/gpt-4o, local/llama3.1]

tools:
  read_inbox: read
  # read_file's output is sensitive: reading one latches the run to local-only.
  read_file: { level: read, sensitive: true }
  send_email: { level: write, approval: required }

policies:
  - email_only_to: ["@mycompany.com"]

limits:
  max_steps: 20
---
You help with email and documents. Plan first, then act. Anything you read from
a file is confidential: once you've read one, keep working locally.
