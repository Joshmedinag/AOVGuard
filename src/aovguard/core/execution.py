"""Structured failures from isolated frame execution and worker cleanup."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aovguard.core.memory import MemoryEstimate
    from aovguard.core.models import FileInspection


class FrameExecutionError(RuntimeError):
    """Base error retaining scalar evidence from an isolated frame request."""

    def __init__(
        self,
        message: str,
        *,
        inspection: FileInspection | None = None,
        estimate: MemoryEstimate | None = None,
        worker_pid: int | None = None,
        elapsed_seconds: float = 0.0,
        timeout_seconds: float | None = None,
        exit_code: int | None = None,
        stage: str = "measurement",
    ) -> None:
        """Capture execution details separately from stable finding metrics."""

        super().__init__(message)
        self.inspection = inspection
        self.estimate = estimate
        self.worker_pid = worker_pid
        self.elapsed_seconds = elapsed_seconds
        self.timeout_seconds = timeout_seconds
        self.exit_code = exit_code
        self.stage = stage


class FrameTimeoutError(FrameExecutionError):
    """An isolated worker exceeded its startup or per-frame deadline."""


class FrameWorkerCrashed(FrameExecutionError):
    """An isolated worker exited or broke its transport before returning a frame."""


class FrameWorkerProtocolError(FrameExecutionError):
    """An isolated worker returned malformed, stale or unsupported protocol data."""


class FrameReadError(FrameExecutionError):
    """A normal remote decode failure, retaining its inspected header evidence."""


class WorkerCleanupError(FrameExecutionError):
    """A child or receiver could not be reaped within the bounded cleanup policy."""
