"""Persistent spawn-process execution with bounded waits and scalar-only IPC."""

from __future__ import annotations

import math
import multiprocessing
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import fields, is_dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from aovguard.core.execution import (
    FrameExecutionError,
    FrameReadError,
    FrameTimeoutError,
    FrameWorkerCrashed,
    FrameWorkerProtocolError,
    WorkerCleanupError,
)
from aovguard.core.luminance import LuminanceWeights
from aovguard.core.memory import MemoryBudgetExceeded, MemoryEstimate, validate_memory_budget
from aovguard.core.models import FileInspection, FrameExecutionRecord
from aovguard.io.process_worker import PROCESS_PROTOCOL_VERSION, frame_worker_main
from aovguard.io.protocol import ReaderProcessSpec

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess

    from aovguard.core.analysis import _ChannelMetricAccumulator, _MetricAccumulator

FrameMeasurement = tuple[
    FileInspection,
    dict[str, "_MetricAccumulator"],
    dict[str, dict[str, "_ChannelMetricAccumulator"]],
    MemoryEstimate | None,
]
WorkerTarget = Callable[[Connection, ReaderProcessSpec], None]
_POLL_SECONDS = 0.05


def _receiver_main(connection: Connection, messages: queue.Queue[tuple[str, Any]]) -> None:
    """Receive on a daemon thread so partial IPC never blocks the control loop."""

    try:
        while True:
            messages.put(("message", connection.recv()))
    except (EOFError, OSError) as exc:
        messages.put(("transport_closed", str(exc)))
    except Exception as exc:
        messages.put(("transport_invalid", f"{type(exc).__name__}: {exc}"))


