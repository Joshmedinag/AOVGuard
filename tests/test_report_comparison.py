import json
from copy import deepcopy
from pathlib import Path

import pytest

from aovguard.cli import main
from aovguard.reports.comparison import (
    build_comparison_payload,
    compare_report_files,
    compare_report_payloads,
    load_report_payload,
    write_comparison_json,
)


def _report(
    source: str,
    metrics: dict[str, dict[str, float]],
    findings: list[dict] | None = None,
    *,
    status: str = "pass",
) -> dict:
    return {
        "schema_version": "1.0",
        "metadata": {"source": source, "status": status},
        "metrics_by_aov": metrics,
        "findings": findings or [],
    }


def _metrics(average: float, ratio: float, maximum: float) -> dict[str, float]:
    return {
        "avg_luminance": average,
        "non_black_ratio": ratio,
        "max_luminance": maximum,
    }


def test_compare_report_payloads_tracks_metrics_and_findings() -> None:
    baseline_finding = {
        "rule_id": "empty_aov",
        "severity": "warning",
        "aov": "emission",
        "channel": None,
        "file": "old.exr",
    }
    candidate_finding = {
        "rule_id": "nan_inf",
        "severity": "error",
        "aov": "beauty",
        "channel": "R",
        "file": "new.exr",
    }
    baseline = _report(
        "baseline",
        {
            "beauty": _metrics(1.0, 0.5, 2.0),
            "removed": _metrics(0.2, 1.0, 0.4),
            "stable": _metrics(0.1, 1.0, 0.2),
        },
        [baseline_finding],
    )
    candidate = _report(
        "candidate",
        {
            "beauty": _metrics(1.5, 0.75, 3.0),
            "added": _metrics(0.3, 0.8, 0.5),
            "stable": _metrics(0.1, 1.0, 0.2),
        },
        [candidate_finding],
        status="fail",
    )

    comparison = compare_report_payloads(baseline, candidate)

    assert comparison.baseline_source == "baseline"
    assert comparison.candidate_status == "fail"
    assert comparison.changed_aov_count == 3
    by_name = {delta.aov: delta for delta in comparison.metric_deltas}
    assert by_name["added"].status == "added"
    assert by_name["removed"].status == "removed"
    assert by_name["stable"].status == "unchanged"
    assert by_name["beauty"].average_luminance_delta == pytest.approx(0.5)
    assert by_name["beauty"].non_black_ratio_delta == pytest.approx(0.25)
    assert by_name["beauty"].max_luminance_delta == pytest.approx(1.0)
    assert comparison.new_findings == (candidate_finding,)
    assert comparison.resolved_findings == (baseline_finding,)

    payload = build_comparison_payload(comparison)
    assert payload["summary"] == {
        "aovs_compared": 4,
        "aovs_changed": 3,
        "new_findings": 1,
        "resolved_findings": 1,
    }


def test_compare_report_files_loads_and_writes_json(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    candidate_path = tmp_path / "candidate.json"
    baseline_path.write_text(
        json.dumps(_report("a", {"beauty": _metrics(1.0, 1.0, 1.0)})),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps(_report("b", {"beauty": _metrics(1.0, 1.0, 1.0)})),
        encoding="utf-8",
    )

    comparison = compare_report_files(baseline_path, candidate_path)
    output = tmp_path / "nested" / "comparison.json"
    write_comparison_json(comparison, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["aovs_changed"] == 0
    assert payload["metric_deltas"][0]["status"] == "unchanged"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "JSON object"),
        ({"metadata": {}}, "canonical AOVGuard"),
    ],
)
def test_load_report_payload_rejects_invalid_shapes(
    tmp_path: Path,
    payload: object,
    message: str,
) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_report_payload(path)


def test_load_report_payload_reports_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid JSON report"):
        load_report_payload(path)


