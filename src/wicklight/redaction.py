"""Secret redaction shared by the trace writer and the test cassettes.

A single source of truth for "what a leaked credential looks like": the
key-shaped patterns below are what the trace writer scrubs from every line and
blob (DTN-227) and what the cassette scrubber and CI scan use (DTN-226). Keeping
them in one neutral module (no heavy imports) means a pattern added here protects
every path at once.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable

#: Key-shaped strings to redact. Deliberately broad — the cost of a false
#: positive (an over-zealous redaction) is far lower than a leaked key.
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
)
REDACTED = "REDACTED"


def scrub_text(text: str) -> str:
    """Replace any key-shaped substrings with the redaction marker."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def scan_for_secrets(text: str) -> list[str]:
    """Return every secret-shaped substring found (empty when clean)."""
    found: list[str] = []
    for pattern in SECRET_PATTERNS:
        found.extend(match.group(0) for match in pattern.finditer(text))
    return found


def build_secret_redactor(values: Iterable[str] = ()) -> Callable[[str], str]:
    """A redactor that removes exact ``values`` (e.g. live API keys) and then any
    key-shaped substrings. Idempotent, so it is safe to run on every trace line.
    """
    # Longest first, so a key that contains a shorter one is redacted whole.
    exact = sorted({value for value in values if value}, key=len, reverse=True)

    def redact(text: str) -> str:
        for value in exact:
            text = text.replace(value, REDACTED)
        return scrub_text(text)

    return redact
