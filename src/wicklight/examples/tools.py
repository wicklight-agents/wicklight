"""Entry-point tool plugins for the example agents, seeded from a world file.

Each class has a no-argument constructor (so it registers as a ``wicklight.tools``
entry point) and binds to a process-wide :class:`MockWorld` loaded once from
``WICKLIGHT_MOCK_WORLD``. The behaviour is the in-memory mock behaviour; only the
world's *source* differs (a file, not an injected object), which is what lets the
example scenarios run inside a deployed container.
"""

from __future__ import annotations

import os
from pathlib import Path

from wicklight.tools.mock import (
    DeleteFile,
    MakePayment,
    MockWorld,
    ReadFile,
    ReadInbox,
    SendEmail,
)

_WORLD_ENV = "WICKLIGHT_MOCK_WORLD"
_world: MockWorld | None = None


def shared_world() -> MockWorld:
    """The process-wide example world, loaded once from ``WICKLIGHT_MOCK_WORLD``.

    An unset or missing file yields an empty world rather than an error, so the
    tools are always usable (an empty inbox, no files, an empty ledger).
    """
    global _world
    if _world is None:
        path = os.environ.get(_WORLD_ENV)
        if path and Path(path).is_file():
            _world = MockWorld.from_yaml(Path(path).read_text(encoding="utf-8"))
        else:
            _world = MockWorld()
    return _world


class ExampleReadInbox(ReadInbox):
    def __init__(self) -> None:
        super().__init__(shared_world())


class ExampleSendEmail(SendEmail):
    def __init__(self) -> None:
        super().__init__(shared_world())


class ExampleReadFile(ReadFile):
    def __init__(self) -> None:
        super().__init__(shared_world())


class ExampleDeleteFile(DeleteFile):
    def __init__(self) -> None:
        super().__init__(shared_world())


class ExampleMakePayment(MakePayment):
    def __init__(self) -> None:
        super().__init__(shared_world())
