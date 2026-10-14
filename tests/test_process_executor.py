"""Real spawned workers must survive bad frames and leave no child behind."""

from __future__ import annotations

import multiprocessing
import os
import threading
import time
from pathlib import Path

import numpy as np
import OpenEXR
import pytest
from process_executor_helpers import (
    no_ready_worker,
    partial_message_worker,
    selective_worker,
    slow_ready_worker,
)

from aovguard.core.analysis import AnalysisCancelled, _measure_frame
from aovguard.core.execution import (
    FrameReadError,
    FrameTimeoutError,
    FrameWorkerCrashed,
    FrameWorkerProtocolError,
)
from aovguard.core.luminance import REC709
from aovguard.core.memory import MemoryBudgetExceeded
from aovguard.io.process_executor import FrameProcessExecutor, _scalar_tree
from aovguard.io.protocol import ReaderProcessSpec
from aovguard.io.reader import OpenEXRReader


def _native_exr(path: Path, *, multipart: bool = False) -> Path:
    pixels = {
        "R": np.ones((2, 2), dtype=np.float32),
        "G": np.full((2, 2), 2.0, dtype=np.float32),
        "B": np.full((2, 2), 3.0, dtype=np.float32),
        "A": np.full((2, 2), np.nan, dtype=np.float32),
        "object_id": np.array([[16_777_216, 16_777_217], [4_294_967_295, 0]], np.uint32),
    }
    if multipart:
        OpenEXR.File([
            OpenEXR.Part({}, pixels, "left"),
            OpenEXR.Part({}, pixels, "right"),
        ]).write(str(path))
    else:
        OpenEXR.File({}, pixels).write(str(path))
    return path


def _measure(executor: FrameProcessExecutor, path: Path, **kwargs):
    return executor.measure_frame(path, REC709, 1e-5, **kwargs)


def _assert_reaped(pid: int) -> None:
    assert pid not in {child.pid for child in multiprocessing.active_children()}
    assert not any(thread.name == f"AOVGuard receiver {pid}" for thread in threading.enumerate())


@pytest.mark.parametrize("multipart", [False, True])
def test_native_process_results_match_direct_reduction_and_reuse_one_pid(tmp_path: Path, multipart: bool) -> None:
    path = _native_exr(tmp_path / "native.exr", multipart=multipart)
    expected = _measure_frame(OpenEXRReader(), path, REC709, 1e-5, None)
    with FrameProcessExecutor(ReaderProcessSpec()) as executor:
        first = _measure(executor, path)
        pid = executor.worker_pid
        assert pid is not None and pid != os.getpid()
        assert _scalar_tree(first)
        assert first == expected
        assert _measure(executor, path) == expected
        assert executor.worker_pid == pid
        assert executor.last_execution.status == "completed"
        assert executor.last_execution.mode == "isolated"
    _assert_reaped(pid)
    executor.close()


def test_memory_rejection_is_reconstructed_and_worker_can_accept_the_next_frame(tmp_path: Path) -> None:
    path = _native_exr(tmp_path / "native.exr")
    with FrameProcessExecutor(ReaderProcessSpec()) as executor:
        with pytest.raises(MemoryBudgetExceeded) as error:
            _measure(executor, path, max_memory_mb=1)
        pid = executor.worker_pid
        assert error.value.inspection.path == path
        assert error.value.estimate.estimated_mib > 1
        assert executor.last_execution.status == "memory_rejected"
        _measure(executor, path, max_memory_mb=100)
        assert executor.worker_pid == pid
    _assert_reaped(pid)


def test_read_error_retains_worker_for_a_subsequent_valid_frame(tmp_path: Path) -> None:
    missing = tmp_path / "missing.exr"
    valid = _native_exr(tmp_path / "valid.exr")
    with FrameProcessExecutor(ReaderProcessSpec()) as executor:
        with pytest.raises(FrameReadError, match="RuntimeError"):
            _measure(executor, missing)
        pid = executor.worker_pid
        assert executor.last_execution.status == "read_error"
        _measure(executor, valid)
        assert executor.worker_pid == pid
    _assert_reaped(pid)


def test_remote_decoder_error_retains_header_and_memory_evidence(tmp_path: Path) -> None:
    with FrameProcessExecutor(ReaderProcessSpec(), worker_target=selective_worker) as executor:
        with pytest.raises(FrameReadError, match="decoder rejected") as error:
            _measure(executor, tmp_path / "readerror.exr")
        assert error.value.inspection.path == tmp_path / "readerror.exr"
        assert error.value.estimate is not None
        assert executor.last_inspection == error.value.inspection
        assert executor.last_execution.status == "read_error"


def test_dead_idle_worker_is_reaped_and_replaced_before_the_next_request(tmp_path: Path) -> None:
    path = _native_exr(tmp_path / "native.exr")
    with FrameProcessExecutor(ReaderProcessSpec()) as executor:
        _measure(executor, path)
        pid = executor.worker_pid
        executor._process.terminate()
        executor._process.join(2)
        _measure(executor, path)
        assert executor.worker_pid != pid
    _assert_reaped(pid)


