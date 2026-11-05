---
# meal-planner — the capstone tutorial's finished agent.
#
# It reads the pantry and the cook's preferences, suggests a week of dinners,
# and can order the groceries — but only within budget, only with your approval,
# and keeping allergy data on a local model.
name: meal-planner

models:
  default: openai/gpt-4o-mini
  routes:
    # Allergies are sensitive: once read_preferences runs, pin the rest of the
    # run to a local model so medical data never leaves the machine.
    - when: { data: sensitive }
      use: local/llama3.1

tools:
  read_pantry: read
  # Allergies are medical info — mark the output sensitive.
  read_preferences: { level: read, sensitive: true }
  # Reads the web, so its output is untrusted (tagged automatically).
  search_recipes: read
  # Spends money and can't be undone: irreversible + approval.
  order_groceries: { level: irreversible, approval: required }

policies:
  # Never spend more than the weekly grocery budget.
  - spend_limit: { max_usd: 60 }

limits:
  max_steps: 15
---
You plan a week of simple dinners from what's already in the pantry and the
cook's preferences, then build a grocery list for anything missing. Read the
cook's allergies before suggesting anything, and never suggest a dish that
contains an allergen. Stay within the grocery budget. List the cart before
ordering, and never order without it being approved.
