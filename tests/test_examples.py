"""Every example agent file must pass `wicklight check` (DTN-198)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wicklight.agentfile import check_agent_path

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.mark.parametrize("name", ["inbox", "files", "payments"])
def test_example_passes_check(name: str) -> None:
    config = check_agent_path(EXAMPLES / f"{name}.md")
    assert config.name
