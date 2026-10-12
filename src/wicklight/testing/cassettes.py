"""Recorded HTTP fixtures (cassettes) for offline, deterministic provider tests.

A *cassette* is a small JSON file of request/response pairs. Provider-adapter
tests replay cassettes through an ``httpx`` client so they run in CI with no
network and no API keys. Maintainers refresh a cassette with ``--record`` (see
``tests/conftest.py``), which performs the real requests and writes them back
with secrets scrubbed.

    async with cassette_client(path, record=record) as client:
        response = await client.post(url, json=payload)

Replay matches each outgoing request to the next recorded interaction with the
same method and URL, in order; an unmatched request raises rather than silently
hitting the network. Secrets never reach disk: request headers (which carry the
API key) are not stored, response headers are scrubbed, and the whole cassette
is scanned on write — :func:`scan_for_secrets` is also run in CI over every
committed cassette.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx

from wicklight.redaction import scan_for_secrets, scrub_text

__all__ = [
    "Cassette",
    "CassetteError",
    "cassette_client",
    "iter_cassettes",
    "scan_for_secrets",
    "scrub_text",
]

CASSETTE_FORMAT_VERSION = 1

# Response headers that may carry identifying or sensitive values. Dropped on
# record so they never land in a committed cassette.
_SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "x-api-key",
        "api-key",
        "openai-organization",
        "openai-project",
        "set-cookie",
        "cookie",
    }
)


class CassetteError(Exception):
    """Raised when a cassette is missing, malformed, or has no matching request."""


@dataclass(frozen=True)
class Interaction:
    method: str
    url: str
    request_body: str
    status_code: int
    response_headers: dict[str, str]
    response_body: str


def _no_interactions() -> list[Interaction]:
    return []


@dataclass
class Cassette:
    """A recorded sequence of HTTP interactions, replayed in order."""

    path: Path
    interactions: list[Interaction] = field(default_factory=_no_interactions)

    @classmethod
    def load(cls, path: str | Path) -> Cassette:
        path = Path(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CassetteError(f"cassette not found: {path}") from exc
        except json.JSONDecodeError as exc:
            raise CassetteError(f"cassette {path} is not valid JSON: {exc}") from exc
        version = data.get("version")
        if version != CASSETTE_FORMAT_VERSION:
            raise CassetteError(
                f"cassette {path} has version {version!r}, "
                f"expected {CASSETTE_FORMAT_VERSION}"
            )
        raw_items = cast("list[dict[str, Any]]", data.get("interactions", []))
        interactions = [
            Interaction(
                method=str(item["request"]["method"]).upper(),
                url=str(item["request"]["url"]),
                request_body=str(item["request"].get("body", "")),
                status_code=int(item["response"]["status_code"]),
                response_headers=dict(item["response"].get("headers", {})),
                response_body=str(item["response"].get("body", "")),
            )
            for item in raw_items
        ]
        return cls(path=path, interactions=interactions)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": CASSETTE_FORMAT_VERSION,
            "interactions": [
                {
                    "request": {
                        "method": i.method,
                        "url": i.url,
                        "body": i.request_body,
                    },
                    "response": {
                        "status_code": i.status_code,
                        "headers": i.response_headers,
                        "body": i.response_body,
                    },
                }
                for i in self.interactions
            ],
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        leaked = scan_for_secrets(text)
        if leaked:
            raise CassetteError(
                f"refusing to write {self.path}: it still contains "
                f"secret-shaped values: {', '.join(sorted(set(leaked)))}"
            )
        self.path.write_text(text + "\n", encoding="utf-8")


def scrub_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Drop sensitive response headers; keep the rest (lower-cased)."""
    return {
        key.lower(): value
        for key, value in headers.items()
        if key.lower() not in _SENSITIVE_HEADERS
    }


class _ReplayTransport(httpx.MockTransport):
    """Serves recorded responses in order; never touches the network."""

    def __init__(self, cassette: Cassette) -> None:
        self._remaining = list(cassette.interactions)
        self._cassette_path = cassette.path
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        method = request.method.upper()
        url = str(request.url)
        for index, interaction in enumerate(self._remaining):
            if interaction.method == method and interaction.url == url:
                self._remaining.pop(index)
                return httpx.Response(
                    interaction.status_code,
                    headers=interaction.response_headers,
                    content=interaction.response_body.encode("utf-8"),
                )
        raise CassetteError(
            f"no recorded interaction for {method} {url} in {self._cassette_path}; "
            f"re-record with --record"
        )


class _RecordingTransport(httpx.AsyncBaseTransport):
    """Performs real requests and records each (scrubbed) into the cassette."""

    def __init__(self, cassette: Cassette, inner: httpx.AsyncBaseTransport) -> None:
        self._cassette = cassette
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        await response.aread()
        self._cassette.interactions.append(
            Interaction(
                method=request.method.upper(),
                url=str(request.url),
                request_body=scrub_text(request.content.decode("utf-8", "replace")),
                status_code=response.status_code,
                response_headers=scrub_headers(response.headers),
                response_body=scrub_text(response.text),
            )
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


@asynccontextmanager
async def cassette_client(
    path: str | Path, *, record: bool = False, **client_kwargs: Any
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """An ``httpx.AsyncClient`` backed by a cassette.

    In replay mode (the default) requests are served from the cassette offline.
    In record mode the real requests go out and are written back, scrubbed, when
    the client closes.
    """
    path = Path(path)
    if record:
        cassette = Cassette(path=path)
        transport: httpx.AsyncBaseTransport = _RecordingTransport(
            cassette, httpx.AsyncHTTPTransport()
        )
        client = httpx.AsyncClient(transport=transport, **client_kwargs)
        try:
            yield client
        finally:
            await client.aclose()
            cassette.save()
    else:
        cassette = Cassette.load(path)
        client = httpx.AsyncClient(
            transport=_ReplayTransport(cassette), **client_kwargs
        )
        try:
            yield client
        finally:
            await client.aclose()


def iter_cassettes(directory: str | Path) -> Iterator[Path]:
    """Yield every ``*.json`` cassette under ``directory`` (recursively)."""
    yield from sorted(Path(directory).rglob("*.json"))