def _scalar_tree(value: object) -> bool:
    if value is None or isinstance(value, (str, int, float, bool, Path)):
        return True
    if isinstance(value, (tuple, list)):
        return all(_scalar_tree(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _scalar_tree(item) for key, item in value.items())
    if is_dataclass(value) and not isinstance(value, type):
        return all(_scalar_tree(getattr(value, field.name)) for field in fields(value))
    return False


def _validate_result(value: Any) -> FrameMeasurement:
    from aovguard.core.analysis import _ChannelMetricAccumulator, _MetricAccumulator

    if not isinstance(value, tuple) or len(value) != 4 or not isinstance(value[0], FileInspection):
        raise ValueError("Worker result must be a four-field scalar measurement.")
    inspection, colors, channels, estimate = value
    if not isinstance(colors, dict) or any(
        not isinstance(name, str) or not isinstance(metric, _MetricAccumulator)
        for name, metric in colors.items()
    ):
        raise ValueError("Worker color statistics have an invalid structure.")
    if not isinstance(channels, dict) or any(
        not isinstance(name, str) or not isinstance(channel_metrics, dict)
        or any(not isinstance(channel, str) or not isinstance(metric, _ChannelMetricAccumulator)
               for channel, metric in channel_metrics.items())
        for name, channel_metrics in channels.items()
    ):
        raise ValueError("Worker channel statistics have an invalid structure.")
    if estimate is not None and not isinstance(estimate, MemoryEstimate):
        raise ValueError("Worker memory estimate has an invalid structure.")
    if not _scalar_tree((inspection, colors, channels, estimate)):
        raise ValueError("Worker result contains non-scalar buffers or unsupported objects.")
    return cast(FrameMeasurement, value)


def _positive_seconds(value: float, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite positive number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number.")
    return number


class FrameProcessExecutor:
    """Reuse one spawned worker for a sequential analysis job.

    Each request starts its deadline after the ready handshake, so interpreter
    startup has its own timeout. On timeout, crash or cancellation the worker
    is reaped before another frame can spawn a replacement. Received pixels
    never enter the parent: the native worker reduces them into scalar models.
    """

    def __init__(
        self,
        spec: ReaderProcessSpec,
        *,
        startup_timeout_seconds: float = 30.0,
        termination_grace_seconds: float = 1.0,
        worker_target: WorkerTarget | None = None,
    ) -> None:
        """Configure lazy spawn and bounded cleanup; no child starts here."""

        self.spec = spec
        self.startup_timeout_seconds = _positive_seconds(startup_timeout_seconds, "Startup timeout")
        self.termination_grace_seconds = _positive_seconds(termination_grace_seconds, "Termination grace")
        self._target = worker_target or frame_worker_main
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._messages: queue.Queue[tuple[str, Any]] | None = None
        self._receiver: threading.Thread | None = None
        self._closed = False
        self._inflight = False
        self._request_id = 0
        self._last_execution: FrameExecutionRecord | None = None
        self._last_inspection: FileInspection | None = None
        self._last_estimate: MemoryEstimate | None = None

    @property
    def last_execution(self) -> FrameExecutionRecord | None:
        """Return execution details for the most recent request, including failures."""

        return self._last_execution

    @property
    def worker_pid(self) -> int | None:
        """Return the current worker PID while its process handle is retained."""

        return self._process.pid if self._process is not None else None

    @property
    def last_inspection(self) -> FileInspection | None:
        """Return header evidence retained for the most recent request."""

        return self._last_inspection

    @property
    def last_estimate(self) -> MemoryEstimate | None:
        """Return the last header's optional conservative memory estimate."""

        return self._last_estimate

    def __enter__(self) -> FrameProcessExecutor:
        """Allow deterministic worker cleanup with a context manager."""

        return self

    def __exit__(self, *_exc: object) -> None:
        """Reap the worker on every context-manager exit."""

        self.close()

    def _cleanup(self, *, force: bool = True) -> int | None:
        """Normalize operational cleanup failures into fatal, poisoned state."""

        try:
            pid = self.worker_pid
        except Exception:
            pid = self._last_execution.worker_pid if self._last_execution is not None else None
        try:
            return self._reap_worker(force=force)
        except WorkerCleanupError:
            self._closed = True
            raise
        except Exception as exc:
            self._closed = True
            raise WorkerCleanupError(
                f"Frame worker cleanup failed: {type(exc).__name__}: {exc}",
                worker_pid=pid, stage="cleanup",
            ) from exc
        except BaseException:
            self._closed = True
            raise

    def _reap_worker(self, *, force: bool = True) -> int | None:
        process = self._process
        connection = self._connection
        receiver = self._receiver
        if process is None:
            return None
        # A control exception after Process.close() can leave a retained Python
        # wrapper for an already reaped child. Do not query its closed handle.
        handle_closed = bool(getattr(process, "_closed", False))
        pid = None if handle_closed else process.pid
        grace = self.termination_grace_seconds
        if pid is None:
            # A failed or interrupted spawn has no child to join. In particular,
            # Process.join() would mask KeyboardInterrupt with AssertionError.
            if connection is not None:
                connection.close()
            if receiver is not None and receiver.ident is not None:
                receiver.join(grace)
                if receiver.is_alive():
                    raise WorkerCleanupError("Frame receiver could not be joined after worker termination.", stage="cleanup")
            process.close()
            self._process = None
            self._connection = None
            self._receiver = None
            self._messages = None
            return None
        if not force and process.is_alive() and connection is not None:
            try:
                connection.send({"kind": "shutdown"})
            except (OSError, EOFError, BrokenPipeError):
                pass
            process.join(grace)
        if process.is_alive():
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            process.join(grace)
        if process.is_alive():
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.join(grace)
        if process.is_alive():
            self._closed = True
            raise WorkerCleanupError("Frame worker could not be reaped after terminate and kill.", worker_pid=pid, stage="cleanup")
        process.join(0)
        exit_code = process.exitcode
        if connection is not None:
            connection.close()
        if receiver is not None and receiver.ident is not None:
            receiver.join(grace)
            if receiver.is_alive():
                self._closed = True
                raise WorkerCleanupError("Frame receiver could not be joined after worker termination.", worker_pid=pid, exit_code=exit_code, stage="cleanup")
        process.close()
        self._process = None
        self._connection = None
        self._receiver = None
        self._messages = None
        return exit_code

    def close(self) -> None:
        """Close pipes, join the receiver and reap the child; repeated calls are safe."""

        self._closed = True
        self._cleanup(force=self._inflight)

    def _event(self, wait: float) -> tuple[str, Any] | None:
        assert self._messages is not None
        try:
            return self._messages.get(timeout=max(0.0, min(_POLL_SECONDS, wait)))
        except queue.Empty:
            return None

    def _start(self, cancellation_callback: Callable[[], bool] | None) -> None:
        if self._process is not None:
            if self._process.is_alive():
                return
            self._cleanup()
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=self._target, args=(child, self.spec), daemon=True)
        self._process = process
        # Windows PipeConnection and POSIX Connection expose the same endpoint
        # API, despite being separate concrete classes in the typing stubs.
        self._connection = cast(Connection, parent)
        self._messages = queue.Queue()
        started = time.monotonic()
        try:
            process.start()
        except BaseException:
            child.close()
            self._cleanup()
            raise
        child.close()
        self._receiver = threading.Thread(
            target=_receiver_main, args=(parent, self._messages),
            daemon=True, name=f"AOVGuard receiver {process.pid}",
        )
        self._receiver.start()
        deadline = started + self.startup_timeout_seconds
        while True:
            if cancellation_callback is not None and cancellation_callback():
                from aovguard.core.analysis import AnalysisCancelled

                raise AnalysisCancelled("Analysis cancelled during frame-worker startup.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FrameTimeoutError(
                    "Frame worker startup exceeded its separate deadline.", worker_pid=process.pid,
                    elapsed_seconds=time.monotonic() - started,
                    timeout_seconds=self.startup_timeout_seconds, stage="startup",
                )
            event = self._event(remaining)
            if event is None:
                if not process.is_alive():
                    raise FrameWorkerCrashed("Frame worker exited before its ready handshake.", worker_pid=process.pid, elapsed_seconds=time.monotonic() - started, exit_code=process.exitcode, stage="startup")
                continue
            kind, message = event
            if kind != "message":
                raise FrameWorkerCrashed(f"Frame worker startup transport failed: {message}", worker_pid=process.pid, elapsed_seconds=time.monotonic() - started, exit_code=process.exitcode, stage="startup")
            if isinstance(message, dict) and message.get("kind") == "startup_error":
                raise FrameWorkerProtocolError(str(message.get("message", "Worker startup failed.")), worker_pid=process.pid, elapsed_seconds=time.monotonic() - started, stage="startup")
            if (
                not isinstance(message, dict) or message.get("kind") != "ready"
                or message.get("protocol") != PROCESS_PROTOCOL_VERSION
                or message.get("pid") != process.pid
            ):
                raise FrameWorkerProtocolError("Invalid frame-worker ready handshake.", worker_pid=process.pid, elapsed_seconds=time.monotonic() - started, stage="startup")
            return

    def measure_frame(
        self,
        path: Path,
        weights: LuminanceWeights,
        threshold: float,
        max_memory_mb: float | None = None,
        timeout_seconds: float | None = None,
        cancellation_callback: Callable[[], bool] | None = None,
    ) -> FrameMeasurement:
        """Read and reduce one frame with independent startup and request deadlines."""

        from aovguard.core.analysis import AnalysisCancelled

        if self._closed:
            raise RuntimeError("Frame process executor is closed.")
        if self._inflight:
            raise RuntimeError("Frame process executor accepts only one request at a time.")
        if timeout_seconds is not None:
            timeout_seconds = _positive_seconds(timeout_seconds, "Frame timeout")
        if max_memory_mb is not None:
            max_memory_mb = validate_memory_budget(max_memory_mb)
        self._inflight = True
        self._request_id += 1
        request_id = self._request_id
        overall_started = started = time.monotonic()
        self._last_inspection = None
        self._last_estimate = None
        inspection: FileInspection | None = None
        estimate: MemoryEstimate | None = None
        stage = "startup"
        pid: int | None = None
        status = "read_error"
        exit_code: int | None = None
        try:
            if cancellation_callback is not None and cancellation_callback():
                raise AnalysisCancelled("Analysis cancelled before frame-worker startup.")
            self._start(cancellation_callback)
            started = time.monotonic()
            stage = "measurement"
            pid = self.worker_pid
            assert self._connection is not None and self._process is not None
            deadline = None if timeout_seconds is None else started + timeout_seconds
            self._connection.send({
                "kind": "measure", "id": request_id, "path": str(Path(path)),
                "weights": (weights.r, weights.g, weights.b), "threshold": threshold,
                "max_memory_mb": max_memory_mb,
            })
            while True:
                if cancellation_callback is not None and cancellation_callback():
                    raise AnalysisCancelled("Analysis cancelled during isolated frame execution.")
                remaining = _POLL_SECONDS if deadline is None else deadline - time.monotonic()
                if remaining <= 0:
                    raise FrameTimeoutError(
                        f"Frame measurement exceeded its {timeout_seconds:g}-second deadline.",
                        inspection=inspection, estimate=estimate, worker_pid=pid,
                        elapsed_seconds=time.monotonic() - overall_started,
                        timeout_seconds=timeout_seconds, stage=stage,
                    )
                event = self._event(remaining)
                if event is None:
                    if not self._process.is_alive():
                        raise FrameWorkerCrashed("Frame worker exited before returning its measurement.", inspection=inspection, estimate=estimate, worker_pid=pid, elapsed_seconds=time.monotonic() - started, timeout_seconds=timeout_seconds, exit_code=self._process.exitcode, stage=stage)
                    continue
                transport_kind, message = event
                if transport_kind != "message":
                    error_type = FrameWorkerCrashed if transport_kind == "transport_closed" else FrameWorkerProtocolError
                    raise error_type(f"Frame worker transport failed: {message}", inspection=inspection, estimate=estimate, worker_pid=pid, elapsed_seconds=time.monotonic() - started, timeout_seconds=timeout_seconds, exit_code=self._process.exitcode, stage=stage)
                if not isinstance(message, dict) or message.get("id") != request_id:
                    raise FrameWorkerProtocolError("Frame worker returned malformed data or a stale request ID.", inspection=inspection, estimate=estimate, worker_pid=pid, elapsed_seconds=time.monotonic() - started, timeout_seconds=timeout_seconds, stage=stage)
                kind = message.get("kind")
                if kind == "header":
                    candidate, candidate_estimate = message.get("inspection"), message.get("estimate")
                    if not isinstance(candidate, FileInspection) or candidate.path != Path(path) or not _scalar_tree(candidate) or (
                        candidate_estimate is not None and not isinstance(candidate_estimate, MemoryEstimate)
                    ):
                        raise FrameWorkerProtocolError("Invalid worker header metadata.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                    inspection, estimate = candidate, candidate_estimate
                    self._last_inspection, self._last_estimate = inspection, estimate
                elif kind == "stage":
                    if message.get("stage") != "reduction":
                        raise FrameWorkerProtocolError("Invalid worker execution stage.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                elif kind == "result":
                    try:
                        result = _validate_result(message.get("result"))
                    except ValueError as exc:
                        raise FrameWorkerProtocolError(str(exc), inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage) from exc
                    if cancellation_callback is not None and cancellation_callback():
                        raise AnalysisCancelled("Analysis cancelled while receiving frame results.")
                    if deadline is not None and time.monotonic() >= deadline:
                        raise FrameTimeoutError(
                            f"Frame measurement exceeded its {timeout_seconds:g}-second deadline.",
                            inspection=inspection, estimate=estimate, worker_pid=pid,
                            elapsed_seconds=time.monotonic() - overall_started,
                            timeout_seconds=timeout_seconds, stage=stage,
                        )
                    expected_status = "unsupported_structure" if result[0].unsupported_reason else "completed"
                    if message.get("status") != expected_status:
                        raise FrameWorkerProtocolError("Worker status disagrees with its measurement.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                    if result[0].path != Path(path):
                        raise FrameWorkerProtocolError("Worker measurement belongs to another frame.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                    status = expected_status
                    self._last_inspection = result[0]
                    self._last_estimate = result[3]
                    return result
                elif kind == "error":
                    if message.get("error") == "memory_rejected":
                        candidate, candidate_estimate = message.get("inspection"), message.get("estimate")
                        if not isinstance(candidate, FileInspection) or not isinstance(candidate_estimate, MemoryEstimate) or not _scalar_tree((candidate, candidate_estimate)):
                            raise FrameWorkerProtocolError("Invalid worker memory-rejection evidence.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                        budget = validate_memory_budget(cast(float, message.get("max_memory_mb")))
                        status = "memory_rejected"
                        self._last_inspection, self._last_estimate = candidate, candidate_estimate
                        raise MemoryBudgetExceeded(candidate, candidate_estimate, budget)
                    if message.get("error") != "read_error" or not isinstance(message.get("message"), str):
                        raise FrameWorkerProtocolError("Invalid worker error envelope.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
                    status = "read_error"
                    raise FrameReadError(
                        message["message"], inspection=inspection, estimate=estimate,
                        worker_pid=pid, elapsed_seconds=time.monotonic() - overall_started,
                        timeout_seconds=timeout_seconds, stage=stage,
                    )
                else:
                    raise FrameWorkerProtocolError("Unexpected worker message kind.", inspection=inspection, estimate=estimate, worker_pid=pid, stage=stage)
        except AnalysisCancelled:
            status = "cancelled"
            pid = pid or self.worker_pid
            exit_code = self._cleanup()
            raise
        except (MemoryBudgetExceeded, FrameReadError):
            raise
        except FrameExecutionError as exc:
            status = "timeout" if isinstance(exc, FrameTimeoutError) else "crash" if isinstance(exc, FrameWorkerCrashed) else "protocol_error"
            pid = exc.worker_pid or self.worker_pid
            stage = exc.stage
            exit_code = self._cleanup()
            exc.exit_code = exit_code
            if exc.elapsed_seconds == 0:
                exc.elapsed_seconds = time.monotonic() - overall_started
            raise
        except (BrokenPipeError, EOFError, OSError) as exc:
            status = "crash"
            pid = pid or self.worker_pid
            exit_code = self._cleanup()
            raise FrameWorkerCrashed(str(exc), inspection=inspection, estimate=estimate, worker_pid=pid, elapsed_seconds=time.monotonic() - overall_started, timeout_seconds=timeout_seconds, exit_code=exit_code, stage=stage) from exc
        except Exception as exc:
            status = "protocol_error"
            pid = pid or self.worker_pid
            exit_code = self._cleanup()
            raise FrameWorkerProtocolError(str(exc), inspection=inspection, estimate=estimate, worker_pid=pid, elapsed_seconds=time.monotonic() - overall_started, timeout_seconds=timeout_seconds, exit_code=exit_code, stage=stage) from exc
        except BaseException:
            # Ctrl+C/SystemExit must be preserved after forcefully reaping the
            # child, including interruptions while startup is still underway.
            status = "cancelled"
            pid = pid or self.worker_pid
            exit_code = self._cleanup()
            raise
        finally:
            self._last_execution = FrameExecutionRecord(
                mode="isolated", status=status, worker_pid=pid,
                elapsed_seconds=time.monotonic() - overall_started, timeout_seconds=timeout_seconds,
                exit_code=exit_code, stage=stage,
            )
            self._inflight = False
