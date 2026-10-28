"""A small CONNECT-only egress proxy that enforces an allowlist (DTN-254).

The deployed agent container has no direct route to the internet; this proxy,
running alongside it, is the only way out. It speaks just enough HTTP to handle
``CONNECT host:port`` (how HTTPS is tunnelled): allowed hosts are piped straight
through with no TLS interception, and any other host is refused with ``403`` and
recorded — so a blocked exfiltration attempt is visible in the trace, something a
plain firewall rule cannot do.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from wicklight.trace import EgressDenied, EgressDeniedPayload, dump_trace_event

logger = logging.getLogger(__name__)

_CHUNK = 65536


@dataclass(frozen=True)
class DeniedConnection:
    """A refused egress attempt."""

    host: str
    port: int
    at: datetime


DenyHandler = Callable[[DeniedConnection], None]


class EgressProxy:
    """An allowlist-enforcing HTTP CONNECT proxy."""

    def __init__(
        self, allowlist: Iterable[str], *, on_deny: DenyHandler | None = None
    ) -> None:
        self._allow = set(allowlist)
        self._on_deny = on_deny
        self._server: asyncio.AbstractServer | None = None

    async def start(self, *, host: str = "127.0.0.1", port: int = 0) -> int:
        """Start listening; returns the bound port (handy when ``port=0``)."""
        self._server = await asyncio.start_server(self._handle, host, port)
        return self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request_line = await reader.readline()
            method, _, target = request_line.decode("latin1").strip().partition(" ")
            target = target.split(" ", 1)[0]  # drop the HTTP/1.1 suffix
            if method.upper() != "CONNECT" or not target:
                await _respond(writer, "405 Method Not Allowed")
                return
            host, _, port_text = target.partition(":")
            port = int(port_text) if port_text.isdigit() else 443

            await _drain_headers(reader)

            if host not in self._allow:
                self._deny(host, port)
                await _respond(writer, "403 Forbidden")
                return

            try:
                up_reader, up_writer = await asyncio.open_connection(host, port)
            except OSError as exc:
                logger.warning("egress: upstream %s:%s failed: %s", host, port, exc)
                await _respond(writer, "502 Bad Gateway")
                return

            await _respond(writer, "200 Connection established")
            await _tunnel(reader, writer, up_reader, up_writer)
        except Exception:
            # One bad connection must never take down the proxy; log and move on.
            logger.exception("egress: error handling a connection")
        finally:
            with contextlib.suppress(OSError):
                writer.close()

    def _deny(self, host: str, port: int) -> None:
        logger.info("egress: refused %s:%s (not in allowlist)", host, port)
        if self._on_deny is not None:
            self._on_deny(
                DeniedConnection(host=host, port=port, at=datetime.now(timezone.utc))
            )


async def _respond(writer: asyncio.StreamWriter, status: str) -> None:
    writer.write(f"HTTP/1.1 {status}\r\n\r\n".encode("latin1"))
    with contextlib.suppress(OSError):
        await writer.drain()


async def _drain_headers(reader: asyncio.StreamReader) -> None:
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            return


async def _tunnel(
    c_reader: asyncio.StreamReader,
    c_writer: asyncio.StreamWriter,
    u_reader: asyncio.StreamReader,
    u_writer: asyncio.StreamWriter,
) -> None:
    async def copy(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await src.read(_CHUNK)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except OSError as exc:
            logger.debug("egress: tunnel closed: %s", exc)  # normal teardown/reset
        finally:
            with contextlib.suppress(OSError):
                dst.close()

    await asyncio.gather(copy(c_reader, u_writer), copy(u_reader, c_writer))


def trace_deny_writer(path: str | Path, *, run_id: str = "egress") -> DenyHandler:
    """A deny handler that appends an ``egress_denied`` event per refusal.

    Appends full JSONL lines (``O_APPEND``) so the proxy can record into a trace
    directory without coordinating with the run's writer.
    """
    target = Path(path)

    def handle(denied: DeniedConnection) -> None:
        event = EgressDenied(
            run_id=run_id,
            step=0,
            timestamp=denied.at,
            explain=f"egress refused: {denied.host}:{denied.port} not in allowlist",
            payload=EgressDeniedPayload(host=denied.host, port=denied.port),
        )
        line = json.dumps(dump_trace_event(event), ensure_ascii=False)
        with target.open("a", encoding="utf-8") as handle_:
            handle_.write(line + "\n")

    return handle


def main() -> int:
    """Sidecar entrypoint: serve the proxy forever, configured from the env.

    ``WICKLIGHT_EGRESS_ALLOW`` is a comma-separated host allowlist,
    ``WICKLIGHT_EGRESS_PORT`` the listen port (default 8080), and
    ``WICKLIGHT_EGRESS_TRACE`` an optional path to append ``egress_denied`` events.
    """
    import os

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    allow = [h for h in os.environ.get("WICKLIGHT_EGRESS_ALLOW", "").split(",") if h]
    port = int(os.environ.get("WICKLIGHT_EGRESS_PORT", "8080"))
    trace = os.environ.get("WICKLIGHT_EGRESS_TRACE")
    on_deny = trace_deny_writer(trace) if trace else None
    proxy = EgressProxy(allow, on_deny=on_deny)

    async def serve() -> None:
        # Bind all interfaces so the agent sidecar can reach it on the pod net.
        bound = await proxy.start(host="0.0.0.0", port=port)
        logger.info(
            "egress proxy on :%d allowing %s", bound, ", ".join(allow) or "(none)"
        )
        await asyncio.Event().wait()  # serve until the container is stopped

    with contextlib.suppress(KeyboardInterrupt):  # Ctrl+C is a clean shutdown
        asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