def test_comparison_validates_tolerance_and_report_sections() -> None:
    valid = _report("source", {})
    with pytest.raises(ValueError, match="tolerance"):
        compare_report_payloads(valid, valid, tolerance=-1.0)
    with pytest.raises(ValueError, match="metrics_by_aov"):
        compare_report_payloads({**valid, "metrics_by_aov": []}, valid)
    with pytest.raises(ValueError, match="findings"):
        compare_report_payloads({**valid, "findings": {}}, valid)
    with pytest.raises(ValueError, match="Metrics for AOV"):
        compare_report_payloads(
            {**valid, "metrics_by_aov": {"beauty": []}},
            {**valid, "metrics_by_aov": {"beauty": {}}},
        )


def test_cli_compare_reports_prints_and_exports(
    tmp_path: Path,
    capsys,
) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "comparison.json"
    baseline.write_text(
        json.dumps(_report("old", {"beauty": _metrics(1.0, 1.0, 1.0)})),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(_report("new", {"beauty": _metrics(2.0, 1.0, 2.0)})),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "compare-reports",
            str(baseline),
            str(candidate),
            "--json",
            str(output),
        ]
    )

    assert exit_code == 0
    assert "AOVs changed: 1" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["aovs_changed"] == 1


def test_cli_compare_reports_handles_invalid_input(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["compare-reports", str(broken), str(broken)])

    assert excinfo.value.code == 1
    assert "aovguard compare-reports: error:" in capsys.readouterr().err


def _configured_report(source: str) -> dict:
    report = _report(source, {"beauty": _metrics(1.0, 0.5, 2.0)})
    report["schema_version"] = "1.1"
    report["metadata"].update(
        {
            "source_kind": "sequence",
            "measurement_region": "data_window",
            "options": {
                "luminance_weights": [0.2126, 0.7152, 0.0722],
                "non_black_threshold": 0.001,
                "aov_category_overrides": {"custom": "scalar"},
            },
            "effective_rules": [
                {
                    "id": "nan_inf",
                    "enabled": True,
                    "severity": "error",
                    "parameters": {},
                    "supported_aov_types": ["color", "scalar"],
                },
                {
                    "id": "extreme_values",
                    "enabled": True,
                    "severity": "warning",
                    "parameters": {"threshold": 1000.0},
                    "supported_aov_types": ["color"],
                },
            ],
        }
    )
    return report


@pytest.mark.parametrize(
    ("baseline_value", "candidate_value"),
    [
        (1.0, None),
        (None, 1.0),
        (None, None),
        (1.0, True),
        (float("nan"), 1.0),
        (float("inf"), 1.0),
        (1e308, -1e308),
        (10**400, 1.0),
    ],
)
def test_missing_or_invalid_metric_evidence_is_unavailable(
    baseline_value: object,
    candidate_value: object,
) -> None:
    baseline = _report("old", {"beauty": _metrics(1.0, 0.5, 2.0)})
    candidate = deepcopy(baseline)
    baseline["metrics_by_aov"]["beauty"]["avg_luminance"] = baseline_value
    candidate["metrics_by_aov"]["beauty"]["avg_luminance"] = candidate_value

    comparison = compare_report_payloads(baseline, candidate)

    delta = comparison.metric_deltas[0]
    assert delta.status == "unavailable"
    assert delta.average_luminance_delta is None
    assert delta.non_black_ratio_delta == 0.0
    assert comparison.changed_aov_count == 1
    json.dumps(build_comparison_payload(comparison), allow_nan=False)


def test_legacy_report_configuration_is_explicitly_unverified() -> None:
    baseline = _report("old", {"beauty": _metrics(1.0, 0.5, 2.0)})
    candidate = _configured_report("new")

    comparison = compare_report_payloads(baseline, candidate)

    assert comparison.metric_deltas[0].status == "unchanged"
    assert len(comparison.warnings) == 1
    assert "could not be fully verified" in comparison.warnings[0]
    assert build_comparison_payload(comparison)["warnings"] == list(comparison.warnings)


