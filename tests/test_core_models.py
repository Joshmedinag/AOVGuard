from pathlib import Path
from types import MappingProxyType

import numpy as np
import pytest

from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    Finding,
    FrameData,
    MetricSet,
    SeriesMetricSet,
    Severity,
    SourceKind,
    SourceMode,
)


def test_file_inspection_reports_unsupported_deep_exr() -> None:
    inspection = FileInspection(
        path=Path("deep.exr"),
        width=16,
        height=16,
        channels=("R", "G", "B"),
        aovs=(),
        is_deep=True,
    )

    assert inspection.unsupported_reason == "Deep EXR data is not supported by the MVP backend."


def test_file_inspection_reports_unsupported_multipart_exr() -> None:
    inspection = FileInspection(
        path=Path("multi.exr"),
        width=16,
        height=16,
        channels=("R", "G", "B"),
        aovs=(),
        part_count=2,
    )

    assert "Multipart EXR" in inspection.unsupported_reason


def test_frame_data_freezes_aov_mapping() -> None:
    inspection = FileInspection(
        path=Path("frame.exr"),
        width=1,
        height=1,
        channels=("R", "G", "B"),
        aovs=(),
    )
    frame = FrameData(
        path=Path("frame.exr"),
        width=1,
        height=1,
        inspection=inspection,
        aovs={"beauty": np.zeros((1, 1, 3), dtype=np.float32)},
    )

    assert isinstance(frame.aovs, MappingProxyType)
    assert tuple(frame.aovs) == ("beauty",)


def test_finding_freezes_metrics_mapping() -> None:
    finding = Finding(
        rule_id="nan_inf",
        severity=Severity.ERROR,
        message="Non-finite values",
        metrics={"nan_count": 1},
        affected_files=("frame.exr",),
    )

    assert isinstance(finding.metrics, MappingProxyType)
    assert finding.metrics["nan_count"] == 1
    assert finding.affected_files == (Path("frame.exr"),)


def test_analysis_report_frame_count_and_frozen_metrics() -> None:
    report = AnalysisReport(
        source=Path("renders"),
        frames=(Path("renders/shot.1001.exr"),),
        inspections=(),
        metrics_by_aov={
            "beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=10),
        },
        channel_metrics_by_aov={
            "beauty": {
                "R": ChannelMetricSet(10, 0.5, 0.0, 1.0),
            },
            "Z": {
                "Z": ChannelMetricSet(10, 4.0, 1.0, 8.0),
            },
        },
        frame_metrics={
            Path("renders/shot.1001.exr"): {
                "beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=10),
            }
        },
        source_kind="comparison_set",
        series_metrics_by_aov={
            "beauty": SeriesMetricSet(1, 0.5, 0.0, 0.5, 0.5, 0.0),
        },
    )

    assert report.frame_count == 1
    assert isinstance(report.metrics_by_aov, MappingProxyType)
    assert isinstance(report.channel_metrics_by_aov, MappingProxyType)
    assert isinstance(report.channel_metrics_by_aov["beauty"], MappingProxyType)
    assert isinstance(report.frame_metrics, MappingProxyType)
    assert isinstance(report.frame_metrics[Path("renders/shot.1001.exr")], MappingProxyType)
    assert report.source_kind is SourceKind.COMPARISON_SET
    assert isinstance(report.series_metrics_by_aov, MappingProxyType)
    assert report.technical_aov_count == 1
    assert report.analyzed_aov_count == 2


def test_channel_metric_properties() -> None:
    constant = ChannelMetricSet(4, 0.5, 0.5, 0.5)
    invalid = ChannelMetricSet(4, 0.0, 0.0, 0.0, nan_count=1)

    assert constant.is_constant
    assert not constant.has_non_finite
    assert invalid.has_non_finite
    assert not invalid.is_constant


def test_aov_descriptor_defaults_to_unknown_category() -> None:
    descriptor = AOVDescriptor(name="custom", channels=("custom.X",))

    assert descriptor.category is AOVCategory.UNKNOWN
    assert descriptor.category_confidence == "unknown"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"frame_pattern": ""}, "must not be empty"),
        ({"frame_pattern": "renders/*.exr"}, "filename pattern"),
        ({"max_depth": -1}, "non-negative"),
    ],
)
def test_analysis_options_validate_discovery_settings(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AnalysisOptions(**kwargs)


def test_analysis_options_accepts_string_source_mode() -> None:
    options = AnalysisOptions(source_mode="sequence")

    assert options.source_mode is SourceMode.SEQUENCE

    with pytest.raises(ValueError):
        AnalysisOptions(source_mode="invalid")
