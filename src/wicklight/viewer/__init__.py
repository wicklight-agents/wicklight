"""The local web viewer that renders a trace as a timeline.

Reads the same JSONL file as the CLI, needs no server or account, and shares
its components with the game's replay viewer. Each step expands to show the
model's context, routing decision, policy checks, and tool results.
"""
