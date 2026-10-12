"""Recorded HTTP fixtures: replay, secret scrubbing, and the CI scan (DTN-226)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from wicklight.testing import (
    Cassette,
    CassetteError,
    cassette_client,
    iter_cassettes,
    scan_for_secrets,
    scrub_text,
)
from wicklight.testing.cassettes import Interaction, _RecordingTransport

CASSETTES_DIR = Path(__file__).parent / "cassettes"
DEMO = CASSETTES_DIR / "demo_messages.json"


# --- the CI secret check: no committed cassette may contain a key -------------


def test_no_committed_cassette_contains_a_secret() -> None:
    offenders: dict[str, list[str]] = {}
    for path in iter_cassettes(CASSETTES_DIR):
        leaked = scan_for_secrets(path.read_text(encoding="utf-8"))
        if leaked:
            offenders[str(path)] = leaked
    assert not offenders, f"cassettes contain secret-shaped values: {offenders}"


# --- replay, offline ----------------------------------------------------------


def test_replay_serves_the_recorded_response_offline() -> None:
    async def go() -> httpx.Response:
        async with cassette_client(DEMO) as client:
            return await client.post(
                "https://api.example.com/v1/messages",
                json={"model": "demo-model", "messages": []},
            )

    response = asyncio.run(go())
    assert response.status_code == 200
    assert "Hello from the cassette!" in response.text


def test_replay_raises_on_an_unrecorded_request() -> None:
    async def go() -> None:
        async with cassette_client(DEMO) as client:
            await client.get("https://api.example.com/v1/unknown")

    with pytest.raises(CassetteError, match="no recorded interaction"):
        asyncio.run(go())


def test_missing_cassette_raises() -> None:
    async def go() -> None:
        async with cassette_client(CASSETTES_DIR / "nope.json") as client:
            await client.get("https://x")

    with pytest.raises(CassetteError, match="cassette not found"):
        asyncio.run(go())


# --- scrubbing and scanning ---------------------------------------------------


def test_scrub_and_scan_find_key_shaped_values() -> None:
    dirty = (
        'Authorization: Bearer sk-ant-abcd1234efgh5678 and key "sk-ABCDEF0123456789"'
    )
    assert scan_for_secrets(dirty)  # the scanner sees them
    cleaned = scrub_text(dirty)
    assert scan_for_secrets(cleaned) == []  # the scrubber removes them
    assert "REDACTED" in cleaned


def test_save_refuses_to_write_a_cassette_with_secrets(tmp_path: Path) -> None:
    cassette = Cassette(
        path=tmp_path / "leak.json",
        interactions=[
            Interaction(
                method="POST",
                url="https://api.example.com/v1/messages",
                request_body="{}",
                status_code=200,
                response_headers={},
                response_body='{"leaked": "sk-ant-abcd1234efgh5678ijkl"}',
            )
        ],
    )
    with pytest.raises(CassetteError, match="secret-shaped"):
        cassette.save()
    assert not (tmp_path / "leak.json").exists()


# --- recording (with a fake network transport, scrubbing applied) -------------


def test_recording_scrubs_secrets_and_round_trips(tmp_path: Path) -> None:
    # A stand-in "network": returns a secret in the body and an auth header.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"authorization": "Bearer sk-should-not-be-stored-abcdefgh"},
            json={"ok": True, "token": "sk-ant-leakage1234567890abcd"},
        )

    cassette_path = tmp_path / "recorded.json"

    async def record() -> None:
        cassette = Cassette(path=cassette_path)
        transport = _RecordingTransport(cassette, httpx.MockTransport(handler))
        async with httpx.AsyncClient(transport=transport) as client:
            await client.post("https://api.example.com/v1/messages", json={"m": 1})
        cassette.save()

    asyncio.run(record())

    # The committed file is clean: no secret, no auth header.
    text = cassette_path.read_text(encoding="utf-8")
    assert scan_for_secrets(text) == []
    stored = json.loads(text)
    headers = stored["interactions"][0]["response"]["headers"]
    assert "authorization" not in headers

    # And it replays the (scrubbed) response offline.
    async def replay() -> httpx.Response:
        async with cassette_client(cassette_path) as client:
            return await client.post("https://api.example.com/v1/messages", json={})

    response = asyncio.run(replay())
    assert response.status_code == 200
    assert "REDACTED" in response.text
