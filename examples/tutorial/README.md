# Meal-planner tutorial project

The finished project for the capstone tutorial,
[**Build a meal-planning agent**](https://wicklight-agents.github.io/wicklight/tutorial/).
Follow the tutorial to build it yourself from an empty folder; this is the
reference you can compare against (and what the test suite runs).

| File | What it is |
| --- | --- |
| `planner.md` | the finished agent file (models, routes, tools, policies) |
| `tools.py` | the four tools, built from scratch (read_pantry, read_preferences, search_recipes, order_groceries) |
| `pantry.yaml`, `preferences.yaml`, `recipes.yaml` | the data the tools read (preferences holds the sensitive allergies; recipes holds a planted injection) |
| `scripts/*.yaml` | scripted model runs for the fake provider: the happy path, an over-budget cart, and a prompt injection |
| `run.py` | runs the agent on the fake provider — no API key |
| `deploy.yaml` | the deployment (weekly schedule, secret, egress) for chapter 7 |

Run it offline:

```bash
cd examples/tutorial
python run.py scripts/plan.yaml          # the happy path
python run.py scripts/over_budget.yaml   # watch spend_limit block it
python run.py scripts/injected.yaml      # watch an injection get contained
```
