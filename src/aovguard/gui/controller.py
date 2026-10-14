"""Own the execution, cancellation and cleanup of one GUI analysis job."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from aovguard.gui.worker import AnalyzeWorker


class AnalysisController(QObject):
    """Coordinate a worker without exposing thread lifetime to presentation code.

    A job remains active until its thread has fully terminated and references
    have been cleared. Result delivery therefore cannot permit an overlapping
    restart or leave a running child thread behind when a window closes.
    """

    finished = Signal(object)
    error = Signal(str, str)
    cancelled = Signal()
    log = Signal(str)
    progress = Signal(int, str)
    idle = Signal()
    shutdown_ready = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        """Create an idle controller in the GUI thread."""

        super().__init__(parent)
        self.analysis_thread: QThread | None = None
        self.worker: AnalyzeWorker | None = None
        self.close_pending = False
        self._unsafe = False
        self.cleanup_failure_message = ""

    @property
    def has_job(self) -> bool:
        """Return whether a job is running or waiting for thread cleanup."""

        return self.analysis_thread is not None

    @property
    def unsafe(self) -> bool:
        """Return whether process cleanup failed and further jobs must be refused."""

        return self._unsafe

    def start(
        self,
        source: str,
        *,
        worker_arguments: Mapping[str, Any] | None = None,
        thread_factory: Callable[..., QThread] = QThread,
        worker_factory: Callable[..., AnalyzeWorker] = AnalyzeWorker,
    ) -> bool:
        """Launch one job using injectable factories; refuse overlapping starts."""

        if self.has_job or self.close_pending or self.unsafe:
            return False
        thread = thread_factory(self)
        try:
            worker = worker_factory(source, **dict(worker_arguments or {}))
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            queued = Qt.ConnectionType.QueuedConnection
            worker.finished.connect(self._receive_result, queued)
            worker.error.connect(self._receive_error, queued)
            worker.cancelled.connect(self._receive_cancelled, queued)
            worker.log.connect(self._receive_log, queued)
            worker.progress.connect(self._receive_progress, queued)
            cleanup_failed = getattr(worker, "cleanup_failed", None)
            if cleanup_failed is not None:
                cleanup_failed.connect(self._receive_cleanup_failure, queued)
            terminals = [worker.finished, worker.error, worker.cancelled]
            if cleanup_failed is not None:
                terminals.append(cleanup_failed)
            for terminal in terminals:
                terminal.connect(thread.quit)
                terminal.connect(worker.deleteLater)
            thread.finished.connect(self.finalize, queued)
            self.analysis_thread = thread
            self.worker = worker
            self.close_pending = False
            thread.start()
        except Exception:
            self.analysis_thread = None
            self.worker = None
            thread.deleteLater()
            raise
        return True

    @Slot()
    def cancel(self) -> bool:
        """Request cooperative cancellation through the worker's thread-safe event."""

        if self.worker is None:
            return False
        self.worker.request_cancel()
        return True

    def wait(self, timeout_ms: int = 0) -> bool:
        """Check thread termination, without blocking unless a timeout is supplied."""

        if timeout_ms < 0:
            raise ValueError("Thread wait timeout must be non-negative.")
        if self.analysis_thread is None:
            return True
        wait = getattr(self.analysis_thread, "wait", None)
        return bool(wait(timeout_ms)) if wait is not None else True

    def request_shutdown(self) -> bool:
        """Cancel an active job and signal readiness after non-blocking cleanup.

        Return True when the caller can close immediately. Otherwise the
        caller should defer closing until ``shutdown_ready`` is emitted.
        """

        if not self.has_job:
            return True
        self.close_pending = True
        self.cancel()
        thread = self.analysis_thread
        if thread is not None and not getattr(thread, "isRunning", lambda: False)():
            self._cleanup_thread(thread)
        return not self.has_job

    @Slot()
    def finalize(self) -> None:
        """Clean up the finished job after the underlying thread has terminated."""

        thread = self.analysis_thread
        if thread is not None:
            sender = self.sender()
            if sender is None or sender is thread:
                self._cleanup_thread(thread)

    def _cleanup_thread(self, thread: QThread) -> None:
        if thread is not self.analysis_thread:
            return
        if not self.wait(0):
            QTimer.singleShot(1, lambda: self._cleanup_thread(thread))
            return
        self.analysis_thread = None
        self.worker = None
        thread.deleteLater()
        if not self.unsafe:
            self.idle.emit()
        if self.close_pending:
            self.close_pending = False
            self.shutdown_ready.emit()

    @Slot(object)
    def _receive_result(self, payload: object) -> None:
        self.finished.emit(payload)

    @Slot(str, str)
    def _receive_error(self, message: str, details: str) -> None:
        self.error.emit(message, details)

    @Slot(str, str)
    def _receive_cleanup_failure(self, message: str, details: str) -> None:
        """Latch an unsafe process state before presenting the terminal failure."""

        self._unsafe = True
        self.cleanup_failure_message = message
        self.error.emit(message, details)

    @Slot()
    def _receive_cancelled(self) -> None:
        self.cancelled.emit()

    @Slot(str)
    def _receive_log(self, message: str) -> None:
        self.log.emit(message)

    @Slot(int, str)
    def _receive_progress(self, percent: int, message: str) -> None:
        self.progress.emit(percent, message)
