import weakref
from pathlib import Path
from typing import Collection

import numpy as np
import OpenEXR
import pytest

from aovguard.core.analysis import _series_metrics, analyze
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    ChannelMetricSet,
    FrameData,
    MetricSet,
    Severity,
)
from aovguard.io.inspector import build_file_inspection
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.html_report import build_analysis_html
from aovguard.reports.json_report import build_analysis_report_payload
from aovguard.rules.builtin import effective_rule_parameters
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules


def _write(path: Path, channels: dict[str, np.ndarray], **header: object) -> None:
    OpenEXR.File({"type": OpenEXR.scanlineimage, **header}, channels).write(str(path))


def test_alpha_nan_is_reported_on_exact_frame_without_changing_luminance(
    tmp_path: Path,
) -> None:
    files = tuple(tmp_path / f"shot.{number:04d}.exr" for number in range(1, 4))
    for index, path in enumerate(files):
        rgb = {name: np.ones((2, 2), dtype=np.float32) for name in ("R", "G", "B")}
        alpha = np.ones((2, 2), dtype=np.float32)
        if index == 1:
            alpha[0, 0] = np.nan
        _write(path, {**rgb, "A": alpha})

    options = AnalysisOptions()
    report = analyze(tmp_path, options, OpenEXRReader())
    finding = next(item for item in report.findings if item.rule_id == "nan_inf")

    assert finding.channel == "A"
    assert finding.file == files[1]
    assert finding.affected_files == (files[1],)
    assert report.frame_channel_metrics[files[1]]["beauty"]["A"].nan_count == 1
    assert report.metrics_by_aov["beauty"].avg_luminance == pytest.approx(1.0)
    assert report.metrics_by_aov["beauty"].nan_count == 0
    payload = build_analysis_report_payload(report, options=options)
    assert payload["schema_version"] == "1.2"
    assert payload["frame_channel_metrics"][str(files[1])]["beauty"]["A"]["nan_count"] == 1
    assert str(files[1]) in build_analysis_html(report, options=options)


@pytest.mark.parametrize(
    ("rule", "values", "expected", "parameters"),
    [
        ("nan_inf", [1.0, float("inf"), 1.0], [1], {}),
        ("negative_values", [-2.0, 1.0, -3.0], [0, 2], {}),
        ("extreme_values", [2.0, 10.0, 100.0], [2], {"max_absolute": 50.0}),
        ("extreme_values", [2.0, 10.0, 100.0], [1, 2], {"max_absolute": 5.0}),
    ],
)
def test_technical_findings_keep_complete_frame_evidence(
    tmp_path: Path,
    rule: str,
    values: list[float],
    expected: list[int],
    parameters: dict[str, float],
) -> None:
    files = tuple(tmp_path / f"shot.{number:04d}.exr" for number in range(1, 4))
    for path, value in zip(files, values):
        _write(path, {"technical.value": np.full((1, 1), value, dtype=np.float32)})
    definition = RuleDefinition(rule, severity=Severity.ERROR, parameters=parameters)
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader(), [definition])
    finding = next(item for item in report.findings if item.rule_id == rule)

    affected = tuple(files[index] for index in expected)
    assert finding.affected_files == affected
    assert finding.file == (affected[0] if len(affected) == 1 else None)
    assert set(finding.metrics["per_frame"]) == {str(path) for path in affected}
    assert all(str(path) in build_analysis_html(report) for path in affected)
    snapshot = build_analysis_report_payload(report)["metadata"]["effective_rules"][0]
    assert snapshot["parameters"] == parameters
    assert snapshot["severity"] == "error"


def test_resolution_rule_uses_display_window_with_variable_crop(tmp_path: Path) -> None:
    display = (np.array([0, 0], dtype=np.int32), np.array([9, 9], dtype=np.int32))
    for number, origin, size in ((1, (0, 0), 2), (2, (4, 3), 1)):
        minimum = np.array(origin, dtype=np.int32)
        maximum = minimum + size - 1
        _write(
            tmp_path / f"shot.{number:04d}.exr",
            {name: np.ones((size, size), dtype=np.float32) for name in ("R", "G", "B")},
            dataWindow=(minimum, maximum),
            displayWindow=display,
        )
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert len({(item.width, item.height) for item in report.inspections}) == 2
    assert {(item.display_width, item.display_height) for item in report.inspections} == {(10, 10)}
    assert not any(item.rule_id == "resolution_mismatch" for item in report.findings)


def test_changed_display_origin_is_detected_even_with_identical_dimensions(
    tmp_path: Path,
) -> None:
    for number, offset in ((1, 0), (2, 10)):
        _write(
            tmp_path / f"shot.{number:04d}.exr",
            {"Z": np.ones((1, 1), dtype=np.float32)},
            displayWindow=(
                np.array([offset, 0], dtype=np.int32),
                np.array([offset + 9, 9], dtype=np.int32),
            ),
        )
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())
    finding = next(item for item in report.findings if item.rule_id == "resolution_mismatch")
    assert finding.file == tmp_path / "shot.0002.exr"
    assert finding.metrics["width"] == finding.metrics["baseline_width"] == 10


