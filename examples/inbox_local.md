---
# inbox-summarizer-local — the inbox example, run against a local model.
#
# Same safety rules as inbox.md, but the model is served locally (Ollama or any
# OpenAI-compatible server) instead of a hosted API. No API key is needed.
name: inbox-summarizer-local

models:
  # `local/<model>` uses the OpenAI-compatible adapter. By default it talks to
  # Ollama at http://localhost:11434/v1; override with OPENAI_BASE_URL.
  default: local/llama3.1

tools:
  read_inbox: read
  send_email: { level: write, approval: required }

policies:
  - email_only_to: ["@mycompany.com"]

limits:
  max_steps: 20
---
You summarize this week's emails and draft replies. Only send mail to
colleagues, and ask before sending anything.
