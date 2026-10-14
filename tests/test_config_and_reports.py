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
    FrameExecutionRecord,
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
    assert payload["schema_version"] == "1.2"
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


def test_report_memory_budget_is_additive_for_schema_12_and_old_baselines() -> None:
    from copy import deepcopy

    from aovguard.reports.comparison import compare_report_payloads
    from aovguard.reports.html_report import build_analysis_html

    report = AnalysisReport(source=Path("renders"), frames=(), inspections=(), metrics_by_aov={})
    payload = build_analysis_report_payload(report, options=AnalysisOptions())
    assert payload["schema_version"] == "1.2"
    assert payload["metadata"]["options"]["max_memory_mb"] is None
    assert payload["memory_estimates"] == {}
    assert payload["metadata"]["memory_estimation"]["budget_unit"] == "MiB"
    assert payload["metadata"]["memory_estimation"]["bytes_per_mib"] == 1024 * 1024
    assert "not a hard" in payload["metadata"]["memory_estimation"]["caveat"]

    legacy = deepcopy(payload)
    legacy["metadata"]["options"].pop("max_memory_mb")
    legacy["metadata"].pop("memory_estimation")
    legacy.pop("memory_estimates")
    comparison = compare_report_payloads(legacy, payload)
    assert comparison.warnings == ()
    assert comparison.changed_aov_count == 0
    budgeted = build_analysis_report_payload(report, options=AnalysisOptions(max_memory_mb=12.5))
    assert compare_report_payloads(legacy, budgeted).warnings == ()
    assert "Memory estimate budget: <strong>Unlimited</strong>" in build_analysis_html(
        report, options=AnalysisOptions()
    )


def test_memory_report_preserves_breakdown_and_exact_large_budget_decision() -> None:
    from dataclasses import replace

    from aovguard.core.memory import MEMORY_MODEL_VERSION, MIB_BYTES, estimate_frame_memory
    from aovguard.reports.html_report import build_analysis_html

    frame = Path("frame<script>.exr")
    inspection = FileInspection(frame, 2, 2, ("R", "G", "B"), ())
    estimate = estimate_frame_memory(inspection)
    exact_bytes = (1 << 54) + 1
    estimate = replace(estimate, estimated_bytes=exact_bytes, estimated_mib=exact_bytes / MIB_BYTES)
    report = AnalysisReport(
        source=frame, frames=(frame,), inspections=(inspection,), metrics_by_aov={},
        failed_frames=(frame,), memory_estimates={frame: estimate},
    )
    options = AnalysisOptions(max_memory_mb=(1 << 54) / MIB_BYTES)

    payload = build_analysis_report_payload(report, options=options)
    stored = payload["memory_estimates"][str(frame)]
    assert stored["estimated_bytes"] == exact_bytes
    assert stored["native_channel_bytes"] == 2 * 2 * 3 * 4
    assert stored["fixed_reserve_bytes"] == 64 * MIB_BYTES
    assert stored["model_version"] == MEMORY_MODEL_VERSION
    assert payload["metadata"]["memory_estimation"]["model_version"] == MEMORY_MODEL_VERSION
    # Display rounding hides the single excess byte; admission and reporting must not.
    assert estimate.estimated_mib == options.max_memory_mb
    document = build_analysis_html(report, options=options)
    assert "Blocked by estimate budget" in document
    assert "frame&lt;script&gt;.exr" in document
    assert "frame<script>.exr" not in document
    assert "Budget not recorded" in build_analysis_html(report)


def test_execution_diagnostics_are_additive_and_do_not_change_baseline_semantics() -> None:
    from copy import deepcopy

    from aovguard.reports.comparison import compare_report_payloads
    from aovguard.reports.html_report import build_analysis_html

    frame = Path("frame<script>.exr")
    record = FrameExecutionRecord(
        mode="isolated", status="completed", worker_pid=12345, elapsed_seconds=0.25,
        timeout_seconds=2.0, exit_code=None, stage="measurement",
    )
    report = AnalysisReport(
        source=frame, frames=(frame,), inspections=(),
        metrics_by_aov={"beauty": MetricSet(1.0, 1.0, 1.0, pixel_count=4)},
        frame_execution={frame: record},
    )
    payload = build_analysis_report_payload(
        report, options=AnalysisOptions(isolate_frames=True, frame_timeout_seconds=2.0)
    )
    assert payload["schema_version"] == "1.2"
    assert payload["metadata"]["options"]["isolate_frames"] is True
    assert payload["metadata"]["options"]["frame_timeout_seconds"] == 2.0
    assert payload["frame_execution"][str(frame)] == {
        "mode": "isolated", "status": "completed", "worker_pid": 12345,
        "elapsed_seconds": 0.25, "timeout_seconds": 2.0, "exit_code": None,
        "stage": "measurement",
    }
    legacy = deepcopy(payload)
    legacy.pop("frame_execution")
    legacy["metadata"]["options"].pop("isolate_frames")
    legacy["metadata"]["options"].pop("frame_timeout_seconds")
    comparison = compare_report_payloads(legacy, payload)
    assert comparison.changed_aov_count == 0
    assert comparison.new_findings == ()
    assert comparison.warnings == ()
    changed_execution = deepcopy(payload)
    changed_execution["frame_execution"][str(frame)]["worker_pid"] = 99999
    changed_execution["frame_execution"][str(frame)]["elapsed_seconds"] = 9.0
    changed_execution["metadata"]["options"]["isolate_frames"] = False
    changed_execution["metadata"]["options"]["frame_timeout_seconds"] = None
    assert compare_report_payloads(payload, changed_execution).changed_aov_count == 0
    document = build_analysis_html(
        report, options=AnalysisOptions(isolate_frames=True, frame_timeout_seconds=2.0)
    )
    assert "Frame Execution Diagnostics" in document
    assert "12345" in document
    assert "0.250" in document
    assert "measurement" in document
    assert "not a security sandbox or a hard RSS cap" in document
    assert "Startup and termination cleanup use separate" in document
    assert "frame&lt;script&gt;.exr" in document
    assert "frame<script>.exr" not in document
