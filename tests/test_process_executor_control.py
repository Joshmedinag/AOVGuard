"""Control-plane failures must preserve deadlines and clean process resources."""

from __future__ import annotations

import queue
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from aovguard.core.analysis import _MetricAccumulator
from aovguard.core.execution import (
    FrameTimeoutError,
    FrameWorkerCrashed,
    FrameWorkerProtocolError,
    WorkerCleanupError,
)
from aovguard.core.luminance import REC709
from aovguard.core.memory import estimate_frame_memory
from aovguard.io import process_executor as module
from aovguard.io.inspector import build_file_inspection
from aovguard.io.process_executor import FrameProcessExecutor, _validate_result
from aovguard.io.protocol import ReaderProcessSpec


class ProcessStub:
    pid = 999_999_991

    def __init__(self, *, alive=True, resist_terminate=False, resist_kill=False, start_error=None) -> None:
        self.alive = alive
        self.resist_terminate = resist_terminate
        self.resist_kill = resist_kill
        self.start_error = start_error
        self.exitcode = None if alive else 23
        self.calls: list = []
        self.closed = False

    def start(self):
        self.calls.append("start")
        if self.start_error:
            raise self.start_error

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.calls.append("terminate")
        if not self.resist_terminate:
            self.alive = False
            self.exitcode = -15

    def kill(self):
        self.calls.append("kill")
        if not self.resist_kill:
            self.alive = False
            self.exitcode = -9

    def join(self, timeout):
        self.calls.append(("join", timeout))

    def close(self):
        self.closed = True


class EndpointStub:
    def __init__(self, messages=(), *, send_error=None):
        self.messages = iter(messages)
        self.send_error = send_error
        self.closed = False

    def send(self, message):
        if self.send_error:
            raise self.send_error

    def recv(self):
        try:
            return next(self.messages)
        except StopIteration:
            raise EOFError from None

    def close(self):
        self.closed = True


def _inspection(path=Path("frame.exr")):
    return build_file_inspection(path=path, width=1, height=1, channels=("R", "G", "B"))


def _result(inspection=None):
    return (inspection or _inspection(), {"beauty": _MetricAccumulator(1e-5, REC709)}, {}, None)


def _install(executor, monkeypatch, events, *, process=None, endpoint=None):
    process = process or ProcessStub()
    endpoint = endpoint or EndpointStub()

    def start(_cancellation_callback):
        executor._process = process
        executor._connection = endpoint
        executor._messages = queue.Queue()
        for event in events:
            executor._messages.put(event)

    monkeypatch.setattr(executor, "_start", start)
    return process, endpoint


@pytest.mark.parametrize("value", [
    (), (_inspection(), {"beauty": object()}, {}, None),
    (_inspection(), {}, {"beauty": "bad"}, None),
    (_inspection(), {}, {"beauty": {"R": object()}}, None),
    (_inspection(), {}, {}, {}),
    (replace(_inspection(), channels=(np.ones(1),)), {}, {}, None),
])
def test_non_scalar_or_malformed_measurements_are_rejected(value) -> None:
    with pytest.raises(ValueError):
        _validate_result(value)


@pytest.mark.parametrize("message", [
    [], {"kind": "header", "id": 9},
    {"kind": "header", "id": 1, "inspection": "bad", "estimate": None},
    {"kind": "header", "id": 1, "inspection": _inspection(), "estimate": {}},
    {"kind": "header", "id": 1, "inspection": _inspection(Path("other.exr")), "estimate": None},
    {"kind": "stage", "id": 1, "stage": "unknown"},
    {"kind": "result", "id": 1, "result": (), "status": "completed"},
    {"kind": "result", "id": 1, "result": _result(), "status": "unsupported_structure"},
    {"kind": "result", "id": 1, "result": _result(_inspection(Path("other.exr"))), "status": "completed"},
    {"kind": "error", "id": 1, "error": "memory_rejected"},
    {"kind": "error", "id": 1, "error": "memory_rejected", "inspection": _inspection(), "estimate": estimate_frame_memory(_inspection()), "max_memory_mb": None},
    {"kind": "error", "id": 1, "error": "read_error", "message": 7},
    {"kind": "unknown", "id": 1},
])
def test_protocol_failures_reap_the_worker_instead_of_accepting_bad_results(monkeypatch, message) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process, endpoint = _install(executor, monkeypatch, [("message", message)])
    with pytest.raises(FrameWorkerProtocolError):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5, timeout_seconds=1)
    assert process.closed and endpoint.closed
    assert executor.worker_pid is None
    assert executor.last_execution.status == "protocol_error"
    executor.close()


