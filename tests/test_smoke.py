"""Smoke test placeholder (DTN-189).

A trivial always-on check that the test runner and coverage are wired up.
Behavioural tests live alongside the code they cover as the harness grows.
"""

from __future__ import annotations

import wicklight


def test_package_version_is_set() -> None:
    assert wicklight.__version__