@pytest.mark.parametrize("version", [None, True, "2.0", "1.3", "bad"])
def test_unsupported_report_schema_is_rejected(version: object, tmp_path: Path) -> None:
    invalid = _configured_report("source")
    invalid["schema_version"] = version
    path = tmp_path / "report.json"
    path.write_text(json.dumps(invalid), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        compare_report_payloads(invalid, _configured_report("source"))
    with pytest.raises(ValueError, match="schema_version"):
        load_report_payload(path)


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_supported_analysis_schemas_remain_comparable(version: str) -> None:
    baseline = _configured_report("source")
    baseline["schema_version"] = version
    candidate = _configured_report("source")
    candidate["schema_version"] = "1.2"
    comparison = compare_report_payloads(baseline, candidate)
    assert not comparison.metric_deltas or comparison.changed_aov_count == 0


def test_equivalent_recorded_configuration_allows_comparison() -> None:
    baseline = _configured_report("old")
    candidate = _configured_report("new")
    candidate["metadata"]["effective_rules"].reverse()
    candidate["metadata"]["effective_rules"][1]["supported_aov_types"].reverse()
    candidate["metadata"]["effective_rules"][0]["parameters"]["threshold"] = 1000
    candidate["metadata"]["options"]["preset_name"] = "renamed-preset.toml"
    candidate["metadata"]["options"]["source_mode"] = "sequence"

    comparison = compare_report_payloads(baseline, candidate)

    assert comparison.warnings == ()
    assert comparison.metric_deltas[0].status == "unchanged"


def test_category_override_case_matches_reader_semantics() -> None:
    baseline = _configured_report("old")
    candidate = _configured_report("new")
    baseline["metadata"]["options"]["aov_category_overrides"] = {"CUSTOM": "scalar", "Custom": "depth"}
    candidate["metadata"]["options"]["aov_category_overrides"] = {"custom": "depth"}
    assert compare_report_payloads(baseline, candidate).warnings == ()


@pytest.mark.parametrize(
    ("section", "name", "value"),
    [
        ("options", "luminance_weights", [0.2722, 0.6741, 0.0537]),
        ("options", "non_black_threshold", 0.01),
        ("options", "aov_category_overrides", {"custom": "depth"}),
        ("metadata", "source_kind", "comparison"),
        ("metadata", "measurement_region", "display_window"),
        ("rule", "severity", "warning"),
        ("rule", "enabled", False),
        ("rule", "parameters", {"maximum_nan_count": 10}),
    ],
)
def test_incompatible_recorded_configuration_is_rejected(
    section: str,
    name: str,
    value: object,
) -> None:
    baseline = _configured_report("old")
    candidate = _configured_report("new")
    if section == "options":
        target = candidate["metadata"]["options"]
    elif section == "rule":
        target = candidate["metadata"]["effective_rules"][0]
    else:
        target = candidate["metadata"]
    target[name] = value

    with pytest.raises(ValueError, match="Incompatible analysis configuration"):
        compare_report_payloads(baseline, candidate)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("luminance_weights", [True, 0.0, 0.0]),
        ("luminance_weights", [float("inf"), 0.0, 0.0]),
        ("luminance_weights", [1.0, 0.0]),
        ("non_black_threshold", False),
        ("non_black_threshold", float("nan")),
        ("aov_category_overrides", []),
        ("aov_category_overrides", {"custom": 1}),
    ],
)
def test_invalid_recorded_numeric_configuration_is_rejected(name: str, value: object) -> None:
    report = _configured_report("source")
    report["metadata"]["options"][name] = value

    with pytest.raises(ValueError, match=name):
        compare_report_payloads(report, report)


