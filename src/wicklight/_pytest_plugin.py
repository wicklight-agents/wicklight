"""Pytest plugin exposing the conformance kit to provider plugins.

Registered as a pytest plugin (``pytest11`` entry point), so installing
wicklight makes ``--wicklight-provider`` and the ``conformance`` marker
available. A plugin author points the kit at their provider with::

    pytest --wicklight-provider=myprovider -m conformance

and writes conformance tests using ``wicklight.testing`` and the
``wicklight_provider`` fixture.

This module is kept deliberately light at import time — it pulls in
``wicklight.contracts`` only inside the fixture — so loading it at pytest
startup does not import the rest of the package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.config import Config
    from _pytest.config.argparsing import Parser

    from wicklight.contracts import Provider


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--wicklight-provider",
        action="store",
        default=None,
        help="Provider name to run the Wicklight conformance kit against.",
    )


def pytest_configure(config: Config) -> None:
    config.addinivalue_line(
        "markers", "conformance: Wicklight provider contract conformance tests"
    )


@pytest.fixture
def wicklight_provider(request: pytest.FixtureRequest) -> Provider:
    """The provider named by ``--wicklight-provider``, resolved from the registry."""
    from wicklight.contracts import ProviderRegistry

    name = request.config.getoption("--wicklight-provider")
    if not name:
        pytest.skip("no --wicklight-provider given")
    return ProviderRegistry.discover().get(str(name))
