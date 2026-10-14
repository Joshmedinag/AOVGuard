"""Core isolation integration preserves metrics and deterministic failure evidence."""

import multiprocessing
from dataclasses import replace
from pathlib import Path

import numpy as np
import OpenEXR
import pytest

import aovguard.core.analysis as analysis_module
from aovguard import cli
from aovguard.core.analysis import AnalysisCancelled, _measure_frame, analyze
from aovguard.core.execution import (
    FrameReadError,
    FrameTimeoutError,
    FrameWorkerCrashed,
    FrameWorkerProtocolError,
    WorkerCleanupError,
)
from aovguard.core.memory import estimate_frame_memory
from aovguard.core.models import AnalysisOptions, FrameExecutionRecord
from aovguard.io.process_executor import FrameProcessExecutor
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.comparison import compare_report_payloads
from aovguard.reports.json_report import build_analysis_report_payload


def _write_frame(path: Path, value: float = 1.0) -> None:
    OpenEXR.File({}, {
        "R": np.full((2, 3), value, np.float32),
        "G": np.full((2, 3), value + 1, np.float32),
        "B": np.full((2, 3), value + 2, np.float32),
        "A": np.full((2, 3), -0.5, np.float32),
        "custom.X": np.full((2, 3), 7, np.float32),
        "id": np.full((2, 3), 4_294_967_295, np.uint32),
    }).write(str(path))


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "30", 10**400])
def test_timeout_rejects_invalid_values(timeout: object) -> None:
    with pytest.raises(ValueError, match="Frame timeout"):
        AnalysisOptions(isolate_frames=True, frame_timeout_seconds=timeout)


@pytest.mark.parametrize("isolation", [0, 1, None, "true"])
def test_isolation_requires_an_explicit_boolean(isolation: object) -> None:
    with pytest.raises(ValueError, match="Frame isolation"):
        AnalysisOptions(isolate_frames=isolation)


def test_timeout_requires_isolation_and_normalizes_numbers() -> None:
    with pytest.raises(ValueError, match="requires process isolation"):
        AnalysisOptions(frame_timeout_seconds=5)
    options = AnalysisOptions(isolate_frames=True, frame_timeout_seconds=5)
    assert options.frame_timeout_seconds == 5.0
    assert not AnalysisOptions().isolate_frames


def test_native_process_spec_snapshots_actual_reader_configuration() -> None:
    overrides = {"CuStOm": "scalar"}
    reader = OpenEXRReader(overrides)
    overrides["CuStOm"] = "color"
    assert reader.process_spec().category_overrides == (("custom", "scalar"),)

    class CustomReader(OpenEXRReader):
        pass

    with pytest.raises(ValueError, match="subclasses"):
        CustomReader().process_spec()


def test_custom_reader_without_process_spec_is_not_silently_decoded(tmp_path: Path) -> None:
    class CustomReader:
        def read_frame(self, *args):
            pytest.fail("Unsupported reader must never decode in isolated mode.")

    with pytest.raises(ValueError, match="does not support process isolation"):
        analyze(tmp_path, AnalysisOptions(isolate_frames=True), CustomReader())


def test_native_isolation_matches_in_process_and_reuses_worker(tmp_path: Path) -> None:
    for index in (1, 2):
        _write_frame(tmp_path / f"shot.{index:04d}.exr", index)
    reader = OpenEXRReader({"custom": "scalar"})
    before = {child.pid for child in multiprocessing.active_children()}
    direct_options = AnalysisOptions(max_memory_mb=100)
    isolated_options = replace(direct_options, isolate_frames=True, frame_timeout_seconds=10)
    direct = analyze(tmp_path, direct_options, reader)
    isolated = analyze(tmp_path, isolated_options, reader)
    for field in (
        "inspections", "metrics_by_aov", "channel_metrics_by_aov", "frame_metrics",
        "frame_channel_metrics", "series_metrics_by_aov", "series_metrics_by_sequence",
        "findings", "successful_frames", "failed_frames", "memory_estimates",
    ):
        assert getattr(isolated, field) == getattr(direct, field)
    records = tuple(isolated.frame_execution.values())
    assert len(records) == 2 and len({record.worker_pid for record in records}) == 1
    assert all(record.mode == "isolated" and record.status == "completed" for record in records)
    assert records[0].worker_pid not in before and records[0].worker_pid is not None
    assert {child.pid for child in multiprocessing.active_children()} == before
    assert all(record.mode == "in_process" for record in direct.frame_execution.values())
    with pytest.raises(TypeError):
        isolated.frame_execution[isolated.frames[0]] = records[0]
    comparison = compare_report_payloads(
        build_analysis_report_payload(direct, options=direct_options),
        build_analysis_report_payload(isolated, options=isolated_options),
    )
    assert not comparison.new_findings and not comparison.resolved_findings
    assert comparison.changed_aov_count == 0
    assert not comparison.warnings


