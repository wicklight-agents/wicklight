"""The meal-planner's tools — the capstone tutorial builds these from scratch.

Four tools, each declaring exactly what it can do:

- ``read_pantry`` and ``read_preferences`` are read-only. ``read_preferences``
  is marked ``sensitive`` because allergies are medical information: once it runs,
  the agent file routes the rest of the run to a local model.
- ``search_recipes`` reads "the web" (here, recipes.yaml). Its output is
  untrusted — a page may carry an injected instruction.
- ``order_groceries`` is irreversible (it spends money) and carries an
  ``amount_usd`` the ``spend_limit`` policy checks. It needs the STORE_TOKEN
  secret, which the harness injects and the model never sees.

The tools read their data from this file's directory, so the project works from
anywhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel
from ruamel.yaml import YAML

from wicklight.contracts import ToolContext, ToolResult, ToolRisk, tool

_DATA = Path(__file__).parent


def _load(name: str) -> dict[str, Any]:
    yaml = YAML(typ="safe")
    return cast("dict[str, Any]", yaml.load((_DATA / name).read_text()) or {})


# --- input schemas ------------------------------------------------------------


class Empty(BaseModel):
    pass


class RecipeQuery(BaseModel):
    query: str


class Order(BaseModel):
    items: list[str]
    amount_usd: float


# --- the tools ----------------------------------------------------------------


@tool(risk=ToolRisk.READ, network_hosts=[], sensitive=False)
async def read_pantry(_input: Empty, _ctx: ToolContext) -> ToolResult:
    """List what is currently in the pantry."""
    items = _load("pantry.yaml").get("items", [])
    return ToolResult.success("Pantry: " + ", ".join(items))


@tool(risk=ToolRisk.READ, network_hosts=[], sensitive=True)
async def read_preferences(_input: Empty, _ctx: ToolContext) -> ToolResult:
    """Read the cook's preferences and allergies (sensitive)."""
    prefs = _load("preferences.yaml")
    allergies = ", ".join(prefs.get("allergies", [])) or "none"
    likes = ", ".join(prefs.get("likes", []))
    return ToolResult.success(
        f"Serves {prefs.get('servings', 2)}. Likes: {likes}. Allergies: {allergies}."
    )


@tool(risk=ToolRisk.READ, network_hosts=["recipes.example.com"], sensitive=False)
async def search_recipes(query: RecipeQuery, _ctx: ToolContext) -> ToolResult:
    """Fetch a recipe page from the web (untrusted content)."""
    pages = _load("recipes.yaml").get("pages", {})
    page = pages.get(query.query.lower().strip())
    if page is None:
        return ToolResult.failure(f"no recipe found for {query.query!r}")
    return ToolResult.success(page)


@tool(
    risk=ToolRisk.IRREVERSIBLE,
    network_hosts=["api.grocery.example"],
    sensitive=False,
    required_secrets=["STORE_TOKEN"],
)
async def order_groceries(order: Order, ctx: ToolContext) -> ToolResult:
    """Place a grocery order (irreversible; costs money)."""
    _token = ctx.secret("STORE_TOKEN")  # the model never sees this
    cart = ", ".join(order.items)
    return ToolResult.success(f"Ordered {cart} for ${order.amount_usd:.2f}.")


def meal_planner_tools() -> dict[str, object]:
    """All four tools, keyed by name — pass to ``Agent.run(tools=...)``."""
    return {
        "read_pantry": read_pantry,
        "read_preferences": read_preferences,
        "search_recipes": search_recipes,
        "order_groceries": order_groceries,
    }
