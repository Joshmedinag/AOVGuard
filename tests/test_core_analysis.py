from pathlib import Path
from typing import Collection

import numpy as np
import pytest

from aovguard.core.analysis import AnalysisCancelled, _ChannelMetricAccumulator, analyze
from aovguard.core.models import (
    AnalysisOptions,
    AOVCategory,
    AOVDescriptor,
    FileInspection,
    FrameData,
    Severity,
    SourceKind,
    SourceMode,
)


class FakeReader:
    def __init__(
        self,
        inspections: dict[Path, FileInspection],
        frames: dict[Path, FrameData],
    ) -> None:
        self.inspections = inspections
        self.frames = frames
        self.inspected: list[Path] = []
        self.read: list[Path] = []

    def inspect(self, path: Path) -> FileInspection:
        self.inspected.append(path)
        return self.inspections[path]

    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        self.read.append(path)
        return self.frames[path]


class FailingReadReader(FakeReader):
    def read_frame(
        self,
        path: Path,
        requested_aovs: Collection[str] | None = None,
    ) -> FrameData:
        self.read.append(path)
        raise RuntimeError("decode failed")


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


def _inspection(path: Path, *, is_deep: bool = False, part_count: int = 1) -> FileInspection:
    return FileInspection(
        path=path,
        width=1,
        height=1,
        channels=("beauty.R", "beauty.G", "beauty.B"),
        aovs=(
            AOVDescriptor(
                name="beauty",
                channels=("beauty.R", "beauty.G", "beauty.B"),
                category=AOVCategory.COLOR,
                category_confidence="channel_group",
            ),
        ),
        part_count=part_count,
        is_deep=is_deep,
    )


def test_analyze_aggregates_metrics_from_fake_reader(tmp_path: Path) -> None:
    frame_a = tmp_path / "shot.1001.exr"
    frame_b = tmp_path / "shot.1002.exr"
    _touch(frame_a)
    _touch(frame_b)
    reader = FakeReader(
        inspections={
            frame_a: _inspection(frame_a),
            frame_b: _inspection(frame_b),
        },
        frames={
            frame_a: FrameData(
                path=frame_a,
                width=1,
                height=1,
                inspection=_inspection(frame_a),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            ),
            frame_b: FrameData(
                path=frame_b,
                width=1,
                height=1,
                inspection=_inspection(frame_b),
                aovs={"beauty": np.zeros((1, 1, 3), dtype=np.float32)},
            ),
        },
    )

    progress: list[tuple[int, int, str]] = []
    report = analyze(
        tmp_path,
        AnalysisOptions(),
        reader,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert report.frames == (frame_a, frame_b)
    assert reader.inspected == []
    assert reader.read == [frame_a, frame_b]
    metrics = report.metrics_by_aov["beauty"]
    assert metrics.pixel_count == 2
    assert metrics.non_black_ratio == 0.5
    assert metrics.avg_luminance == 0.5
    assert metrics.max_luminance == 1.0
    assert report.frame_metrics[frame_a]["beauty"].avg_luminance == 1.0
    assert report.frame_metrics[frame_b]["beauty"].avg_luminance == 0.0
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "empty_aov"
    assert report.findings[0].affected_files == (frame_b,)
    assert report.source_kind is SourceKind.NUMBERED_SEQUENCE
    assert report.series_metrics_by_aov["beauty"].median_luminance == 0.5
    assert report.rules_executed == (
        "unknown_aov",
        "nan_inf",
        "empty_aov",
        "near_empty_aov",
        "resolution_mismatch",
        "aov_structure_mismatch",
    )
    assert progress == [
        (1, 2, "Processed shot.1001.exr"),
        (2, 2, "Processed shot.1002.exr"),
    ]


def test_channel_accumulator_uses_float64_reduction_for_hdr_values() -> None:
    values = np.concatenate(
        (
            np.asarray([100_000_000.0], dtype=np.float32),
            np.ones(100_000, dtype=np.float32),
        )
    )
    accumulator = _ChannelMetricAccumulator()

    accumulator.update(values)
    metrics = accumulator.finalize()

    expected = (100_000_000.0 + 100_000.0) / 100_001
    assert metrics.avg_value == pytest.approx(expected, rel=0.0, abs=1e-12)


def test_channel_accumulator_preserves_float64_input_across_long_sequence() -> None:
    accumulator = _ChannelMetricAccumulator()
    for _index in range(1_000):
        accumulator.update(np.asarray([100_000_000.0, 0.125], dtype=np.float64))

    metrics = accumulator.finalize()

    assert metrics.avg_value == pytest.approx(50_000_000.0625, abs=1e-12)


def test_auto_mode_resolves_standalone_files_as_comparison_set(tmp_path: Path) -> None:
    frames = (tmp_path / "beauty.exr", tmp_path / "beauty_no_light.exr")
    for frame in frames:
        _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame) for frame in frames},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )
            for frame in frames
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert report.source_kind is SourceKind.COMPARISON_SET
    assert report.warnings == ()
    assert all(finding.rule_id != "sequence_gap" for finding in report.findings)


