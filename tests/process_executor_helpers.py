"""Importable spawn targets for faults unavailable through presets or the CLI."""

from __future__ import annotations

import os
import struct
import time
from multiprocessing.connection import Connection
from pathlib import Path

from aovguard.core.memory import estimate_frame_memory
from aovguard.io.inspector import build_file_inspection
from aovguard.io.protocol import ReaderProcessSpec


def _ready(connection: Connection) -> None:
    connection.send({"kind": "ready", "protocol": 1, "pid": os.getpid()})


def _header(connection: Connection, request: dict):
    inspection = build_file_inspection(
        path=Path(request["path"]), width=1, height=1, channels=("R", "G", "B"),
    )
    connection.send({
        "kind": "header", "id": request["id"],
        "inspection": inspection, "estimate": estimate_frame_memory(inspection),
    })
    return inspection


def selective_worker(connection: Connection, spec: ReaderProcessSpec) -> None:
    from aovguard.core.analysis import _measure_frame
    from aovguard.core.luminance import LuminanceWeights
    from aovguard.io.reader import OpenEXRReader

    _ready(connection)
    try:
        while True:
            request = connection.recv()
            if request["kind"] == "shutdown":
                return
            name = Path(request["path"]).name
            _header(connection, request)
            if name.startswith("timeout"):
                time.sleep(60)
            elif name.startswith("crash"):
                os._exit(23)
            elif name.startswith("stale"):
                connection.send({"kind": "header", "id": request["id"] + 1})
            elif name.startswith("badresult"):
                connection.send({"kind": "result", "id": request["id"], "result": (), "status": "completed"})
            elif name.startswith("badpickle"):
                connection.send_bytes(b"invalid pickle")
            elif name.startswith("readerror"):
                connection.send({"kind": "error", "id": request["id"], "error": "read_error", "message": "A decoder rejected this frame."})
            else:
                result = _measure_frame(
                    OpenEXRReader(dict(spec.category_overrides)), Path(request["path"]),
                    LuminanceWeights.from_values(request["weights"]), request["threshold"],
                    None, request["max_memory_mb"],
                )
                connection.send({"kind": "result", "id": request["id"], "result": result, "status": "completed"})
    finally:
        connection.close()


def no_ready_worker(connection: Connection, _spec: ReaderProcessSpec) -> None:
    try:
        time.sleep(60)
    finally:
        connection.close()


def slow_ready_worker(connection: Connection, _spec: ReaderProcessSpec) -> None:
    from aovguard.core.analysis import _MetricAccumulator
    from aovguard.core.luminance import REC709

    time.sleep(0.4)
    _ready(connection)
    try:
        while True:
            request = connection.recv()
            if request["kind"] == "shutdown":
                return
            inspection = _header(connection, request)
            result = (inspection, {"beauty": _MetricAccumulator(1e-5, REC709)}, {}, None)
            connection.send({"kind": "result", "id": request["id"], "result": result, "status": "completed"})
    finally:
        connection.close()


def partial_message_worker(connection: Connection, _spec: ReaderProcessSpec) -> None:
    """Write only the first fragment of a POSIX Connection packet, then stall."""

    _ready(connection)
    try:
        request = connection.recv()
        _header(connection, request)
        os.write(connection.fileno(), struct.pack("!i", 100_000) + b"incomplete pickle")
        time.sleep(60)
    finally:
        connection.close()
