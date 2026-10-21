"""The read-only HTTP API behind ``wicklight view``.

A small FastAPI app that serves three JSON endpoints over existing trace files
and mounts the prebuilt frontend assets. It is read-only and offline: it binds
to loopback, never runs an agent, and only reads files already on disk.

Endpoints:

* ``GET /api/runs`` — the run list (one summary per trace).
* ``GET /api/runs/{run_id}/events`` — the run's events plus any read issues.
* ``GET /api/runs/{run_id}/blobs/{ref}`` — a content-addressed blob by hash.

Everything else is served from the packaged assets, so ``/`` returns the app.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from wicklight.trace import TraceReadError, dump_trace_event
from wicklight.viewer.source import RunNotFoundError, RunSource

# A blob ref is a sha256 hex digest. Validating the shape keeps a crafted ref
# (e.g. "../../etc/passwd") from escaping the blob directory.
_BLOB_REF = re.compile(r"^[0-9a-f]{64}$")


def assets_dir() -> Path:
    """The directory of prebuilt frontend assets shipped in the package."""
    return Path(__file__).parent / "assets"


def create_app(source: RunSource, *, assets: Path | None = None) -> FastAPI:
    """Build the viewer app over ``source``.

    ``assets`` overrides the packaged asset directory (used in tests); when the
    directory is absent the API still works and ``/`` returns a short notice.
    """
    app = FastAPI(title="wicklight viewer", docs_url=None, redoc_url=None)

    @app.get("/api/runs")
    def list_runs() -> list[dict[str, object]]:
        return [summary.to_json() for summary in source.list_runs()]

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: str) -> dict[str, object]:
        try:
            trace = source.trace_for(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=f"no such run: {run_id}"
            ) from exc
        except TraceReadError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {
            "run_id": run_id,
            "events": [dump_trace_event(event) for event in trace.events],
            "issues": [
                {
                    "line": issue.line,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in trace.issues
            ],
        }

    @app.get("/api/runs/{run_id}/blobs/{ref}")
    def run_blob(run_id: str, ref: str) -> Response:
        if not _BLOB_REF.match(ref):
            raise HTTPException(status_code=400, detail="invalid blob reference")
        try:
            trace = source.trace_for(run_id)
        except RunNotFoundError as exc:
            raise HTTPException(
                status_code=404, detail=f"no such run: {run_id}"
            ) from exc
        try:
            content = trace.resolve_blob(ref)
        except TraceReadError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        # Blobs are stored as text (usually JSON): label it JSON when it parses
        # so the viewer can pretty-print, otherwise serve it as plain text.
        media_type = "application/json" if _is_json(content) else "text/plain"
        return Response(content=content, media_type=f"{media_type}; charset=utf-8")

    _mount_assets(app, assets if assets is not None else assets_dir())
    return app


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def _mount_assets(app: FastAPI, directory: Path) -> None:
    if directory.is_dir() and (directory / "index.html").exists():
        app.mount("/", StaticFiles(directory=directory, html=True), name="assets")
        return

    # No built assets (e.g. a dev checkout before `npm run build`): keep the API
    # usable and tell the developer how to produce the frontend.
    @app.get("/")
    def _no_assets() -> Response:
        message = (
            "wicklight viewer: frontend assets are not built.\n"
            "Run `npm --prefix src/wicklight/viewer/frontend install` then "
            "`npm --prefix src/wicklight/viewer/frontend run build`.\n"
            "The JSON API is available under /api/.\n"
        )
        return Response(content=message, media_type="text/plain; charset=utf-8")


def _free_port(host: str) -> int:
    """Ask the OS for an unused port on ``host``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((host, 0))
        return probe.getsockname()[1]


def serve(
    source: RunSource,
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    open_browser: bool = True,
) -> None:
    """Run the viewer until interrupted (Ctrl+C).

    Binds to loopback by default. ``port=0`` picks a free port. When
    ``open_browser`` is set, the default browser is pointed at the server once
    it has had a moment to start.
    """
    chosen = port or _free_port(host)
    url = f"http://{host}:{chosen}/"
    app = create_app(source)

    if open_browser:
        # Open just after uvicorn starts; a daemon timer never blocks shutdown.
        timer = threading.Timer(0.7, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()

    print(f"wicklight viewer on {url} (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=chosen, log_level="warning")