def test_comparison_mode_suppresses_sequence_findings(tmp_path: Path) -> None:
    frames = (tmp_path / "shot.1001.exr", tmp_path / "shot.1003.exr")
    for frame in frames:
        _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame) for frame in frames},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )
            for frame in frames
        },
    )

    report = analyze(
        tmp_path,
        AnalysisOptions(source_mode=SourceMode.COMPARISON),
        reader,
    )

    assert report.source_kind is SourceKind.COMPARISON_SET
    assert all(finding.rule_id != "sequence_gap" for finding in report.findings)


def test_sequence_mode_rejects_unnumbered_files(tmp_path: Path) -> None:
    frame = tmp_path / "beauty.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame)},
        frames={},
    )

    with pytest.raises(ValueError, match="requires at least one numbered"):
        analyze(
            tmp_path,
            AnalysisOptions(source_mode=SourceMode.SEQUENCE),
            reader,
        )


def test_series_metrics_use_median_mad_and_detect_outlier(tmp_path: Path) -> None:
    values = (1.0, 1.0, 1.0, 10.0)
    frames = tuple(tmp_path / f"shot.{1001 + index}.exr" for index in range(4))
    for frame in frames:
        _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame) for frame in frames},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.full((1, 1, 3), value, dtype=np.float32)},
            )
            for frame, value in zip(frames, values)
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)
    series = report.series_metrics_by_aov["beauty"]

    assert series.median_luminance == pytest.approx(1.0)
    assert series.mad_luminance == pytest.approx(0.0)
    assert series.max_frame_delta == pytest.approx(9.0)
    assert series.outlier_frames == (frames[-1],)


