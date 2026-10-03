"""Model routing: route rules, fallbacks, and routing decisions.

Routes live in the agent file, are evaluated top to bottom with the first
match winning, and every decision is logged with the rule that matched. The
data-sensitivity route is also a safety control.
"""