def test_isolated_memory_rejection_retains_header_and_execution(tmp_path: Path) -> None:
    path = tmp_path / "shot.0001.exr"
    _write_frame(path)
    report = analyze(path, AnalysisOptions(isolate_frames=True, max_memory_mb=1), OpenEXRReader())
    assert report.failed_frames == (path,) and not report.successful_frames
    assert report.inspections[0].path == path
    assert report.memory_estimates[path].estimated_mib > 1
    assert report.frame_execution[path].status == "memory_rejected"
    assert report.findings[0].rule_id == "memory_budget"


def test_isolated_bad_frame_does_not_prevent_next_frame(tmp_path: Path) -> None:
    bad = tmp_path / "shot.0001.exr"
    bad.touch()
    good = tmp_path / "shot.0002.exr"
    _write_frame(good)
    report = analyze(tmp_path, AnalysisOptions(isolate_frames=True), OpenEXRReader())
    assert report.failed_frames == (bad,) and report.successful_frames == (good,)
    assert report.frame_execution[bad].status == "read_error"
    assert report.frame_execution[bad].worker_pid == report.frame_execution[good].worker_pid
    assert report.findings[0].affected_files == (bad,)


@pytest.mark.parametrize(
    ("error_type", "rule", "status"),
    [
        (FrameTimeoutError, "frame_timeout", "timeout"),
        (FrameWorkerCrashed, "worker_crash", "crash"),
        (FrameWorkerProtocolError, "worker_protocol", "protocol_error"),
    ],
)
def test_execution_failure_is_exact_and_following_frame_survives(
    tmp_path: Path, monkeypatch, error_type, rule: str, status: str,
) -> None:
    paths = [tmp_path / f"shot.{index:04d}.exr" for index in (1, 2)]
    for path in paths:
        _write_frame(path)
    reader = OpenEXRReader()
    header = reader.inspect(paths[0])
    estimate = estimate_frame_memory(header)
    closed: list[bool] = []

    class ControlledExecutor:
        last_execution = None

        def __init__(self, spec):
            pass

        def measure_frame(self, path, weights, threshold, budget, timeout, cancellation):
            self.last_execution = FrameExecutionRecord(
                "isolated", status if path == paths[0] else "completed", 999, 0.25, timeout,
            )
            if path == paths[0]:
                raise error_type(
                    "Controlled frame execution failure.", inspection=header, estimate=estimate,
                    worker_pid=999, elapsed_seconds=0.25, timeout_seconds=timeout, exit_code=42,
                )
            return _measure_frame(reader, path, weights, threshold, cancellation, budget)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", ControlledExecutor)
    report = analyze(tmp_path, AnalysisOptions(isolate_frames=True, frame_timeout_seconds=1), reader)
    assert closed == [True]
    assert report.failed_frames == (paths[0],) and report.successful_frames == (paths[1],)
    assert report.frame_metrics[paths[1]]["beauty"].pixel_count == 6
    finding = next(finding for finding in report.findings if finding.rule_id == rule)
    assert finding.file == paths[0] and finding.affected_files == (paths[0],)
    assert "worker_pid" not in finding.metrics and "elapsed_seconds" not in finding.metrics
    assert report.inspections[0] == header and report.memory_estimates[paths[0]] == estimate
    assert report.frame_execution[paths[0]].status == status
    assert report.series_metrics_by_aov["beauty"].max_frame_delta == 0


@pytest.mark.parametrize("failure", [AnalysisCancelled("cancel"), WorkerCleanupError("cleanup")])
def test_cancellation_or_unreaped_worker_is_fatal_and_closes(tmp_path: Path, monkeypatch, failure) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)
    closed: list[bool] = []

    class FailedExecutor:
        last_execution = None

        def __init__(self, spec):
            pass

        def measure_frame(self, *args):
            raise failure

        def close(self):
            closed.append(True)

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", FailedExecutor)
    with pytest.raises(type(failure)):
        analyze(path, AnalysisOptions(isolate_frames=True), OpenEXRReader())
    assert closed == [True]


