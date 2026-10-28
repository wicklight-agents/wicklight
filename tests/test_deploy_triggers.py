"""Triggers, overlap, file approvals, schedule, and kill recording (DTN-256/257).

Host-side / in-process tests only (no container) — the end-to-end Docker test is
test_deploy_run.py.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from wicklight.agent import Agent
from wicklight.core.approval import ApprovalRequest, Approved, Denied
from wicklight.deploy import (
    FileApprover,
    OverlapPolicy,
    Supervisor,
    cron_matches,
    next_fire,
    pending_approvals,
    record_killed,
    resolve_approval,
)
from wicklight.deploy.approvals import approvals_dir
from wicklight.providers import FakeProvider, FakeScript
from wicklight.tools import MockWorld
from wicklight.trace import read_trace

AGENT = "---\nname: t\nmodels: { default: fake/x }\ntools: {}\n---\nDo the thing.\n"


def _deploy(tmp_path: Path, *, triggers: str = "", overlap: str = "") -> Path:
    (tmp_path / "agent.md").write_text(AGENT, encoding="utf-8")
    body = f"name: t\nagent: agent.md\ntraces: ./runs\n{triggers}{overlap}"
    deploy = tmp_path / "deploy.yaml"
    deploy.write_text(body, encoding="utf-8")
    return deploy


def _supervisor(
    deploy: Path, *, text: str = "responses:\n  - text: done\n"
) -> Supervisor:
    return Supervisor(
        deploy,
        env={},
        run_kwargs={
            "provider": FakeProvider(FakeScript.from_yaml(text)),
            "world": MockWorld(),
        },
    )


# --- manual trigger starts a run with provenance ------------------------------


def test_manual_trigger_runs_with_the_trigger_recorded(tmp_path: Path) -> None:
    sup = _supervisor(_deploy(tmp_path))

    async def go() -> Path:
        run_id = await sup.dispatch("manual", "hello")
        assert run_id is not None
        task, trace = sup._runs[run_id]
        await task
        return trace

    trace_path = asyncio.run(go())
    events = read_trace(trace_path).events
    started = next(e for e in events if e.type == "run_started")
    assert started.payload.trigger == "manual"
    assert events[-1].type == "run_finished"


# --- overlap policy -----------------------------------------------------------


def test_default_overlap_skips_while_a_run_is_active(tmp_path: Path) -> None:
    sup = _supervisor(_deploy(tmp_path))
    assert sup.config.overlap is OverlapPolicy.SKIP

    async def go() -> str | None:
        # Pretend a run is in progress, then a second trigger arrives.
        busy = asyncio.create_task(asyncio.sleep(5))
        sup._runs["busy"] = (busy, tmp_path / "x.jsonl")
        result = await sup.dispatch("manual", "second")
        busy.cancel()
        return result

    assert asyncio.run(go()) is None  # skipped: no new run started


def test_overlap_queue_parses(tmp_path: Path) -> None:
    sup = _supervisor(_deploy(tmp_path, overlap="overlap: queue\n"))
    assert sup.config.overlap is OverlapPolicy.QUEUE


# --- kill switch records a killed run -----------------------------------------


def test_record_killed_appends_a_killed_run_finished(tmp_path: Path) -> None:
    # Produce a real trace, then record a kill on it.
    result = Agent.load(_deploy(tmp_path) and tmp_path / "agent.md").run(
        "go",
        provider=FakeProvider(FakeScript.from_yaml("responses:\n  - text: hi\n")),
        world=MockWorld(),
        run_id="victim",
        runs_dir=tmp_path,
    )
    record_killed(Path(result.trace_path), "victim")
    events = read_trace(result.trace_path).events
    assert events[-1].type == "run_finished"
    assert events[-1].payload.reason == "killed"


# --- file approvals bridge the run to the host --------------------------------


def test_file_approver_waits_for_a_host_decision(tmp_path: Path) -> None:
    control = tmp_path / "control"
    approver = FileApprover(control, run_id="r", timeout_seconds=5)
    request = ApprovalRequest(tool="send_email", reason="write action", call_id="c1")

    async def go() -> object:
        pending_task = asyncio.create_task(approver.request(request))
        # Let the request file be written, then resolve it from the "host".
        for _ in range(20):
            if pending_approvals(control):
                break
            await asyncio.sleep(0.05)
        waiting = pending_approvals(control)
        assert len(waiting) == 1 and waiting[0].tool == "send_email"
        resolve_approval(control, "c1", approved=True)
        return await pending_task

    assert isinstance(asyncio.run(go()), Approved)
    # Request and response files are cleaned up afterwards.
    assert not list(approvals_dir(control).glob("*.json"))


def test_file_approver_times_out_to_deny(tmp_path: Path) -> None:
    approver = FileApprover(tmp_path / "control", timeout_seconds=0.3)
    decision = asyncio.run(
        approver.request(ApprovalRequest(tool="x", reason="y", call_id="c2"))
    )
    assert isinstance(decision, Denied)


# --- schedule matching --------------------------------------------------------


def test_cron_matches_weekday_window() -> None:
    assert cron_matches("0 8 * * 1-5", datetime(2024, 1, 1, 8, 0))  # Monday 08:00
    assert not cron_matches("0 8 * * 1-5", datetime(2024, 1, 7, 8, 0))  # Sunday
    assert cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 15))
    assert not cron_matches("*/15 * * * *", datetime(2024, 1, 1, 0, 16))


def test_next_fire_finds_the_next_minute() -> None:
    assert next_fire("0 8 * * *", datetime(2024, 1, 1, 7, 0)) == datetime(
        2024, 1, 1, 8, 0
    )
