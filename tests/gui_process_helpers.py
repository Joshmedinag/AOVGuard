"""Spawn-importable process targets for GUI lifetime tests; no Qt dependency."""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from aovguard.core.memory import estimate_frame_memory
from aovguard.io.protocol import ReaderProcessSpec
from aovguard.io.reader import OpenEXRReader


def stall_after_real_header(connection: Connection, spec: ReaderProcessSpec, *, started: Any) -> None:
    """Inspect a real EXR, then simulate a non-returning frame operation."""

    try:
        connection.send({"kind": "ready", "protocol": 1, "pid": os.getpid()})
        request = connection.recv()
        inspection = OpenEXRReader(dict(spec.category_overrides)).inspect(Path(request["path"]))
        connection.send({
            "kind": "header", "id": request["id"], "inspection": inspection,
            "estimate": estimate_frame_memory(inspection),
        })
        started.set()
        time.sleep(60)
    finally:
        connection.close()
