"""Direct worker-envelope tests complement the real spawned-process regressions."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import OpenEXR
import pytest

from aovguard.core.models import FrameData
from aovguard.io.inspector import build_file_inspection
from aovguard.io.process_executor import _scalar_tree
from aovguard.io.process_worker import frame_worker_main
from aovguard.io.protocol import ReaderProcessSpec


class FakeConnection:
    def __init__(self, requests=(), *, receive_error=None, send_errors=()) -> None:
        self.requests = iter(requests)
        self.receive_error = receive_error
        self.send_errors = iter(send_errors)
        self.messages: list[dict] = []
        self.closed = False

    def recv(self):
        if self.receive_error is not None:
            raise self.receive_error
        try:
            return next(self.requests)
        except StopIteration:
            raise EOFError from None

    def send(self, message):
        failure = next(self.send_errors, None)
        if failure is not None:
            raise failure
        self.messages.append(message)

    def close(self):
        self.closed = True


def _request(path: Path, request_id: int = 1, **kwargs) -> dict:
    return {
        "kind": "measure", "id": request_id, "path": str(path),
        "weights": (0.2126, 0.7152, 0.0722), "threshold": 1e-5,
        "max_memory_mb": None, **kwargs,
    }


def test_worker_reduces_real_frames_and_recovers_after_memory_rejection(tmp_path: Path) -> None:
    path = tmp_path / "native.exr"
    OpenEXR.File({}, {
        name: np.ones((2, 2), np.float32) for name in ("R", "G", "B")
    }).write(str(path))
    connection = FakeConnection([
        _request(path, 1, max_memory_mb=1),
        _request(path, 2, max_memory_mb=100),
        _request(path, 3),
        {"kind": "shutdown"},
    ])

    frame_worker_main(connection, ReaderProcessSpec())

    assert connection.closed
    assert connection.messages[0]["kind"] == "ready"
    rejected = next(message for message in connection.messages if message.get("error") == "memory_rejected")
    assert rejected["id"] == 1
    assert rejected["inspection"].path == path
    assert rejected["estimate"].estimated_mib > rejected["max_memory_mb"]
    results = [message for message in connection.messages if message["kind"] == "result"]
    assert [message["id"] for message in results] == [2, 3]
    assert all(message["status"] == "completed" for message in results)
    assert all(_scalar_tree(message["result"]) for message in results)
    assert all(message["result"][1]["beauty"].pixel_count == 4 for message in results)
    assert any(message["kind"] == "stage" for message in connection.messages)


def test_worker_read_error_is_an_envelope_and_next_request_still_runs(tmp_path: Path) -> None:
    path = tmp_path / "missing.exr"
    connection = FakeConnection([_request(path), _request(path, 2, threshold="bad"), {"kind": "shutdown"}])

    frame_worker_main(connection, ReaderProcessSpec())

    errors = [message for message in connection.messages if message["kind"] == "error"]
    assert [message["id"] for message in errors] == [1, 2]
    assert all(message["error"] == "read_error" for message in errors)
    assert "RuntimeError" in errors[0]["message"]
    assert "ValueError" in errors[1]["message"]
    assert connection.closed


@pytest.mark.parametrize("frame_request", [[], {"kind": "invalid", "id": 1}, {"kind": "measure", "id": True}])
def test_invalid_requests_are_rejected_and_worker_closes(frame_request) -> None:
    connection = FakeConnection([frame_request])

    frame_worker_main(connection, ReaderProcessSpec())

    assert connection.messages[-1]["kind"] == "protocol_error"
    assert connection.closed


def test_unsupported_backend_is_rejected_before_ready() -> None:
    connection = FakeConnection()

    frame_worker_main(connection, ReaderProcessSpec(backend="unknown"))

    assert connection.messages[0]["kind"] == "startup_error"
    assert connection.closed


def test_reader_construction_failure_is_a_startup_envelope() -> None:
    connection = FakeConnection()

    frame_worker_main(connection, ReaderProcessSpec(category_overrides=(("beauty", "invalid"),)))

    assert connection.messages[0]["kind"] == "startup_error"
    assert "ValueError" in connection.messages[0]["message"]
    assert connection.closed


@pytest.mark.parametrize("receive_error", [EOFError(), OSError("broken endpoint")])
def test_worker_releases_endpoint_when_parent_transport_ends(receive_error: Exception) -> None:
    connection = FakeConnection(receive_error=receive_error)

    frame_worker_main(connection, ReaderProcessSpec())

    assert connection.closed


@pytest.mark.parametrize("send_errors", [
    (BrokenPipeError("closed"),),
    (RuntimeError("send failure"), BrokenPipeError("cannot report it")),
])
def test_worker_closes_when_result_transport_or_error_reporting_fails(send_errors) -> None:
    connection = FakeConnection(send_errors=send_errors)

    frame_worker_main(connection, ReaderProcessSpec())

    assert connection.closed


def test_deep_structure_reports_header_without_a_flat_memory_estimate(monkeypatch, tmp_path: Path) -> None:
    inspection = build_file_inspection(
        path=tmp_path / "deep.exr", width=1, height=1, channels=("Z",), is_deep=True,
    )

    class DeepReader:
        def __init__(self, _overrides) -> None:
            pass

        def inspect(self, path):
            return inspection

        def read_frame(self, path, requested_aovs=None):
            header = self.inspect(path)
            return FrameData(path, 1, 1, header, {})

        def read_frame_with_memory_budget(self, path, max_memory_mb):
            return self.read_frame(path)

    monkeypatch.setattr("aovguard.io.process_worker.OpenEXRReader", DeepReader)
    connection = FakeConnection([_request(inspection.path), {"kind": "shutdown"}])

    frame_worker_main(connection, ReaderProcessSpec())

    header = next(message for message in connection.messages if message["kind"] == "header")
    assert header["estimate"] is None
    assert connection.messages[-1]["status"] == "unsupported_structure"
