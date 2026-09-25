import csv
import json
from pathlib import Path

import pytest

from aovguard.analysis_core import (
    AOVResult,
    Thresholds,
    build_report_payload,
    make_summary,
    write_csv,
    write_json,
)
from aovguard.config import load_thresholds, merge_threshold_overrides
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    MetricSet,
    SourceMode,
)
from aovguard.reports import json_report
from aovguard.reports.json_report import build_analysis_report_payload, write_analysis_json


def test_build_report_payload_contains_metadata() -> None:
    results = [AOVResult("keyLight", "Active", 0.2, 0.1, 0.8)]
    payload = build_report_payload(
        results, mode="multilayer", thresholds=Thresholds(), frames_analyzed=3
    )

    assert payload["metadata"]["tool"] == "AOVGuard"
    assert payload["metadata"]["summary"]["Active"] == 1
    assert payload["metadata"]["frames_analyzed"] == 3
    assert payload["results"][0]["aov_name"] == "keyLight"


def test_build_report_payload_supports_all_optional_metadata(tmp_path: Path) -> None:
    results = [AOVResult("custom", "Custom Status", 0.1, 0.2, 0.3)]

    payload = build_report_payload(
        results,
        input_folder=tmp_path,
        mode="legacy",
        frames_analyzed=2,
        extra_metadata={"renderer": "Arnold"},
    )

    assert payload["metadata"]["input_folder"] == str(tmp_path)
    assert payload["metadata"]["mode"] == "legacy"
    assert payload["metadata"]["frames_analyzed"] == 2
    assert payload["metadata"]["renderer"] == "Arnold"
    assert make_summary(results)["Custom Status"] == 1


def test_write_json_creates_structured_report(tmp_path) -> None:
    path = tmp_path / "report.json"
    results = [AOVResult("practicalLamp", "Empty", 0.0, 0.0, 0.0)]
    write_json(results, path, mode="simple", thresholds=Thresholds())

    data = json.loads(path.read_text())
    assert data["metadata"]["summary"]["Empty"] == 1
    assert data["results"][0]["classification"] == "Empty"


