import json
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