def test_previous_pixel_buffers_are_released_before_next_read(tmp_path: Path) -> None:
    files = tuple(tmp_path / f"shot.{number:04d}.exr" for number in range(1, 4))
    for path in files:
        path.touch()

    class Reader:
        def __init__(self) -> None:
            self.previous: weakref.ReferenceType[np.ndarray] | None = None
            self.read_count = 0

        def read_frame(
            self, path: Path, requested_aovs: Collection[str] | None = None,
        ) -> FrameData:
            if self.previous is not None:
                assert self.previous() is None
            pixels = np.ones((1, 1, 3), dtype=np.float32)
            self.previous = weakref.ref(pixels)
            self.read_count += 1
            inspection = build_file_inspection(
                path=path, width=1, height=1, channels=("R", "G", "B"),
            )
            return FrameData(path, 1, 1, inspection, {"beauty": pixels})

    reader = Reader()
    report = analyze(tmp_path, AnalysisOptions(), reader)
    assert report.frame_count == reader.read_count == 3
    assert reader.previous is not None and reader.previous() is None


def test_luminance_reduction_is_performed_once_per_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aovguard.core.analysis as core

    for number in range(1, 4):
        _write(
            tmp_path / f"shot.{number:04d}.exr",
            {name: np.ones((1, 1), dtype=np.float32) for name in ("R", "G", "B")},
        )
    original = core.compute_luminance
    calls: list[int] = []

    def counting(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(core, "compute_luminance", counting)
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())
    assert report.frame_count == len(calls) == 3
    assert report.metrics_by_aov["beauty"].pixel_count == 3


def test_inventory_includes_aovs_discovered_after_first_frame(tmp_path: Path) -> None:
    _write(tmp_path / "shot.0001.exr", {"Z": np.ones((1, 1), dtype=np.float32)})
    _write(
        tmp_path / "shot.0002.exr",
        {"Z": np.ones((1, 1), dtype=np.float32), "custom": np.ones((1, 1), dtype=np.uint32)},
    )
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())
    payload = build_analysis_report_payload(report)
    assert payload["metadata"]["aovs_detected"] == 2
    assert payload["metadata"]["summary_by_aov_category"] == {"depth": 1, "scalar": 1}


def test_rule_snapshot_records_defaults_and_is_independent_of_mutable_preset(
    tmp_path: Path,
) -> None:
    path = tmp_path / "shot.0001.exr"
    _write(path, {"Z": np.ones((1, 1), dtype=np.float32)})
    required = ["Z"]
    report = analyze(
        path, AnalysisOptions(), OpenEXRReader(),
        [RuleDefinition("missing_aov", parameters={"required": required}),
         RuleDefinition("empty_aov")],
    )
    required.append("changed_after_analysis")
    snapshot = build_analysis_report_payload(report)["metadata"]["effective_rules"]
    assert snapshot[0]["parameters"]["required"] == ["Z"]
    assert snapshot[1]["parameters"] == {"max_luminance": 1e-5, "max_average": 1e-6}
    with pytest.raises(TypeError):
        report.effective_rules[0]["parameters"]["required"] = []


def test_duplicate_frame_number_does_not_form_temporal_edge() -> None:
    first, duplicate, second = (Path(name) for name in ("shot.0001.exr", "shot.1.exr", "shot.0002.exr"))
    samples = {
        path: {"beauty": MetricSet(1.0, value, value, 1)}
        for path, value in ((first, 1.0), (duplicate, 100.0), (second, 2.0))
    }
    stats = _series_metrics(samples, frame_numbers={first: 1, duplicate: 1, second: 2})
    assert stats["beauty"].max_frame_delta == 0.0
    assert stats["beauty"].max_frame_delta_from is None


def test_non_finite_luminance_fallback_is_not_hidden_by_another_channel_finding() -> None:
    path = Path("shot.0001.exr")
    color = MetricSet(0.0, float("nan"), float("nan"), 1, nan_count=1)
    report = AnalysisReport(
        source=Path("renders"), frames=(path,), inspections=(),
        metrics_by_aov={"beauty": color},
        frame_metrics={path: {"beauty": color}},
        channel_metrics_by_aov={"Z": {"Z": ChannelMetricSet(1, 0.0, 0.0, 0.0, nan_count=1)}},
    )
    findings = execute_rules(report, [RuleDefinition("nan_inf", severity=Severity.ERROR)])
    assert {finding.aov for finding in findings} == {"Z", "beauty"}
    color_finding = next(finding for finding in findings if finding.aov == "beauty")
    assert color_finding.file == path
    assert color_finding.affected_files == (path,)


def test_effective_parameters_normalize_numeric_strings_and_preserve_invalid_values() -> None:
    assert effective_rule_parameters(
        RuleDefinition("extreme_values", parameters={"max_absolute": "50"}),
    ) == effective_rule_parameters(
        RuleDefinition("extreme_values", parameters={"max_absolute": 50.0}),
    )
    assert effective_rule_parameters(
        RuleDefinition("extreme_values", parameters={"max_absolute": "invalid"}),
    )["max_absolute"] == "invalid"
