"""The read-only viewer API behind `wicklight view` (DTN-247).

These tests exercise the FastAPI app directly with a TestClient — no port is
bound and no browser opens, so they are fast and offline.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wicklight.agent import Agent
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.viewer.server import _stream_events, create_app
from wicklight.viewer.source import RunSource, run_id_for, summarize

SAMPLE = Path("examples/sample.jsonl")
INJECTION = Path("tests/fixtures/viewer/injection.jsonl")


def _client(source: RunSource) -> TestClient:
    # assets default to the packaged dir; the API is what we test here.
    return TestClient(create_app(source))


# --- a deployment trace opens in the viewer (DTN-258) -------------------------


def test_deployment_trace_with_trigger_and_egress_opens(tmp_path: Path) -> None:
    # A scheduled run records run_started.trigger; the egress proxy appends
    # egress_denied events to the same trace. The viewer must load both.
    from wicklight.deploy.proxy import DeniedConnection, trace_deny_writer

    agent_file = tmp_path / "a.md"
    agent_file.write_text(
        "---\nname: sched\nmodels: { default: fake/x }\ntools: {}\n---\nGo.\n",
        encoding="utf-8",
    )
    result = Agent.load(agent_file).run(
        "scheduled run",
        provider=FakeProvider(FakeScript.from_yaml("responses:\n  - text: done\n")),
        world=MockWorld(),
        trigger="schedule",
        run_id="sched",
        runs_dir=tmp_path,
    )
    # The proxy appends a refusal to the same trace file.
    from datetime import datetime, timezone

    trace_deny_writer(result.trace_path)(
        DeniedConnection("evil.example", 443, datetime.now(timezone.utc))
    )

    client = _client(RunSource.from_path(result.trace_path))
    body = client.get("/api/runs/sched/events").json()
    types = [e["type"] for e in body["events"]]
    assert "egress_denied" in types
    started = next(e for e in body["events"] if e["type"] == "run_started")
    assert started["payload"]["trigger"] == "schedule"
    assert body["issues"] == []  # loaded cleanly, no parse errors


# --- run list -----------------------------------------------------------------


def test_run_list_summarizes_the_sample_run() -> None:
    client = _client(RunSource.from_path(SAMPLE))
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["run_id"] == "sample"
    assert run["agent"] == "inbox-summarizer"
    assert run["status"] == "limit"
    assert run["steps"] == 5
    # The sample has one policy denial and one granted approval.
    assert run["blocks"] == 1
    assert run["approvals"] == 1
    assert run["models"] == ["anthropic/claude-sonnet"]


# --- events -------------------------------------------------------------------


def test_events_endpoint_returns_every_event() -> None:
    client = _client(RunSource.from_path(SAMPLE))
    body = client.get("/api/runs/sample/events").json()
    assert body["run_id"] == "sample"
    assert len(body["events"]) == 17
    assert body["events"][0]["type"] == "run_started"
    # Every event carries the envelope the frontend relies on.
    first = body["events"][0]
    assert {"v", "run_id", "step", "timestamp", "type", "payload", "explain"} <= set(
        first
    )
    assert body["issues"] == []


def test_unknown_run_is_404() -> None:
    client = _client(RunSource.from_path(SAMPLE))
    response = client.get("/api/runs/does-not-exist/events")
    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_corrupt_line_is_reported_but_other_events_survive(tmp_path: Path) -> None:
    lines = SAMPLE.read_text(encoding="utf-8").splitlines()
    corrupt = tmp_path / "run.jsonl"
    corrupt.write_text(
        lines[0] + "\n" + "{bad json\n" + "\n".join(lines[1:]) + "\n",
        encoding="utf-8",
    )
    client = _client(RunSource.from_path(corrupt))
    body = client.get("/api/runs/run/events").json()
    assert len(body["events"]) == 17  # every real event survives the bad line
    assert body["issues"] and body["issues"][0]["line"] == 2
    assert body["issues"][0]["severity"] == "error"


# --- blobs --------------------------------------------------------------------


@pytest.fixture
def recorded_run(tmp_path: Path) -> tuple[RunSource, str]:
    """A real run whose trace references request/response blobs."""
    agent_file = tmp_path / "a.md"
    agent_file.write_text(
        "---\nname: t\nmodels: { default: fake/x }\ntools: { read_inbox: read }\n"
        "---\nGo.\n",
        encoding="utf-8",
    )
    script = "responses:\n  - tool_calls:\n      - name: read_inbox\n  - text: done\n"
    result = Agent.load(agent_file).run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml(script)),
        world=MockWorld.from_yaml("inbox:\n  - sender: a@b.com\n    subject: Hi\n"),
        run_id="rec",
        runs_dir=tmp_path,
    )
    assert result.trace_path is not None
    return RunSource.from_path(result.trace_path), "rec"


def test_blob_is_served_by_hash(recorded_run: tuple[RunSource, str]) -> None:
    source, run_id = recorded_run
    events = source.trace_for(run_id).events
    refs = [
        e.payload.request_ref
        for e in events
        if e.type == "model_called" and e.payload.request_ref
    ]
    assert refs, "expected a recorded request blob"
    client = _client(source)
    response = client.get(f"/api/runs/{run_id}/blobs/{refs[0]}")
    assert response.status_code == 200
    # Request blobs are JSON, so the endpoint labels them as such.
    assert response.headers["content-type"].startswith("application/json")
    assert response.text


def test_invalid_blob_ref_is_rejected(recorded_run: tuple[RunSource, str]) -> None:
    source, run_id = recorded_run
    client = _client(source)
    # A ref that is not a 64-char sha256 hex digest is a bad request.
    assert client.get(f"/api/runs/{run_id}/blobs/not-a-hash").status_code == 400


def test_missing_blob_is_404(recorded_run: tuple[RunSource, str]) -> None:
    source, run_id = recorded_run
    client = _client(source)
    absent = "0" * 64
    assert client.get(f"/api/runs/{run_id}/blobs/{absent}").status_code == 404


# --- the committed injection fixture (DTN-248/249 demo) -----------------------


def test_injection_fixture_serves_the_untrusted_email_and_block() -> None:
    client = _client(RunSource.from_path(INJECTION))
    body = client.get("/api/runs/injection/events").json()

    # The send to the attacker is blocked, and the block cites the policy line.
    blocked = [
        e
        for e in body["events"]
        if e["type"] == "policy_checked" and e["payload"]["decision"] == "deny"
    ]
    assert blocked and "line 22" in blocked[0]["explain"]

    # The step where the block happened recorded the context the model saw; its
    # request blob carries the poisoned email as an untrusted tool result.
    blocked_step = blocked[0]["step"]
    called = [
        e
        for e in body["events"]
        if e["type"] == "model_called" and e["step"] == blocked_step
    ]
    ref = called[0]["payload"]["request_ref"]
    blob = client.get(f"/api/runs/injection/blobs/{ref}")
    assert blob.status_code == 200
    messages = blob.json()["messages"]
    poisoned = [m for m in messages if m["role"] == "tool" and not m["trusted"]]
    assert poisoned and "attacker@evil.com" in poisoned[0]["content"]
    assert poisoned[0]["name"] == "read_inbox"


# --- run list metadata + live stream (DTN-250) --------------------------------


def test_meta_reports_run_count_and_live_flag() -> None:
    client = _client(RunSource.from_dir("tests/fixtures/viewer"))
    meta = client.get("/api/meta").json()
    assert meta["live"] is False
    assert meta["run_count"] == 1
    assert meta["single_run_id"] == "injection"

    live_client = TestClient(
        create_app(RunSource.from_path(INJECTION), live_run_id="injection")
    )
    live_meta = live_client.get("/api/meta").json()
    assert live_meta["live"] is True
    assert live_meta["live_run_id"] == "injection"


def test_stream_of_unknown_run_is_404() -> None:
    client = _client(RunSource.from_path(SAMPLE))
    assert client.get("/api/runs/nope/stream").status_code == 404


class _NeverDisconnected:
    """Stand-in for a Starlette Request that stays connected."""

    async def is_disconnected(self) -> bool:
        return False


def test_stream_appends_events_as_the_trace_grows(tmp_path: Path) -> None:
    # A live run is a trace file being appended to. The stream should emit the
    # events present so far, then new ones as they are written, then end.
    lines = SAMPLE.read_text(encoding="utf-8").splitlines()
    live = tmp_path / "live.jsonl"
    live.write_text("\n".join(lines[:3]) + "\n", encoding="utf-8")  # no run_finished
    source = RunSource.from_path(live)

    async def drive() -> tuple[int, bool]:
        gen = _stream_events(source, "live", _NeverDisconnected())  # type: ignore[arg-type]
        received = 0
        ended = False
        appended = False
        for _ in range(100):
            try:
                chunk = (await asyncio.wait_for(gen.__anext__(), timeout=3)).decode()
            except StopAsyncIteration:
                break
            if chunk.startswith("event: end"):
                ended = True
                break
            received += 1
            # After the initial batch arrives, write the rest of the run.
            if not appended and received >= 3:
                live.write_text("\n".join(lines) + "\n", encoding="utf-8")
                appended = True
        await gen.aclose()
        return received, ended

    received, ended = asyncio.run(drive())
    assert ended
    assert received == len(lines)  # every event delivered across both writes


# --- assets fallback ----------------------------------------------------------


def test_root_without_built_assets_explains_how_to_build(tmp_path: Path) -> None:
    empty = tmp_path / "no-assets"
    empty.mkdir()
    app = create_app(RunSource.from_path(SAMPLE), assets=empty)
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "frontend assets are not built" in response.text
    # The API still works without a frontend.
    assert client.get("/api/runs").status_code == 200


# --- source helpers -----------------------------------------------------------


def test_run_id_strips_trace_suffixes() -> None:
    assert run_id_for(Path("runs/run_123.jsonl")) == "run_123"
    assert run_id_for(Path("runs/run_123.jsonl.gz")) == "run_123"


def test_from_dir_lists_every_trace(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(
        SAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "b.jsonl").write_text(
        SAMPLE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    source = RunSource.from_dir(tmp_path)
    assert set(source.run_ids()) == {"a", "b"}


def test_summarize_reads_agent_and_outcome() -> None:
    from wicklight.trace import read_trace

    summary = summarize("sample", read_trace(SAMPLE))
    assert summary.agent == "inbox-summarizer"
    assert summary.status == "limit"
    assert summary.steps == 5