@pytest.mark.parametrize("transport_kind,error", [
    ("transport_closed", FrameWorkerCrashed), ("transport_invalid", FrameWorkerProtocolError),
])
def test_transport_errors_reap_the_worker(monkeypatch, transport_kind, error) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process, endpoint = _install(executor, monkeypatch, [(transport_kind, "broken")])
    with pytest.raises(error):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5, timeout_seconds=1)
    assert process.closed and endpoint.closed


def test_worker_exit_without_a_message_is_detected(monkeypatch) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process, endpoint = _install(executor, monkeypatch, [], process=ProcessStub(alive=False))
    with pytest.raises(FrameWorkerCrashed):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5, timeout_seconds=1)
    assert process.closed and endpoint.closed


def test_request_send_failure_reaps_the_worker(monkeypatch) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process, endpoint = _install(executor, monkeypatch, [], endpoint=EndpointStub(send_error=BrokenPipeError()))
    with pytest.raises(FrameWorkerCrashed):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    assert process.closed and endpoint.closed


def test_cleanup_kills_after_terminate_does_not_finish() -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec(), termination_grace_seconds=0.1)
    process = ProcessStub(resist_terminate=True)
    endpoint = EndpointStub()
    executor._process, executor._connection = process, endpoint

    executor.close()

    assert "terminate" in process.calls and "kill" in process.calls
    assert process.closed and endpoint.closed
    executor.close()


