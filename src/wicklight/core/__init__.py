"""The fixed agent loop and safety enforcement.

The loop, permission checks, untrusted-content tagging, the approval gate,
limits, and trace writing live here and cannot be replaced by a plugin. This
is the only place tool calls happen, so safety checks can never be skipped.
"""
