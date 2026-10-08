"""Tests for provider descriptions and `wicklight providers list` (DTN-208)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from typer.testing import CliRunner

from wicklight.cli import app
from wicklight.contracts import (
    Capabilities,
    ModelEvent,
    ModelRequest,
    ModelResponse,
    StopReason,
    classify_contract_version,
    describe_providers,
)

runner = CliRunner()


class _Provider:
    contract_version = "1.0"
    capabilities = Capabilities(streaming=True, max_context_tokens=100_000)

    async def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(stop_reason=StopReason.STOP)

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]:
        if False:  # pragma: no cover - never iterated in these tests
            yield  # type: ignore[unreachable]


class _DeprecatedProvider(_Provider):
    contract_version = "0.9"


class _FutureProvider(_Provider):
    contract_version = "2.0"


class _BrokenToLoad:
    pass


@dataclass
class FakeEntryPoint:
    name: str
    obj: object

    def load(self) -> object:
        if isinstance(self.obj, type) and self.obj is _BrokenToLoad:
            raise RuntimeError("cannot import plugin")
        return self.obj


def _describe(**plugins: object):
    eps = [FakeEntryPoint(name, obj) for name, obj in plugins.items()]
    return {info.name: info for info in describe_providers(entry_points_=eps)}


def test_describes_a_provider_with_capabilities() -> None:
    infos = _describe(acme=_Provider)
    info = infos["acme"]
    assert info.contract_version == "1.0"
    assert info.status == "ok"
    assert info.capabilities is not None
    assert info.capabilities.streaming is True
    assert info.capabilities.max_context_tokens == 100_000


def test_flags_deprecated_and_unsupported_versions() -> None:
    infos = _describe(old=_DeprecatedProvider, future=_FutureProvider)
    assert infos["old"].status == "deprecated"
    assert infos["future"].status == "unsupported"
    # A listing never raises on a bad version; it reports it.
    assert "newer than this harness" in infos["future"].detail


def test_reports_load_errors_without_raising() -> None:
    info = _describe(broken=_BrokenToLoad)["broken"]
    assert info.status == "error"
    assert "cannot import plugin" in info.detail
    assert info.capabilities is None


@pytest.mark.parametrize(
    ("version", "status"),
    [
        ("1.0", "ok"),
        ("1.4", "ok"),
        ("0.9", "deprecated"),
        ("2.0", "unsupported"),
        ("nope", "unsupported"),
    ],
)
def test_classify_contract_version(version: str, status: str) -> None:
    assert classify_contract_version(version)[0] == status


def test_cli_lists_the_fake_provider() -> None:
    result = runner.invoke(app, ["providers", "list"])
    assert result.exit_code == 0
    assert "fake" in result.output
    assert "1.0" in result.output
    assert "wicklight" in result.output
