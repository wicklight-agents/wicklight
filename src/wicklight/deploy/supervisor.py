"""The in-container supervisor for a deployed agent (DTN-256, Option A).

Runs inside the sealed container and stays up between runs: it hosts the webhook
endpoint and the cron scheduler, watches a shared control directory for manual
triggers, and executes each trigger as its own run with its own trace (the
trigger recorded in ``run_started``). Overlapping triggers follow the deploy
file's policy (skip, queue, or allow; default skip). On ``SIGTERM`` — the host
kill switch (DTN-257) — the active run is stopped and ``run_finished`` with
reason ``killed`` is recorded, then the supervisor exits.

Because it is the same image everywhere, this runs identically on a laptop
(``docker run``) and on a hosted container service (ECS, Fly, Cloud Run).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from wicklight.agent import Agent
from wicklight.deploy.approvals import FileApprover
from wicklight.deploy.errors import parse_and_validate_deploy
from wicklight.deploy.schedule import cron_matches
from wicklight.deploy.schema import OverlapPolicy
from wicklight.deploy.secrets import resolve_secrets
from wicklight.trace import RunFinished, RunFinishedPayload, RunStatus, dump_trace_event

logger = logging.getLogger(__name__)

_MANUAL_POLL_SECONDS = 0.3
_WEBHOOK_TOKEN_ENV = "WICKLIGHT_WEBHOOK_TOKEN"


def control_dir(traces_dir: Path) -> Path:
    """The shared control directory (triggers in, approvals both ways)."""
    return traces_dir / "control"


def triggers_dir(traces_dir: Path) -> Path:
    return control_dir(traces_dir) / "triggers"


class Supervisor:
    """Runs a deployed agent's triggers, one trace per run."""

    def __init__(
        self,
        deploy_path: Path,
        *,
        env: Mapping[str, str] | None = None,
        run_kwargs: dict[str, Any] | None = None,
    ) -> None:
        environ = os.environ if env is None else env
        text = deploy_path.read_text(encoding="utf-8")
        _file, self.config = parse_and_validate_deploy(text, filename=deploy_path.name)
        self.deploy_dir = deploy_path.parent
        self.agent_path = deploy_path.parent / self.config.agent
        self.traces_dir = _resolve(deploy_path.parent, self.config.traces)
        self.secrets = resolve_secrets(
            self.config, base_dir=deploy_path.parent, env=environ
        )
        # Extra kwargs forwarded to Agent.arun (tests inject a fake provider/world).
        self._run_kwargs = run_kwargs or {}
        self._env = environ
        self._runs: dict[str, tuple[asyncio.Task[Any], Path]] = {}
        self._queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self._stopping = asyncio.Event()

    # --- lifecycle ------------------------------------------------------------

    async def serve(self, *, webhook_port: int = 8000) -> None:
        """Run until stopped (SIGTERM). Starts every configured trigger source."""
        triggers_dir(self.traces_dir).mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(NotImplementedError):  # no signals on some loops
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGTERM, self._request_stop
            )
        tasks = [
            asyncio.create_task(self._queue_worker()),
            asyncio.create_task(self._watch_manual()),
            asyncio.create_task(self._scheduler()),
        ]
        server = self._maybe_webhook_server(webhook_port)
        if server is not None:
            tasks.append(asyncio.create_task(server.serve()))

        logger.info("supervisor: ready for agent %r", self.config.name)
        await self._stopping.wait()

        if server is not None:
            server.should_exit = True
        await self._kill_active_runs()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _request_stop(self) -> None:
        logger.info("supervisor: SIGTERM received, stopping")
        self._stopping.set()

    # --- dispatch + run -------------------------------------------------------

    async def dispatch(self, trigger: str, task: str) -> str | None:
        """Apply the overlap policy and start (or queue/skip) a run."""
        if self._runs and self.config.overlap is not OverlapPolicy.ALLOW:
            if self.config.overlap is OverlapPolicy.SKIP:
                logger.info(
                    "supervisor: skip %s trigger (a run is in progress)", trigger
                )
                return None
            await self._queue.put((trigger, task))  # QUEUE
            logger.info("supervisor: queued %s trigger behind the active run", trigger)
            return None
        return self._start_run(trigger, task)

    def _start_run(self, trigger: str, task: str) -> str:
        run_id = f"run_{uuid4().hex[:12]}"
        trace = self.traces_dir / f"{run_id}.jsonl"
        approver = FileApprover(control_dir(self.traces_dir), run_id=run_id)
        agent = Agent.load(self.agent_path)
        coro = agent.arun(
            task,
            secrets=self.secrets,
            trigger=trigger,
            run_id=run_id,
            runs_dir=self.traces_dir,
            approver=approver,
            **self._run_kwargs,
        )
        run_task = asyncio.create_task(coro)
        self._runs[run_id] = (run_task, trace)
        run_task.add_done_callback(lambda _t, rid=run_id: self._on_run_done(rid))
        logger.info("supervisor: started %s run %s (%s)", trigger, run_id, task)
        return run_id

    def _on_run_done(self, run_id: str) -> None:
        self._runs.pop(run_id, None)
        if not self._runs and not self._queue.empty() and not self._stopping.is_set():
            trigger, task = self._queue.get_nowait()
            self._start_run(trigger, task)

    async def _kill_active_runs(self) -> None:
        for run_id, (task, trace) in list(self._runs.items()):
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            record_killed(trace, run_id)
            logger.info("supervisor: killed run %s", run_id)

    # --- trigger sources ------------------------------------------------------

    async def _queue_worker(self) -> None:
        # Draining is driven by _on_run_done; this just keeps the task alive so
        # QUEUE items put before any run started are not lost.
        while not self._stopping.is_set():
            if not self._runs and not self._queue.empty():
                trigger, task = await self._queue.get()
                self._start_run(trigger, task)
            await asyncio.sleep(_MANUAL_POLL_SECONDS)

    async def _watch_manual(self) -> None:
        folder = triggers_dir(self.traces_dir)
        while not self._stopping.is_set():
            for request in sorted(folder.glob("*.json")):
                raw = request.read_text(encoding="utf-8")
                request.unlink(missing_ok=True)
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning("supervisor: bad manual trigger file: %s", exc)
                    continue
                await self.dispatch("manual", str(data.get("task", "")))
            await asyncio.sleep(_MANUAL_POLL_SECONDS)

    async def _scheduler(self) -> None:
        schedules = [t.schedule for t in self.config.triggers if t.schedule]
        if not schedules:
            return
        while not self._stopping.is_set():
            await _sleep_to_next_minute()
            if self._stopping.is_set():
                return
            now = datetime.now(timezone.utc)
            for expr in schedules:
                if cron_matches(expr, now):
                    await self.dispatch("schedule", "scheduled run")

    def _maybe_webhook_server(self, port: int) -> Any | None:
        paths = [t.webhook.path for t in self.config.triggers if t.webhook]
        if not paths:
            return None
        import uvicorn
        from fastapi import FastAPI, Request, Response

        token = self.secrets.get("WEBHOOK_TOKEN") or self._env.get(_WEBHOOK_TOKEN_ENV)
        app = FastAPI(docs_url=None, redoc_url=None)

        @app.post("/{full_path:path}")
        async def _hook(full_path: str, request: Request) -> Response:
            if "/" + full_path not in paths:
                return Response(status_code=404)
            if token and request.headers.get("X-Wicklight-Token") != token:
                return Response(status_code=401)
            body = (await request.body()).decode("utf-8", "replace")
            await self.dispatch("webhook", body)
            return Response(status_code=202)

        # Bind all interfaces — the one exposed port, published to host loopback.
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
        return uvicorn.Server(config)


def record_killed(trace_path: Path, run_id: str) -> None:
    """Append a ``run_finished`` (reason ``killed``) event to a run's trace."""
    if not trace_path.exists():
        return
    event = RunFinished(
        run_id=run_id,
        step=0,
        timestamp=datetime.now(timezone.utc),
        explain="run finished: killed by the host kill switch",
        payload=RunFinishedPayload(status=RunStatus.STOPPED, steps=0, reason="killed"),
    )
    line = json.dumps(dump_trace_event(event), ensure_ascii=False)
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _resolve(base: Path, path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else base / candidate


async def _sleep_to_next_minute() -> None:
    now = datetime.now(timezone.utc)
    await asyncio.sleep(60 - now.second - now.microsecond / 1_000_000)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    deploy_path = Path(os.environ.get("WICKLIGHT_DEPLOY", "/app/deploy.yaml"))
    port = int(os.environ.get("WICKLIGHT_WEBHOOK_PORT", "8000"))
    try:
        supervisor = Supervisor(deploy_path)
    except Exception as exc:  # noqa: BLE001 - startup failure must be reported clearly
        print(f"wicklight: {exc}", flush=True)
        return 1
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(supervisor.serve(webhook_port=port))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
