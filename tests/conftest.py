"""Shared pytest configuration.

``--record`` is a maintainer switch for refreshing HTTP cassettes (DTN-226): it
lets cassette-backed tests make real requests and write them back, scrubbed.
Without it (the default, and always in CI) those tests replay offline.
"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record",
        action="store_true",
        default=False,
        help="Refresh HTTP cassettes by making real requests (maintainers only).",
    )


@pytest.fixture
def record_mode(request: pytest.FixtureRequest) -> bool:
    """True when the suite was invoked with ``--record``."""
    return bool(request.config.getoption("--record"))
