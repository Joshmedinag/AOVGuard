import time
from collections.abc import Callable
from functools import partial
from multiprocessing import active_children, get_context
from pathlib import Path
from threading import Event
from typing import Collection

import numpy as np
import OpenEXR
import pytest
from gui_process_helpers import stall_after_real_header
from PySide6.QtCore import QSettings, QThread
from PySide6.QtTest import QTest

from aovguard.core.execution import WorkerCleanupError
from aovguard.core.models import FrameData
from aovguard.io.inspector import build_file_inspection
from aovguard.io.process_executor import FrameProcessExecutor
from aovguard.ui import MainWindow


def _wait_until(predicate: Callable[[], bool], seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def test_close_defers_until_real_worker_thread_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    application = qt_application
    started, release = Event(), Event()
    path = tmp_path / "shot.0001.exr"
    path.touch()

    class Reader:
        def read_frame(
            self, source: Path, requested_aovs: Collection[str] | None = None,
        ) -> FrameData:
            started.set()
            if not release.wait(5):
                raise RuntimeError("Timed out waiting for test release")
            inspection = build_file_inspection(
                path=source, width=1, height=1, channels=("R", "G", "B"),
            )
            return FrameData(
                source, 1, 1, inspection, {"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )

    monkeypatch.setattr("aovguard.gui.worker.OpenEXRReader", lambda _overrides: Reader())
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.source_edit.setText(str(path))
    window.isolate_frames_checkbox.setChecked(False)
    window.show()
    try:
        window.start_analysis()
        _wait_until(started.is_set)
        window.close()
        assert window.isVisible()
        assert window._close_pending
        assert window.analysis_thread is not None and window.analysis_thread.isRunning()
        release.set()
        _wait_until(lambda: window.analysis_thread is None)
        _wait_until(lambda: not window.isVisible())
        assert window.worker is None
        assert not window.isVisible()
    finally:
        release.set()
        _wait_until(lambda: window.analysis_thread is None)
        application.processEvents()
        window.close()
        application.processEvents()


def test_restart_waits_for_previous_thread_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    settings = QSettings(str(tmp_path / "restart.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    old_thread = QThread(window)
    window.analysis_thread = old_thread
    called: list[bool] = []
    monkeypatch.setattr(window, "_source", lambda: called.append(True))
    window.start_analysis()
    assert called == []
    assert window.analysis_thread is old_thread
    window._on_thread_finished()
    assert window.analysis_thread is None
    window.start_analysis()
    assert called == [True]
    window.close()
    qt_application.processEvents()


def _write_real_frame(path: Path) -> None:
    OpenEXR.File({}, {
        channel: np.ones((1, 1), dtype=np.float32) for channel in ("R", "G", "B")
    }).write(str(path))


def _blocked_executor_factory(monkeypatch: pytest.MonkeyPatch):
    started = get_context("spawn").Event()
    executors: list[FrameProcessExecutor] = []

    def factory(spec):
        executor = FrameProcessExecutor(
            spec, worker_target=partial(stall_after_real_header, started=started),
            termination_grace_seconds=0.2,
        )
        executors.append(executor)
        return executor

    monkeypatch.setattr("aovguard.core.analysis.FrameProcessExecutor", factory)
    return started, executors


def _assert_children_reaped(executors: list[FrameProcessExecutor]) -> None:
    live_pids = {child.pid for child in active_children()}
    for executor in executors:
        assert executor.worker_pid is None
        assert executor.last_execution is not None
        assert isinstance(executor.last_execution.worker_pid, int)
        assert executor.last_execution.worker_pid not in live_pids


def test_isolated_cancel_reaps_child_before_idle_and_allows_real_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    source = tmp_path / "shot.0001.exr"
    _write_real_frame(source)
    started, executors = _blocked_executor_factory(monkeypatch)
    window = MainWindow(settings=QSettings(str(tmp_path / "cancel.ini"), QSettings.Format.IniFormat))
    window.source_edit.setText(str(source))
    window.show()
    try:
        window.start_analysis()
        _wait_until(started.is_set, seconds=10.0)
        cancelled_at = time.monotonic()
        window.cancel_analysis()
        _wait_until(lambda: window.analysis_thread is None, seconds=5.0)
        assert time.monotonic() - cancelled_at < 5.0
        assert window.worker is None
        assert window.report is None
        assert window.status_label.text() == "CANCELLED"
        assert window.analyze_btn.isEnabled()
        _assert_children_reaped(executors)
        assert executors[0].last_execution.status == "cancelled"

        monkeypatch.setattr("aovguard.core.analysis.FrameProcessExecutor", FrameProcessExecutor)
        window.start_analysis()
        _wait_until(lambda: window.report is not None and window.analysis_thread is None, seconds=10.0)
        assert window.report.frame_count == 1
        assert window.report.failed_frame_count == 0
        completed_pid = window.report.frame_execution[source].worker_pid
        assert isinstance(completed_pid, int)
        assert completed_pid not in {child.pid for child in active_children()}
        assert window.worker is None
        assert window.analyze_btn.isEnabled()
    finally:
        window.close()
        _wait_until(lambda: window.analysis_thread is None, seconds=5.0)
        qt_application.processEvents()


def test_isolated_close_stops_stalled_child_before_window_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    source = tmp_path / "shot.0001.exr"
    _write_real_frame(source)
    started, executors = _blocked_executor_factory(monkeypatch)
    window = MainWindow(settings=QSettings(str(tmp_path / "close.ini"), QSettings.Format.IniFormat))
    window.source_edit.setText(str(source))
    window.show()
    try:
        window.start_analysis()
        _wait_until(started.is_set, seconds=10.0)
        window.close()
        assert window._close_pending and window.isVisible()
        _wait_until(lambda: window.analysis_thread is None and not window.isVisible(), seconds=5.0)
        assert window.worker is None
        _assert_children_reaped(executors)
    finally:
        window.close()
        _wait_until(lambda: window.analysis_thread is None, seconds=5.0)
        qt_application.processEvents()


def test_isolated_timeout_returns_actionable_frame_and_restores_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    source = tmp_path / "shot.0001.exr"
    _write_real_frame(source)
    _started, executors = _blocked_executor_factory(monkeypatch)
    window = MainWindow(settings=QSettings(str(tmp_path / "timeout.ini"), QSettings.Format.IniFormat))
    window.source_edit.setText(str(source))
    window.frame_timeout_spin.setValue(0.1)
    window.show()
    try:
        window.start_analysis()
        _wait_until(lambda: window.report is not None and window.analysis_thread is None, seconds=10.0)
        report = window.report
        assert report.frame_count == 0 and report.failed_frame_count == 1
        finding = next(item for item in report.findings if item.rule_id == "frame_timeout")
        assert finding.file == source and finding.affected_files == (source,)
        assert finding.metrics["timeout_seconds"] == 0.1
        assert report.frame_execution[source].status == "timeout"
        assert window.worker is None
        assert window.status_label.text().startswith("FAIL")
        assert window.analyze_btn.isEnabled() and window.frame_timeout_spin.isEnabled()
        assert not window.cancel_btn.isEnabled()
        _assert_children_reaped(executors)
    finally:
        window.close()
        _wait_until(lambda: window.analysis_thread is None, seconds=5.0)
        qt_application.processEvents()


def test_cleanup_failure_blocks_new_jobs_without_hanging_the_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    source = tmp_path / "shot.0001.exr"
    _write_real_frame(source)
    failures: list[str] = []
    close_warnings: list[str] = []
    calls: list[bool] = []

    def fail_cleanup(*_args: object, **_kwargs: object) -> None:
        calls.append(True)
        raise WorkerCleanupError("Could not reap worker.", worker_pid=456789, stage="cleanup")

    monkeypatch.setattr("aovguard.gui.worker.analyze", fail_cleanup)
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: failures.append(message),
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: close_warnings.append(message),
    )
    settings = QSettings(str(tmp_path / "fatal_cleanup.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.source_edit.setText(str(source))
    clean_idle: list[bool] = []
    window.analysis_controller.idle.connect(lambda: clean_idle.append(True))
    window.show()
    try:
        window.start_analysis()
        _wait_until(lambda: window.analysis_thread is None and bool(failures))
        assert window.analysis_controller.unsafe
        assert not window.analysis_controller.has_job
        assert window.worker is None and window.report is None
        assert clean_idle == []
        assert not window.analyze_btn.isEnabled() and not window.inspect_btn.isEnabled()
        assert not window.cancel_btn.isEnabled()
        assert window.source_edit.isEnabled()
        assert window.status_label.text() == "FAIL | CLEANUP NOT CONFIRMED"
        assert "worker PID 456789" in window.analyze_btn.toolTip()
        assert "worker PID 456789" in window.inspect_btn.toolTip()
        assert "cleanup not confirmed" in window.findings_panel.empty_label.text()
        assert "worker PID 456789" in failures[0]
        assert "restart AOVGuard" in window.log_output.toPlainText()
        window.set_busy(False)
        assert not window.analyze_btn.isEnabled() and not window.inspect_btn.isEnabled()
        assert not window.analysis_controller.start(str(source))
        monkeypatch.setattr(window, "_source", lambda: pytest.fail("Unsafe jobs must not inspect input."))
        window.start_analysis()
        window.inspect_source()
        assert calls == [True]
        window.close()
        assert not window.isVisible()
        assert len(close_warnings) == 1
        assert "does not confirm" in close_warnings[0]
        assert "worker PID 456789" in close_warnings[0]
    finally:
        if window.isVisible():
            window.close()
        qt_application.processEvents()


def test_pending_close_after_cleanup_failure_warns_and_releases_only_the_qthread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, qt_application,
) -> None:
    source = tmp_path / "shot.0001.exr"
    _write_real_frame(source)
    started, release = Event(), Event()
    failures: list[str] = []
    warnings: list[str] = []

    def delayed_failure(*_args: object, **_kwargs: object) -> None:
        started.set()
        assert release.wait(5)
        raise WorkerCleanupError("Could not reap worker.", worker_pid=456789, stage="cleanup")

    monkeypatch.setattr("aovguard.gui.worker.analyze", delayed_failure)
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: failures.append(message),
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    settings = QSettings(str(tmp_path / "unsafe_close.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.source_edit.setText(str(source))
    window.show()
    try:
        window.start_analysis()
        _wait_until(started.is_set)
        window.close()
        assert window._close_pending and window.isVisible()
        release.set()
        _wait_until(lambda: window.analysis_thread is None and not window.isVisible())
        assert window.analysis_controller.unsafe
        assert window.worker is None
        assert failures == [] and len(warnings) == 1
        assert "does not confirm" in warnings[0]
        assert "worker PID 456789" in warnings[0]
        assert not window.analysis_controller.start(str(source))
    finally:
        release.set()
        _wait_until(lambda: window.analysis_thread is None)
        if window.isVisible():
            window.close()
        qt_application.processEvents()