def test_write_csv_creates_header_and_rows(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.csv"
    results = [AOVResult("key", "Active", 1.0, 0.5, 2.0)]

    write_csv(results, path)

    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    assert rows[0] == [
        "aov_name",
        "classification",
        "non_black_ratio",
        "avg_luminance",
        "max_luminance",
    ]
    assert rows[1] == ["key", "Active", "1.0", "0.5", "2.0"]


def test_load_thresholds_from_toml(tmp_path) -> None:
    path = tmp_path / "aovguard.toml"
    path.write_text("[analysis]\nreview_max_ratio = 0.12\nempty_max_luminance = 0.0002\n")

    thresholds = load_thresholds(path)

    assert thresholds.review_max_ratio == 0.12
    assert thresholds.empty_max_luminance == 0.0002


def test_load_thresholds_supports_json_and_thresholds_layout(tmp_path: Path) -> None:
    path = tmp_path / "aovguard.json"
    path.write_text(
        json.dumps({"thresholds": {"review_max_average": "0.25"}}),
        encoding="utf-8",
    )

    thresholds = load_thresholds(path)

    assert thresholds.review_max_average == 0.25


def test_load_thresholds_default_and_error_paths(tmp_path: Path) -> None:
    assert load_thresholds(None) == Thresholds()

    with pytest.raises(FileNotFoundError, match="does not exist"):
        load_thresholds(tmp_path / "missing.toml")

    unsupported = tmp_path / "config.yaml"
    unsupported.write_text("analysis: {}", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported config format"):
        load_thresholds(unsupported)

    non_object = tmp_path / "list.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="top level"):
        load_thresholds(non_object)

    invalid_thresholds = tmp_path / "invalid.json"
    invalid_thresholds.write_text('{"thresholds": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="must be a dictionary"):
        load_thresholds(invalid_thresholds)

    unknown = tmp_path / "unknown.toml"
    unknown.write_text("[analysis]\nnot_a_threshold = 1", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown threshold"):
        load_thresholds(unknown)


def test_merge_threshold_overrides() -> None:
    thresholds = merge_threshold_overrides(
        Thresholds(),
        empty_max_luminance=0.1,
        empty_max_average=0.2,
        nearly_empty_max_ratio=0.3,
        nearly_empty_max_average=0.4,
        review_max_ratio=0.5,
        review_max_average=0.6,
    )
    assert thresholds.empty_max_luminance == 0.1
    assert thresholds.empty_max_average == 0.2
    assert thresholds.nearly_empty_max_ratio == 0.3
    assert thresholds.nearly_empty_max_average == 0.4
    assert thresholds.review_max_ratio == 0.5
    assert thresholds.review_max_average == 0.6


def test_canonical_json_is_strict_with_non_finite_metrics(tmp_path: Path) -> None:
    frame = Path("broken.1001.exr")
    report = AnalysisReport(
        source=Path("renders"),
        frames=(frame,),
        inspections=(),
        metrics_by_aov={
            "beauty": MetricSet(
                0.0,
                float("nan"),
                float("nan"),
                pixel_count=1,
                nan_count=1,
            )
        },
        failed_frames=(frame,),
        frame_metrics={
            frame: {
                "beauty": MetricSet(
                    0.0,
                    float("nan"),
                    float("nan"),
                    pixel_count=1,
                    nan_count=1,
                )
            }
        },
        channel_metrics_by_aov={
            "Z": {"Z": ChannelMetricSet(1, 10.0, 10.0, 10.0)},
        },
    )
    output = tmp_path / "canonical.json"

    options = AnalysisOptions(
        frame_pattern="shot.*.exr",
        recursive=True,
        max_depth=2,
        allow_multiple_sequences=True,
        source_mode=SourceMode.COMPARISON,
        aov_category_overrides={"rendererData": AOVCategory.SCALAR},
    )
    write_analysis_json(report, output, options=options)

    text = output.read_text(encoding="utf-8")
    payload = json.loads(
        text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value))
    )
    assert "NaN" not in text
    assert "Infinity" not in text
    assert payload["schema_version"] == "1.0"
    assert payload["metadata"]["frames_discovered"] == 1
    assert payload["metadata"]["frames_processed"] == 0
    assert payload["metadata"]["frames_failed"] == 1
    assert payload["metadata"]["status"] == "fail"
    assert payload["metadata"]["color_aovs_analyzed"] == 1
    assert payload["metadata"]["technical_aovs_diagnosed"] == 1
    assert payload["metadata"]["aovs_diagnosed"] == 2
    assert payload["metadata"]["options"]["frame_pattern"] == "shot.*.exr"
    assert payload["metadata"]["options"]["recursive"] is True
    assert payload["metadata"]["options"]["max_depth"] == 2
    assert payload["metadata"]["options"]["allow_multiple_sequences"] is True
    assert payload["metadata"]["options"]["source_mode"] == "comparison"
    assert payload["metadata"]["options"]["aov_category_overrides"] == {
        "rendererData": "scalar",
    }
    assert payload["metadata"]["source_kind"] == "single_file"
    assert payload["metrics_by_aov"]["beauty"]["avg_luminance"] is None
    assert payload["frame_metrics"][str(frame)]["beauty"]["avg_luminance"] is None


def test_canonical_json_includes_explicit_aov_inventory() -> None:
    frame = Path("shot.1001.exr")
    descriptor = AOVDescriptor(
        "rendererData",
        ("rendererData.foo", "rendererData.bar"),
        AOVCategory.UNKNOWN,
        "insufficient_evidence",
    )
    report = AnalysisReport(
        source=frame,
        frames=(frame,),
        inspections=(
            FileInspection(
                path=frame,
                width=1,
                height=1,
                channels=descriptor.channels,
                aovs=(descriptor,),
            ),
        ),
        metrics_by_aov={},
        channel_metrics_by_aov={
            "rendererData": {
                "rendererData.foo": ChannelMetricSet(1, 1.0, 1.0, 1.0),
                "rendererData.bar": ChannelMetricSet(1, 2.0, 2.0, 2.0),
            }
        },
    )

    payload = build_analysis_report_payload(report, options=AnalysisOptions(max_frames=10))

    assert payload["aov_inventory"] == [
        {
            "name": "rendererData",
            "category": "unknown",
            "category_confidence": "insufficient_evidence",
            "channels": ["rendererData.bar", "rendererData.foo"],
            "files": [str(frame)],
        }
    ]
    assert payload["metadata"]["options"]["max_frames"] == 10


def test_report_version_falls_back_for_uninstalled_source_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_version(_name: str) -> str:
        raise json_report.metadata.PackageNotFoundError

    monkeypatch.setattr(json_report.metadata, "version", missing_version)

    assert json_report._version() == "unknown"
