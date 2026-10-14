"""Memory admission checks must run before pixels and retain exact frame evidence."""

from dataclasses import replace
from pathlib import Path
from typing import Collection

import numpy as np
import OpenEXR
import pytest

from aovguard.core.analysis import AnalysisCancelled, analyze
from aovguard.core.memory import MemoryBudgetExceeded, enforce_memory_budget, estimate_frame_memory
from aovguard.core.models import AnalysisOptions, FileInspection, FrameData
from aovguard.io.inspector import build_file_inspection
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.json_report import build_analysis_report_payload


def _header(path: Path, size: int = 1) -> FileInspection:
    return build_file_inspection(path=path, width=size, height=size, channels=("R", "G", "B"))


class HeaderReader:
    def __init__(self, inspections: dict[Path, FileInspection]) -> None:
        self.inspections = inspections
        self.inspected: list[Path] = []
        self.decoded: list[Path] = []

    def inspect(self, path: Path) -> FileInspection:
        self.inspected.append(path)
        return self.inspections[path]

    def read_frame(self, path: Path, requested_aovs: Collection[str] | None = None) -> FrameData:
        self.decoded.append(path)
        inspection = self.inspections[path]
        assert inspection.width == 1  # A large mocked frame must never allocate pixels.
        return FrameData(path, 1, 1, inspection, {"beauty": np.ones((1, 1, 3), np.float32)})


@pytest.mark.parametrize("budget", [0, -1, float("nan"), float("inf"), True, "1024", 10**400])
def test_memory_options_reject_invalid_budgets(budget: object) -> None:
    with pytest.raises(ValueError, match="Memory budget"):
        AnalysisOptions(max_memory_mb=budget)


def test_memory_options_accept_positive_fractional_mib_and_unlimited() -> None:
    assert AnalysisOptions().max_memory_mb is None
    assert AnalysisOptions(max_memory_mb=80.5).max_memory_mb == 80.5
    assert AnalysisOptions(max_memory_mb=1024).max_memory_mb == 1024.0


def test_oversized_frame_is_not_decoded_and_next_frame_is_processed(tmp_path: Path) -> None:
    large, small = (tmp_path / name for name in ("shot.0001.exr", "shot.0002.exr"))
    large.touch()
    small.touch()
    reader = HeaderReader({large: _header(large, 4096), small: _header(small)})
    progress: list[tuple[int, int, str]] = []
    report = analyze(
        tmp_path, AnalysisOptions(max_memory_mb=100), reader,
        progress_callback=lambda *event: progress.append(event),
    )
    assert reader.inspected == [large, small]
    assert reader.decoded == [small]
    assert report.failed_frames == (large,)
    assert report.successful_frames == (small,)
    assert report.metrics_by_aov["beauty"].pixel_count == 1
    finding = next(f for f in report.findings if f.rule_id == "memory_budget")
    assert finding.file == large and finding.affected_files == (large,)
    assert finding.metrics["max_memory_mb"] == 100
    assert finding.metrics["estimated_mib"] > 100
    assert set(report.memory_estimates) == {large, small}
    assert progress[-1][0:2] == (2, 2)
    with pytest.raises(TypeError):
        report.memory_estimates[small] = report.memory_estimates[large]
    payload = build_analysis_report_payload(report, options=AnalysisOptions(max_memory_mb=100))
    assert payload["metadata"]["status"] == "fail"
    assert payload["metadata"]["options"]["max_memory_mb"] == 100


def test_unlimited_mode_preserves_existing_reader_calls(tmp_path: Path) -> None:
    path = tmp_path / "small.exr"
    path.touch()
    reader = HeaderReader({path: _header(path)})
    report = analyze(path, AnalysisOptions(), reader)
    assert reader.inspected == []
    assert reader.decoded == [path]
    assert not report.memory_estimates


def test_header_failure_does_not_fall_back_to_pixel_decoding(tmp_path: Path) -> None:
    path = tmp_path / "bad.exr"
    path.touch()
    reader = HeaderReader({})
    report = analyze(path, AnalysisOptions(max_memory_mb=100), reader)
    assert not reader.decoded
    assert report.failed_frames == (path,)
    assert report.findings[0].rule_id == "read_frame"


