"""Reference policy plugins implementing the Policy contract.

A policy inspects a proposed tool call and returns allow or deny with a
reason. Every policy runs before every call; denials are logged with the rule
and its source line (e.g. recipient allowlists, spend limits).
"""