def test_analyze_reports_non_finite_values(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1001.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame)},
        frames={
            frame: FrameData(
                path=frame,
                width=3,
                height=1,
                inspection=_inspection(frame),
                aovs={
                    "beauty": np.array([[np.nan, np.inf, -np.inf]], dtype=np.float32),
                },
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    metrics = report.metrics_by_aov["beauty"]
    assert metrics.has_non_finite
    assert metrics.nan_count == 1
    assert metrics.posinf_count == 1
    assert metrics.neginf_count == 1
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "nan_inf"
    assert report.findings[0].severity is Severity.ERROR


def test_analyze_collects_per_channel_metrics(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1001.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame)},
        frames={
            frame: FrameData(
                path=frame,
                width=2,
                height=1,
                inspection=_inspection(frame),
                aovs={
                    "beauty": np.array(
                        [[[1.0, -1.0, np.nan], [1.0, 2.0, np.inf]]],
                        dtype=np.float32,
                    )
                },
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    channels = report.channel_metrics_by_aov["beauty"]
    assert channels["beauty.R"].is_constant
    assert channels["beauty.G"].negative_count == 1
    assert channels["beauty.B"].nan_count == 1
    assert channels["beauty.B"].posinf_count == 1


def test_analyze_diagnoses_technical_aovs_without_luminance(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1001.exr"
    _touch(frame)
    inspection = FileInspection(
        path=frame,
        width=2,
        height=1,
        channels=("Z", "N.X", "N.Y", "N.Z"),
        aovs=(
            AOVDescriptor("Z", ("Z",), AOVCategory.DEPTH, "name"),
            AOVDescriptor(
                "N",
                ("N.X", "N.Y", "N.Z"),
                AOVCategory.VECTOR,
                "xyz_channels",
            ),
        ),
    )
    reader = FakeReader(
        inspections={frame: inspection},
        frames={
            frame: FrameData(
                path=frame,
                width=2,
                height=1,
                inspection=inspection,
                aovs={
                    "Z": np.array([[2.0, np.nan]], dtype=np.float32),
                    "N": np.array(
                        [[[0.0, 1.0, -1.0], [1.0, 0.0, -2.0]]],
                        dtype=np.float32,
                    ),
                },
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert report.metrics_by_aov == {}
    assert report.frame_metrics[frame] == {}
    assert report.technical_aov_count == 2
    assert report.channel_metrics_by_aov["Z"]["Z"].nan_count == 1
    assert report.channel_metrics_by_aov["N"]["N.Z"].negative_count == 2
    assert any(finding.rule_id == "nan_inf" and finding.aov == "Z" for finding in report.findings)


def test_analyze_recursive_discovery_requires_explicit_multiple_sequence_opt_in(
    tmp_path: Path,
) -> None:
    _touch(tmp_path / "beauty" / "beauty.1001.exr")
    _touch(tmp_path / "diffuse" / "diffuse.1001.exr")
    reader = FakeReader(inspections={}, frames={})

    with pytest.raises(ValueError, match="multiple numbered EXR sequences"):
        analyze(tmp_path, AnalysisOptions(recursive=True), reader)


def test_analyze_recursive_discovery_allows_multiple_sequences_when_requested(
    tmp_path: Path,
) -> None:
    frames = (
        tmp_path / "beauty" / "beauty.1001.exr",
        tmp_path / "diffuse" / "diffuse.1001.exr",
    )
    for frame in frames:
        _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame) for frame in frames},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )
            for frame in frames
        },
    )

    report = analyze(
        tmp_path,
        AnalysisOptions(recursive=True, allow_multiple_sequences=True),
        reader,
    )

    assert report.frames == frames
    assert reader.read == list(frames)
    assert len(report.sequence_check.sequences) == 2


def test_analyze_reports_unsupported_deep_exr_without_analyzing_pixels(tmp_path: Path) -> None:
    frame = tmp_path / "deep.1001.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame, is_deep=True)},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame, is_deep=True),
                aovs={},
            )
        },
    )

    progress: list[tuple[int, int, str]] = []
    report = analyze(
        tmp_path,
        AnalysisOptions(),
        reader,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert reader.inspected == []
    assert reader.read == [frame]
    assert report.metrics_by_aov == {}
    assert report.frame_count == 0
    assert report.failed_frames == (frame,)
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "unsupported_structure"
    assert "Deep EXR" in report.findings[0].message
    assert progress == [(1, 1, "Unsupported EXR: deep.1001.exr")]


def test_analyze_includes_discovery_warnings(tmp_path: Path) -> None:
    direct = tmp_path / "shot.1001.exr"
    nested = tmp_path / "beauty" / "shot.1002.exr"
    _touch(direct)
    _touch(nested)
    reader = FakeReader(
        inspections={direct: _inspection(direct)},
        frames={
            direct: FrameData(
                path=direct,
                width=1,
                height=1,
                inspection=_inspection(direct),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert report.frames == (direct,)
    assert report.warnings == (
        "Direct EXR files were found, so one-level nested EXR files were ignored.",
    )


def test_analyze_reports_reader_errors_and_continues(tmp_path: Path) -> None:
    frame = tmp_path / "broken.1001.exr"
    _touch(frame)
    reader = FailingReadReader(inspections={}, frames={})

    progress: list[tuple[int, int, str]] = []
    report = analyze(
        tmp_path,
        AnalysisOptions(),
        reader,
        progress_callback=lambda current, total, message: progress.append(
            (current, total, message)
        ),
    )

    assert report.metrics_by_aov == {}
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "read_frame"
    assert report.frame_count == 0
    assert report.discovered_frame_count == 1
    assert report.failed_frame_count == 1
    assert progress == [(1, 1, "Read failed: broken.1001.exr")]


def test_analyze_uses_fallback_channel_names_for_backend_only_aov(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1001.exr"
    _touch(frame)
    inspection = FileInspection(
        path=frame,
        width=1,
        height=1,
        channels=(),
        aovs=(),
    )
    reader = FakeReader(
        inspections={frame: inspection},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=inspection,
                aovs={"backend_aov": np.ones((1, 1, 3), dtype=np.float32)},
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert set(report.channel_metrics_by_aov["backend_aov"]) == {
        "backend_aov.R",
        "backend_aov.G",
        "backend_aov.B",
    }


def test_analyze_reports_read_errors_and_continues(tmp_path: Path) -> None:
    frame = tmp_path / "broken.1001.exr"
    _touch(frame)
    reader = FailingReadReader(
        inspections={frame: _inspection(frame)},
        frames={},
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    assert reader.inspected == []
    assert reader.read == [frame]
    assert report.metrics_by_aov == {}
    assert len(report.findings) == 1
    assert report.findings[0].rule_id == "read_frame"
    assert "decode failed" in report.findings[0].message


def test_analyze_rejects_empty_discovery(tmp_path: Path) -> None:
    reader = FakeReader(inspections={}, frames={})

    with pytest.raises(FileNotFoundError, match="No EXR files"):
        analyze(tmp_path, AnalysisOptions(), reader)


def test_analyze_enforces_configured_frame_limit_before_reading(tmp_path: Path) -> None:
    for frame_number in range(1001, 1004):
        _touch(tmp_path / f"shot.{frame_number}.exr")
    reader = FakeReader(inspections={}, frames={})

    with pytest.raises(ValueError, match="exceeding.*max_frames"):
        analyze(tmp_path, AnalysisOptions(max_frames=2), reader)

    assert reader.read == []


def test_analysis_options_enabled_rules_are_authoritative(tmp_path: Path) -> None:
    frame = tmp_path / "black.1001.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame)},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.zeros((1, 1, 3), dtype=np.float32)},
            )
        },
    )

    report = analyze(
        tmp_path,
        AnalysisOptions(enabled_rules=("nan_inf",)),
        reader,
    )

    assert report.rules_executed == ("nan_inf",)
    assert report.findings == ()


def test_negative_color_data_is_active_signal_not_empty(tmp_path: Path) -> None:
    frame = tmp_path / "negative.1001.exr"
    _touch(frame)
    reader = FakeReader(
        inspections={frame: _inspection(frame)},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": -np.ones((1, 1, 3), dtype=np.float32)},
            )
        },
    )

    report = analyze(tmp_path, AnalysisOptions(), reader)

    metrics = report.metrics_by_aov["beauty"]
    assert metrics.non_black_ratio == 1.0
    assert metrics.avg_luminance == -1.0
    assert metrics.avg_abs_luminance == 1.0
    assert metrics.max_abs_luminance == 1.0
    assert all(finding.rule_id != "empty_aov" for finding in report.findings)


def test_analyze_cancels_cooperatively_between_frames(tmp_path: Path) -> None:
    frame_a = tmp_path / "shot.1001.exr"
    frame_b = tmp_path / "shot.1002.exr"
    _touch(frame_a)
    _touch(frame_b)
    reader = FakeReader(
        inspections={},
        frames={
            frame: FrameData(
                path=frame,
                width=1,
                height=1,
                inspection=_inspection(frame),
                aovs={"beauty": np.ones((1, 1, 3), dtype=np.float32)},
            )
            for frame in (frame_a, frame_b)
        },
    )
    callback_results = iter((False, True))

    with pytest.raises(AnalysisCancelled, match="cancelled by user"):
        analyze(
            tmp_path,
            AnalysisOptions(),
            reader,
            cancellation_callback=lambda: next(callback_results),
        )

    assert reader.read == [frame_a]
