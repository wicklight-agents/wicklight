"""Reference tool plugins implementing the Tool contract.

Each tool is a named action with a typed input schema and a declared risk
level (read, write, irreversible). The harness applies permission checks,
approval gates, and untrusted tagging of results around every call.
"""
