"""Reference provider plugins implementing the Provider contract.

Translation between the harness's neutral model types and one model API:
Anthropic, OpenAI, and OpenAI-compatible (also covering local models via
Ollama or vLLM). Ship as examples, not a catch-all layer.

``FakeProvider`` is a scripted, offline provider used for deterministic tests
and demos; it is registered under the ``fake`` provider name.
"""

from __future__ import annotations

from wicklight.providers.fake import (
    FakeProvider,
    FakeScript,
    FakeScriptError,
    ScriptedResponse,
    ScriptedToolCall,
)

__all__ = [
    "FakeProvider",
    "FakeScript",
    "FakeScriptError",
    "ScriptedResponse",
    "ScriptedToolCall",
]