@pytest.mark.parametrize("prefix,error,status", [
    ("timeout", FrameTimeoutError, "timeout"),
    ("crash", FrameWorkerCrashed, "crash"),
    ("stale", FrameWorkerProtocolError, "protocol_error"),
    ("badresult", FrameWorkerProtocolError, "protocol_error"),
    ("badpickle", FrameWorkerProtocolError, "protocol_error"),
])
def test_fault_reaps_worker_and_lazily_restarts_for_the_next_frame(
    tmp_path: Path, prefix: str, error: type[Exception], status: str,
) -> None:
    valid = _native_exr(tmp_path / "valid.exr")
    executor = FrameProcessExecutor(ReaderProcessSpec(), worker_target=selective_worker)
    try:
        with pytest.raises(error) as failure:
            _measure(executor, tmp_path / f"{prefix}.exr", timeout_seconds=0.3)
        old_pid = executor.last_execution.worker_pid
        assert executor.last_execution.status == status
        assert failure.value.inspection.path == tmp_path / f"{prefix}.exr"
        assert failure.value.estimate is not None
        assert executor.worker_pid is None
        _assert_reaped(old_pid)
        _measure(executor, valid, timeout_seconds=2)
        assert executor.worker_pid != old_pid
    finally:
        executor.close()


def test_cancellation_interrupts_a_real_worker_and_reaps_it(tmp_path: Path) -> None:
    cancelled = threading.Event()
    executor = FrameProcessExecutor(ReaderProcessSpec(), worker_target=selective_worker)

    def cancel_after_header():
        if executor.last_inspection is not None:
            cancelled.set()
        return cancelled.is_set()

    started = time.monotonic()
    try:
        with pytest.raises(AnalysisCancelled):
            _measure(executor, tmp_path / "timeout.exr", cancellation_callback=cancel_after_header)
        pid = executor.last_execution.worker_pid
        assert executor.last_execution.status == "cancelled"
        assert executor.worker_pid is None
        assert time.monotonic() - started < 5
        _assert_reaped(pid)
    finally:
        executor.close()


def test_preexisting_cancel_creates_no_child(tmp_path: Path) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    try:
        with pytest.raises(AnalysisCancelled):
            _measure(executor, tmp_path / "unused.exr", cancellation_callback=lambda: True)
        assert executor.worker_pid is None
    finally:
        executor.close()


def test_startup_has_its_own_timeout_and_cleanup(tmp_path: Path) -> None:
    executor = FrameProcessExecutor(
        ReaderProcessSpec(), startup_timeout_seconds=0.2, worker_target=no_ready_worker,
    )
    try:
        with pytest.raises(FrameTimeoutError) as error:
            _measure(executor, tmp_path / "unused.exr", timeout_seconds=5)
        assert error.value.stage == "startup"
        assert error.value.timeout_seconds == 0.2
        _assert_reaped(error.value.worker_pid)
    finally:
        executor.close()


def test_frame_deadline_begins_after_ready_and_excludes_slow_startup(tmp_path: Path) -> None:
    with FrameProcessExecutor(ReaderProcessSpec(), worker_target=slow_ready_worker) as executor:
        _measure(executor, tmp_path / "unused.exr", timeout_seconds=0.15)
        assert executor.last_execution.status == "completed"
        assert executor.last_execution.elapsed_seconds >= 0.4


@pytest.mark.skipif(os.name == "nt", reason="Raw POSIX Connection fragments differ from Windows message pipes.")
def test_partially_written_ipc_cannot_block_timeout_or_receiver_cleanup(tmp_path: Path) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec(), worker_target=partial_message_worker)
    try:
        with pytest.raises(FrameTimeoutError):
            _measure(executor, tmp_path / "partial.exr", timeout_seconds=0.3)
        pid = executor.last_execution.worker_pid
        _assert_reaped(pid)
    finally:
        executor.close()


def test_closed_executor_cannot_start_a_new_child(tmp_path: Path) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec())
    executor.close()
    with pytest.raises(RuntimeError, match="closed"):
        _measure(executor, tmp_path / "unused.exr")


def test_unknown_reader_backend_fails_during_handshake_and_reaps_worker(tmp_path: Path) -> None:
    executor = FrameProcessExecutor(ReaderProcessSpec(backend="unknown"))
    try:
        with pytest.raises(FrameWorkerProtocolError, match="Unsupported reader backend") as error:
            _measure(executor, tmp_path / "unused.exr")
        assert error.value.stage == "startup"
        _assert_reaped(error.value.worker_pid)
    finally:
        executor.close()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True])
def test_executor_rejects_invalid_deadlines_without_spawning(timeout: float) -> None:
    with pytest.raises(ValueError):
        FrameProcessExecutor(ReaderProcessSpec(), startup_timeout_seconds=timeout)
