---
# file-reader — answer questions about a folder, read-only.
#
# This example shows least privilege: the agent can read files but can never
# modify them, and only within an allowed path.
name: file-reader

models:
  default: anthropic/claude-sonnet

tools:
  # Read-only access. There is no write or delete tool, so the agent cannot
  # change anything on disk no matter what the model decides to do.
  read_file: read

policies:
  # Confine file access to one folder. Reads outside it are denied and logged.
  - path_allowlist: ["./docs"]

limits:
  max_steps: 15
---
You answer questions about the project's documentation. You may read files
under ./docs only.
