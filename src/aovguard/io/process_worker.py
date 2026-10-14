"""Spawn-safe worker reducing frames locally and transferring scalar results."""

from __future__ import annotations

import os
from collections.abc import Collection
from multiprocessing.connection import Connection
from pathlib import Path

from aovguard.core.luminance import LuminanceWeights
from aovguard.core.memory import MemoryBudgetExceeded, estimate_frame_memory
from aovguard.core.models import FileInspection, FrameData
from aovguard.io.protocol import ReaderProcessSpec
from aovguard.io.reader import OpenEXRReader

PROCESS_PROTOCOL_VERSION = 1


def frame_worker_main(connection: Connection, spec: ReaderProcessSpec) -> None:
    """Handle sequential requests until shutdown, retaining arrays in this child.

    Only the programmatic worker-target seam can replace this function. Preset
    data and CLI arguments cannot select arbitrary worker code or test hooks.
    Exceptions are converted into data envelopes instead of being pickled.
    """

    from aovguard.core.analysis import _measure_frame

    request_id: int | None = None

    class ReportingReader(OpenEXRReader):
        def inspect(self, path: Path) -> FileInspection:
            inspection = super().inspect(path)
            try:
                estimate = estimate_frame_memory(inspection)
            except ValueError:
                estimate = None
            connection.send({
                "kind": "header", "id": request_id,
                "inspection": inspection, "estimate": estimate,
            })
            return inspection

        def read_frame(self, path: Path, requested_aovs: Collection[str] | None = None) -> FrameData:
            frame = super().read_frame(path, requested_aovs)
            connection.send({"kind": "stage", "id": request_id, "stage": "reduction"})
            return frame

        def read_frame_with_memory_budget(self, path: Path, max_memory_mb: float) -> FrameData:
            frame = super().read_frame_with_memory_budget(path, max_memory_mb)
            connection.send({"kind": "stage", "id": request_id, "stage": "reduction"})
            return frame

    try:
        if spec.backend != "openexr":
            connection.send({"kind": "startup_error", "message": f"Unsupported reader backend: {spec.backend!r}"})
            return
        reader = ReportingReader(dict(spec.category_overrides))
        connection.send({
            "kind": "ready", "protocol": PROCESS_PROTOCOL_VERSION, "pid": os.getpid(),
        })
        while True:
            try:
                request = connection.recv()
            except EOFError:
                return
            if not isinstance(request, dict):
                connection.send({"kind": "protocol_error", "id": None, "message": "Request must be an object."})
                return
            if request.get("kind") == "shutdown":
                return
            request_id = request.get("id")
            if request.get("kind") != "measure" or type(request_id) is not int:
                connection.send({"kind": "protocol_error", "id": request_id, "message": "Invalid frame request."})
                return
            try:
                result = _measure_frame(
                    reader, Path(request["path"]),
                    LuminanceWeights.from_values(request["weights"]),
                    float(request["threshold"]), None,
                    request["max_memory_mb"],
                )
                status = "unsupported_structure" if result[0].unsupported_reason else "completed"
                connection.send({"kind": "result", "id": request_id, "result": result, "status": status})
            except MemoryBudgetExceeded as exc:
                connection.send({
                    "kind": "error", "id": request_id, "error": "memory_rejected",
                    "inspection": exc.inspection, "estimate": exc.estimate,
                    "max_memory_mb": exc.max_memory_mb, "message": str(exc),
                })
            except Exception as exc:
                connection.send({
                    "kind": "error", "id": request_id, "error": "read_error",
                    "message": f"{type(exc).__name__}: {exc}",
                })
    except (BrokenPipeError, EOFError, OSError):
        return
    except Exception as exc:
        try:
            connection.send({"kind": "startup_error", "message": f"{type(exc).__name__}: {exc}"})
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()