@pytest.mark.parametrize(
    ("baseline_root", "candidate_root"),
    [("/old/render", "/new/render"), (r"C:\old\render", r"D:\new\render")],
)
def test_finding_evidence_survives_root_relocation(
    baseline_root: str,
    candidate_root: str,
) -> None:
    baseline = _configured_report(baseline_root)
    candidate = _configured_report(candidate_root)
    finding = {
        "rule_id": "nan_inf",
        "severity": "error",
        "aov": "beauty",
        "channel": "R",
        "file": baseline_root + "/shot.0342.exr",
        "affected_files": [baseline_root + "/shot.0342.exr", baseline_root + "/shot.0343.exr"],
        "metrics": {
            "nan_count": 2,
            "baseline_file": baseline_root + "/shot.0001.exr",
            "nested": {"maximum": None},
            "per_frame": {
                baseline_root + "/shot.0342.exr": {"nan_count": 1},
                baseline_root + "/shot.0343.exr": {"nan_count": 1},
            },
            "files": [baseline_root + "/shot.0343.exr", baseline_root + "/shot.0342.exr"],
        },
    }
    baseline["findings"] = [finding]
    moved_finding = deepcopy(finding)
    moved_finding["file"] = candidate_root + "/shot.0342.exr"
    moved_finding["affected_files"] = [
        candidate_root + "/shot.0343.exr",
        candidate_root + "/shot.0342.exr",
    ]
    moved_finding["metrics"]["nan_count"] = 2.0
    moved_finding["metrics"]["baseline_file"] = candidate_root + "/shot.0001.exr"
    moved_finding["metrics"]["per_frame"] = {
        candidate_root + "/shot.0342.exr": {"nan_count": 1},
        candidate_root + "/shot.0343.exr": {"nan_count": 1},
    }
    moved_finding["metrics"]["files"] = [
        candidate_root + "/shot.0342.exr",
        candidate_root + "/shot.0343.exr",
    ]
    candidate["findings"] = [moved_finding]
    baseline_before = deepcopy(baseline)
    candidate_before = deepcopy(candidate)

    comparison = compare_report_payloads(baseline, candidate)

    assert comparison.new_findings == ()
    assert comparison.resolved_findings == ()
    assert baseline == baseline_before
    assert candidate == candidate_before


@pytest.mark.parametrize("changed_evidence", ["affected_files", "metrics"])
def test_changed_finding_evidence_is_new_and_resolves_old(changed_evidence: str) -> None:
    baseline = _configured_report("/render")
    finding = {
        "rule_id": "nan_inf",
        "severity": "error",
        "aov": "beauty",
        "channel": "R",
        "file": None,
        "affected_files": ["/render/shot.0342.exr"],
        "metrics": {"nan_count": 1},
    }
    baseline["findings"] = [finding]
    candidate = deepcopy(baseline)
    replacement = (
        ["/render/shot.0343.exr"] if changed_evidence == "affected_files" else {"nan_count": 2}
    )
    candidate["findings"][0][changed_evidence] = replacement

    comparison = compare_report_payloads(baseline, candidate)

    assert comparison.new_findings == (candidate["findings"][0],)
    assert comparison.resolved_findings == (finding,)


def test_non_finite_finding_evidence_can_be_written_as_strict_json(tmp_path: Path) -> None:
    baseline = _configured_report("/render")
    candidate = deepcopy(baseline)
    candidate["findings"] = [
        {
            "rule_id": "nan_inf",
            "metrics": {"minimum": float("nan"), "maximum": float("inf")},
        }
    ]

    comparison = compare_report_payloads(baseline, candidate)
    output = tmp_path / "comparison.json"
    write_comparison_json(comparison, output)

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["new_findings"][0]["metrics"] == {"minimum": None, "maximum": None}


def test_malformed_finding_evidence_is_rejected() -> None:
    valid = _configured_report("source")
    for malformed in [True, {"affected_files": [None]}, {"file": True}]:
        invalid = deepcopy(valid)
        invalid["findings"] = [malformed]
        with pytest.raises(ValueError, match="Finding|findings"):
            compare_report_payloads(valid, invalid)
