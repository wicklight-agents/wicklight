"""The OpenAI-compatible provider adapter (Ollama, vLLM, local servers).

Registered as ``local/<model>`` through the ``wicklight.providers`` entry point.
Many servers speak the OpenAI Chat Completions wire format, so this reuses the
OpenAI adapter's translation code wholesale (DTN-230) and only changes the
endpoint and auth: it targets a configurable base URL and needs no API key.

The base URL defaults to Ollama's local endpoint and can be overridden with the
``OPENAI_BASE_URL`` environment variable (expected to include the ``/v1``
suffix, e.g. ``http://localhost:11434/v1``). Per-agent-file endpoint config and
``check`` capability warnings are a follow-up (DTN-268).
"""

from __future__ import annotations

import os

import httpx

from wicklight.contracts import Capabilities
from wicklight.providers.openai import OpenAIProvider

#: Ollama's OpenAI-compatible endpoint, the default when nothing is configured.
DEFAULT_BASE_URL = "http://localhost:11434/v1"


class OpenAICompatibleProvider(OpenAIProvider):
    """An OpenAI-compatible endpoint reached at a configurable base URL.

    Capabilities are deliberately conservative: local servers vary, and many
    lack parallel tool calls or structured output, so only text and streaming
    are declared. (Per-endpoint capability declarations arrive with the
    agent-file endpoint config in DTN-268.)
    """

    provider_name = "local"
    # Tool calling is declared because the common local models (e.g. llama3.1 via
    # Ollama) support it; parallel calls and structured output are not assumed.
    # Per-endpoint capability overrides arrive in DTN-268.
    capabilities = Capabilities(tool_calls=True, streaming=True)

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ) -> None:
        resolved = base_url or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
        super().__init__(
            api_key=api_key,
            base_url=resolved,
            transport=transport,
            timeout=timeout,
            # No key required for a local server; an optional one is still sent
            # if given (some hosted compatible services want a bearer token).
            requires_key=False,
            # base_url already carries the /v1 prefix, so the path is just the
            # chat-completions tail.
            chat_path="/chat/completions",
        )
