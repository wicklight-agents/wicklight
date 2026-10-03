"""The append-only JSONL trace: the source of truth for a run.

Every model call, routing decision, policy check, approval, and tool call is
written here, one event per line, flushed per event so a crash never loses
earlier steps.
"""
