"""Tests for the Tool contract, discovery, and conformance kit (DTN-209)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import ClassVar

import pytest
from pydantic import BaseModel

from wicklight.contracts import (
    Tool,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolRisk,
    tool,
)
from wicklight.testing import run_tool_conformance


class EchoInput(BaseModel):
    text: str


@tool(risk="read", network_hosts=[], sensitive=False)
async def echo(tool_input: EchoInput, ctx: ToolContext) -> ToolResult:
    """Echo the text back."""
    return ToolResult.success(tool_input.text)


@tool(
    risk="write",
    network_hosts=["mail.example.com"],
    sensitive=lambda i: "secret" in i.text,
)
async def shout(tool_input: EchoInput, ctx: ToolContext) -> str:
    # Returns a bare string, which the decorator wraps into a success result.
    return tool_input.text.upper()


class WeatherInput(BaseModel):
    city: str


class WeatherTool:
    name = "get_weather"
    description = "Look up the weather."
    risk = ToolRisk.READ
    network_hosts: ClassVar[list[str]] = ["api.weather.test"]
    input_model = WeatherInput

    def is_sensitive(self, tool_input: BaseModel) -> bool:
        return False

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(tool_input, WeatherInput)
        return ToolResult.success(f"sunny in {tool_input.city}")


@dataclass
class FakeEntryPoint:
    name: str
    obj: object

    def load(self) -> object:
        return self.obj


def _run(tool_obj: Tool, model: BaseModel) -> ToolResult:
    return asyncio.run(tool_obj.run(model, ToolContext()))


# --- the decorator ------------------------------------------------------------


def test_decorator_builds_a_tool() -> None:
    assert echo.name == "echo"
    assert echo.description == "Echo the text back."
    assert echo.risk is ToolRisk.READ
    assert echo.network_hosts == []
    assert echo.input_model is EchoInput
    assert echo.is_sensitive(EchoInput(text="hi")) is False

    result = _run(echo, EchoInput(text="hello"))
    assert result.ok and result.output == "hello"


def test_bare_string_return_is_wrapped_and_sensitivity_stamped() -> None:
    public = _run(shout, EchoInput(text="hello"))
    assert public.output == "HELLO"
    assert public.sensitive is False
    # The sensitivity function sees the input and stamps the result.
    secret = _run(shout, EchoInput(text="secret plans"))
    assert secret.sensitive is True


def test_decorator_rejects_sync_function() -> None:
    with pytest.raises(ToolError, match="must be an async function"):

        @tool(risk="read", network_hosts=[], sensitive=False)
        def broken(tool_input: EchoInput, ctx: ToolContext) -> ToolResult:  # type: ignore[misc]
            return ToolResult.success()


def test_decorator_rejects_untyped_input() -> None:
    with pytest.raises(ToolError, match="Pydantic model"):

        @tool(risk="read", network_hosts=[], sensitive=False)
        async def broken(tool_input, ctx: ToolContext) -> ToolResult:  # type: ignore[no-untyped-def]
            return ToolResult.success()


def test_decorator_rejects_invalid_risk() -> None:
    with pytest.raises(ToolError, match="invalid risk"):

        @tool(risk="off", network_hosts=[], sensitive=False)
        async def broken(tool_input: EchoInput, ctx: ToolContext) -> ToolResult:
            return ToolResult.success()


# --- context / secrets --------------------------------------------------------


def test_context_exposes_secrets_but_not_to_the_model() -> None:
    ctx = ToolContext(secrets={"api_key": "sk-123"})
    assert ctx.secret("api_key") == "sk-123"
    with pytest.raises(ToolError, match="not available"):
        ctx.secret("missing")


# --- discovery ----------------------------------------------------------------


def test_discovery_and_lookup() -> None:
    eps = [FakeEntryPoint("echo", echo), FakeEntryPoint("weather", WeatherTool)]
    registry = ToolRegistry.discover(entry_points_=eps)
    assert registry.names() == ["echo", "get_weather"]  # keyed by tool.name
    assert _run(registry.get("get_weather"), WeatherInput(city="Paris")).output == (
        "sunny in Paris"
    )
    with pytest.raises(ToolError, match="unknown tool 'nope'"):
        registry.get("nope")


# --- conformance kit ----------------------------------------------------------


def test_decorated_tool_passes_conformance() -> None:
    report = asyncio.run(run_tool_conformance(echo, EchoInput(text="hi")))
    assert report.passed(), report.summary()


def test_entry_point_tool_passes_conformance() -> None:
    registry = ToolRegistry.discover(entry_points_=[FakeEntryPoint("w", WeatherTool)])
    report = asyncio.run(
        run_tool_conformance(registry.get("get_weather"), WeatherInput(city="Paris"))
    )
    assert report.passed(), report.summary()


class BrokenTool:
    name = "broken"
    description = ""
    risk = "read"  # wrong: a string, not a ToolRisk
    network_hosts = "nope"  # wrong: not a list
    input_model = WeatherInput

    def is_sensitive(self, tool_input: BaseModel) -> str:
        return "yes"  # wrong: not a bool

    async def run(self, tool_input: BaseModel, ctx: ToolContext) -> ToolResult:
        raise RuntimeError("boom")  # wrong: raises instead of returning a result


def test_broken_tool_fails_conformance_with_clear_messages() -> None:
    report = asyncio.run(run_tool_conformance(BrokenTool(), WeatherInput(city="x")))
    assert not report.passed()
    failed = {r.name for r in report.failures}
    assert failed == {
        "risk_declared",
        "network_hosts_declared",
        "sensitive_declared",
        "returns_result",
    }