def test_cancellation_after_header_prevents_pixel_decoding(tmp_path: Path) -> None:
    path = tmp_path / "small.exr"
    path.touch()
    reader = HeaderReader({path: _header(path)})
    with pytest.raises(AnalysisCancelled):
        analyze(
            path, AnalysisOptions(max_memory_mb=100), reader,
            cancellation_callback=lambda: bool(reader.inspected),
        )
    assert not reader.decoded


def test_native_reader_rejection_only_opens_headers(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "real.exr"
    OpenEXR.File({}, {name: np.ones((2, 3), np.float32) for name in ("R", "G", "B")}).write(str(path))
    native_file = OpenEXR.File
    calls: list[bool] = []

    def track_file(*args, **kwargs):
        header_only = kwargs.get("header_only", False)
        calls.append(header_only)
        assert header_only  # Never open the native decoder with this tiny budget.
        return native_file(*args, **kwargs)

    monkeypatch.setattr(OpenEXR, "File", track_file)
    reader = OpenEXRReader()
    with pytest.raises(MemoryBudgetExceeded):
        reader.read_frame_with_memory_budget(path, 1)
    report = analyze(path, AnalysisOptions(max_memory_mb=1), reader)
    assert report.failed_frames == (path,)
    assert calls == [True, True]
    assert report.memory_estimates[path].channel_count == 3


def test_native_guard_acceptance_and_unlimited_have_equivalent_metrics(tmp_path: Path) -> None:
    path = tmp_path / "real.exr"
    OpenEXR.File({}, {name: np.full((2, 3), value, np.float32) for name, value in (("R", 1), ("G", 2), ("B", 3))}).write(str(path))
    reader = OpenEXRReader()
    unlimited = analyze(path, AnalysisOptions(), reader)
    accepted = analyze(path, AnalysisOptions(max_memory_mb=100), reader)
    assert accepted.metrics_by_aov == unlimited.metrics_by_aov
    assert accepted.channel_metrics_by_aov == unlimited.channel_metrics_by_aov
    assert accepted.frame_metrics == unlimited.frame_metrics
    assert accepted.memory_estimates[path] == estimate_frame_memory(accepted.inspections[0])


def test_guarded_deep_frame_remains_explicitly_unsupported(tmp_path: Path) -> None:
    path = tmp_path / "deep.exr"
    path.touch()
    base = _header(path)
    reader = HeaderReader({path: replace(base, is_deep=True)})
    report = analyze(path, AnalysisOptions(max_memory_mb=100), reader)
    assert report.failed_frames == (path,)
    assert report.findings[0].rule_id == "unsupported_structure"
    assert not report.memory_estimates and not reader.decoded


def test_all_budget_rejections_are_failure_not_an_empty_pass(tmp_path: Path) -> None:
    paths = (tmp_path / "shot.0001.exr", tmp_path / "shot.0002.exr")
    for path in paths:
        path.touch()
    reader = HeaderReader({path: _header(path, 4096) for path in paths})
    report = analyze(tmp_path, AnalysisOptions(max_memory_mb=100), reader)
    payload = build_analysis_report_payload(report)
    assert report.frame_count == 0 and report.failed_frame_count == 2
    assert report.metrics_by_aov == {} and not reader.decoded
    assert payload["metadata"]["status"] == "fail"
    assert {finding.file for finding in report.findings if finding.rule_id == "memory_budget"} == set(paths)


def test_optional_native_style_hook_owns_its_preflight(tmp_path: Path) -> None:
    path = tmp_path / "large.exr"
    path.touch()

    class BudgetReader(HeaderReader):
        def read_frame_with_memory_budget(self, source: Path, max_memory_mb: float) -> FrameData:
            inspection = self.inspect(source)
            enforce_memory_budget(inspection, max_memory_mb)
            return self.read_frame(source)

    reader = BudgetReader({path: _header(path, 4096)})
    report = analyze(path, AnalysisOptions(max_memory_mb=100), reader)
    assert reader.inspected == [path]  # The core must not add a stale duplicate inspection.
    assert not reader.decoded
    assert report.findings[0].rule_id == "memory_budget"


def test_incomplete_multipart_metadata_fails_closed_before_read(tmp_path: Path) -> None:
    path = tmp_path / "multipart.exr"
    path.touch()
    reader = HeaderReader({path: replace(_header(path), part_count=2)})
    report = analyze(path, AnalysisOptions(max_memory_mb=100), reader)
    assert not reader.decoded
    assert report.failed_frames == (path,)
    assert "requires every part" in report.findings[0].message