def test_cleanup_failure_is_fatal_after_bounded_terminate_and_kill() -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec(), termination_grace_seconds=0.1)
    process = ProcessStub(resist_terminate=True, resist_kill=True)
    executor._process = process
    with pytest.raises(WorkerCleanupError) as error:
        executor.close()
    assert error.value.worker_pid == process.pid
    assert process.calls.count("terminate") == 1 and process.calls.count("kill") == 1
    assert [call for call in process.calls if isinstance(call, tuple)] == [
        ("join", 0.1), ("join", 0.1),
    ]
    with pytest.raises(RuntimeError, match="closed"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    # This object is a deterministic fake, not an unreaped operating-system child.
    executor._process = None


def test_unjoined_receiver_poisoning_prevents_another_request() -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec(), termination_grace_seconds=0.1)
    process = ProcessStub(alive=False)
    executor._process = process
    executor._connection = EndpointStub()
    executor._receiver = SimpleNamespace(ident=1, join=lambda _timeout: None, is_alive=lambda: True)
    with pytest.raises(WorkerCleanupError, match="receiver"):
        executor.close()
    with pytest.raises(RuntimeError, match="closed"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    executor._receiver = None
    executor.close()


@pytest.mark.parametrize("operation", ["terminate", "join", "close_endpoint"])
def test_operational_cleanup_exceptions_are_fatal_and_poison_the_executor(operation, monkeypatch) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process = ProcessStub()
    endpoint = EndpointStub()
    executor._process, executor._connection = process, endpoint

    def fail(*_args):
        raise PermissionError(f"cannot perform {operation}")

    if operation == "close_endpoint":
        monkeypatch.setattr(endpoint, "close", fail)
    else:
        monkeypatch.setattr(process, operation, fail)
    with pytest.raises(WorkerCleanupError, match="PermissionError") as error:
        executor._cleanup()
    assert error.value.worker_pid == process.pid
    assert error.value.stage == "cleanup"
    with pytest.raises(RuntimeError, match="closed"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    # Restore the deterministic fake operation and allow an explicit retry.
    monkeypatch.undo()
    executor.close()


def test_cleanup_interrupt_poisoning_preserves_keyboard_interrupt(monkeypatch) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    process = ProcessStub()
    executor._process = process

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(process, "terminate", interrupt)
    with pytest.raises(KeyboardInterrupt):
        executor._cleanup()
    with pytest.raises(RuntimeError, match="closed"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    monkeypatch.undo()
    executor.close()


def test_receiver_start_failure_reaps_the_already_started_process(monkeypatch) -> None:
    parent, child = EndpointStub(), EndpointStub()
    process = ProcessStub()
    context = SimpleNamespace(Pipe=lambda **_kwargs: (parent, child), Process=lambda **_kwargs: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _name: context)

    class BrokenThread:
        ident = None

        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("receiver thread could not start")

    monkeypatch.setattr(module.threading, "Thread", BrokenThread)
    executor = FrameProcessExecutor(ReaderProcessSpec())
    with pytest.raises(FrameWorkerProtocolError, match="receiver thread"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    assert parent.closed and child.closed and process.closed
    assert "terminate" in process.calls


def test_receiver_blocked_in_partial_recv_does_not_block_control_timeout(monkeypatch) -> None:
    entered, released = threading.Event(), threading.Event()

    class PartialEndpoint(EndpointStub):
        def recv(self):
            entered.set()
            released.wait(5)
            raise EOFError

        def close(self):
            super().close()
            released.set()

    executor = FrameProcessExecutor(ReaderProcessSpec(), termination_grace_seconds=0.1)
    process = ProcessStub()
    endpoint = PartialEndpoint()

    def start(_callback):
        executor._process, executor._connection = process, endpoint
        executor._messages = queue.Queue()
        executor._receiver = threading.Thread(
            target=module._receiver_main, args=(endpoint, executor._messages), daemon=True,
        )
        executor._receiver.start()
        assert entered.wait(1)

    monkeypatch.setattr(executor, "_start", start)
    with pytest.raises(FrameTimeoutError):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5, timeout_seconds=0.1)
    assert process.closed and endpoint.closed
    assert released.is_set()
    assert executor._receiver is None


def test_spawn_start_failure_closes_both_endpoints_and_process_handle(monkeypatch) -> None:
    parent, child = EndpointStub(), EndpointStub()
    process = ProcessStub(alive=False, start_error=RuntimeError("spawn could not start"))
    context = SimpleNamespace(Pipe=lambda **_kwargs: (parent, child), Process=lambda **_kwargs: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _name: context)
    executor = FrameProcessExecutor(ReaderProcessSpec())

    with pytest.raises(FrameWorkerProtocolError, match="spawn could not start"):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)

    assert parent.closed and child.closed and process.closed
    assert executor.worker_pid is None


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, SystemExit])
def test_interrupted_spawn_with_no_child_preserves_control_exception_and_closes_handles(monkeypatch, interrupt) -> None:
    parent, child = EndpointStub(), EndpointStub()
    process = ProcessStub(alive=False, start_error=interrupt())
    process.pid = None
    context = SimpleNamespace(Pipe=lambda **_kwargs: (parent, child), Process=lambda **_kwargs: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _name: context)
    executor = FrameProcessExecutor(ReaderProcessSpec())

    with pytest.raises(interrupt):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)

    assert parent.closed and child.closed and process.closed
    assert not any(isinstance(call, tuple) for call in process.calls)
    assert executor.worker_pid is None
    executor.close()


def test_interrupted_spawn_after_child_start_reaps_that_child(monkeypatch) -> None:
    parent, child = EndpointStub(), EndpointStub()
    process = ProcessStub(start_error=KeyboardInterrupt())
    context = SimpleNamespace(Pipe=lambda **_kwargs: (parent, child), Process=lambda **_kwargs: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _name: context)
    executor = FrameProcessExecutor(ReaderProcessSpec())

    with pytest.raises(KeyboardInterrupt):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)

    assert "terminate" in process.calls
    assert parent.closed and child.closed and process.closed
    executor.close()


@pytest.mark.parametrize("ready", [
    None, {"kind": "ready", "protocol": 99, "pid": ProcessStub.pid},
    {"kind": "startup_error", "message": "factory failed"},
])
def test_invalid_startup_handshakes_are_rejected_and_cleaned(monkeypatch, ready) -> None:
    parent, child = EndpointStub((ready,)), EndpointStub()
    process = ProcessStub()
    context = SimpleNamespace(Pipe=lambda **_kwargs: (parent, child), Process=lambda **_kwargs: process)
    monkeypatch.setattr(module.multiprocessing, "get_context", lambda _name: context)
    executor = FrameProcessExecutor(ReaderProcessSpec())
    with pytest.raises(FrameWorkerProtocolError):
        executor.measure_frame(Path("frame.exr"), REC709, 1e-5)
    assert parent.closed and child.closed and process.closed