def test_progress_callback_failure_still_closes_worker(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)
    closed: list[bool] = []

    class TrackingExecutor:
        last_execution = None

        def __init__(self, spec):
            pass

        def measure_frame(self, *args):
            pytest.fail("Progress callback fails before measurement.")

        def close(self):
            closed.append(True)

    def failing_progress(*args):
        raise LookupError("Callback failure")

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", TrackingExecutor)
    with pytest.raises(LookupError, match="Callback failure"):
        analyze(
            path, AnalysisOptions(isolate_frames=True), OpenEXRReader(),
            progress_callback=failing_progress,
        )
    assert closed == [True]


def test_cleanup_failure_does_not_return_apparently_completed_report(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)
    reader = OpenEXRReader()

    class CleanupFailureExecutor:
        last_execution = None

        def __init__(self, spec):
            pass

        def measure_frame(self, path, weights, threshold, budget, timeout, cancellation):
            return _measure_frame(reader, path, weights, threshold, cancellation, budget)

        def close(self):
            raise WorkerCleanupError("Not reaped")

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", CleanupFailureExecutor)
    with pytest.raises(WorkerCleanupError, match="Not reaped"):
        analyze(path, AnalysisOptions(isolate_frames=True), reader)


def test_direct_execution_reports_unsupported_status(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "deep.exr"
    _write_frame(path)
    header = replace(OpenEXRReader().inspect(path), is_deep=True)
    monkeypatch.setattr(analysis_module, "_measure_frame", lambda *args: (header, {}, {}, None))
    report = analyze(path, AnalysisOptions(), OpenEXRReader())
    assert report.frame_execution[path].status == "unsupported_structure"
    assert report.failed_frames == (path,)


def test_isolated_decoder_error_retains_header_without_partial_metrics(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)
    reader = OpenEXRReader()
    inspection = reader.inspect(path)
    estimate = estimate_frame_memory(inspection)
    closed: list[bool] = []

    class DecoderErrorExecutor:
        last_execution = FrameExecutionRecord("isolated", "read_error", 123, 0.1, None)

        def __init__(self, spec):
            pass

        def measure_frame(self, *args):
            raise FrameReadError("Corrupt pixel block", inspection=inspection, estimate=estimate)

        def close(self):
            closed.append(True)

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", DecoderErrorExecutor)
    report = analyze(path, AnalysisOptions(isolate_frames=True), reader)
    assert closed == [True]
    assert report.inspections == (inspection,)
    assert report.memory_estimates[path] == estimate
    assert not report.metrics_by_aov and not report.channel_metrics_by_aov
    assert not report.frame_metrics and not report.frame_channel_metrics
    assert report.findings[0].rule_id == "read_frame"


def test_timeout_without_header_still_identifies_frame(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)

    class EarlyTimeoutExecutor:
        last_execution = FrameExecutionRecord("isolated", "timeout", 123, 0.1, 0.1)

        def __init__(self, spec):
            pass

        def measure_frame(self, *args):
            raise FrameTimeoutError("Header never arrived", timeout_seconds=0.1)

        def close(self):
            pass

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", EarlyTimeoutExecutor)
    report = analyze(path, AnalysisOptions(isolate_frames=True, frame_timeout_seconds=0.1), OpenEXRReader())
    assert not report.inspections and not report.memory_estimates
    assert report.failed_frames == (path,) and report.findings[0].affected_files == (path,)


def test_cli_keyboard_interrupt_during_real_execution_reaps_child(tmp_path: Path, monkeypatch, capsys) -> None:
    path = tmp_path / "shot.exr"
    _write_frame(path)
    before = {child.pid for child in multiprocessing.active_children()}

    class InterruptedExecutor(FrameProcessExecutor):
        def measure_frame(self, path, weights, threshold, budget, timeout, cancellation):
            def interrupt_after_header():
                if self.last_inspection is not None:
                    raise KeyboardInterrupt
                return False

            return super().measure_frame(
                path, weights, threshold, budget, timeout, interrupt_after_header,
            )

    monkeypatch.setattr(analysis_module, "FrameProcessExecutor", InterruptedExecutor)
    report_path = tmp_path / "interrupted.json"
    assert cli.main(["analyze", str(path), "--json", str(report_path)]) == 130
    assert not report_path.exists()
    stderr = capsys.readouterr().err
    assert "interrupted by user" in stderr
    assert "Traceback" not in stderr and "AssertionError" not in stderr
    assert {child.pid for child in multiprocessing.active_children()} == before
