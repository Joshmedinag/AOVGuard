"""Comparison models and operations for canonical JSON reports."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class AOVMetricDelta:
    """Per-AOV metric changes between baseline and candidate."""

    aov: str
    status: str
    average_luminance_delta: float | None = None
    non_black_ratio_delta: float | None = None
    max_luminance_delta: float | None = None


@dataclass(frozen=True, slots=True)
class ReportComparison:
    """Structured comparison result for two canonical reports."""

    baseline_source: str
    candidate_source: str
    baseline_status: str
    candidate_status: str
    metric_deltas: tuple[AOVMetricDelta, ...]
    new_findings: tuple[Mapping[str, Any], ...]
    resolved_findings: tuple[Mapping[str, Any], ...]

    @property
    def changed_aov_count(self) -> int:
        """Return the number of added, removed or changed AOVs."""

        return sum(delta.status != "unchanged" for delta in self.metric_deltas)


def load_report_payload(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate a canonical JSON report."""

    report_path = Path(path)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON report {report_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"AOVGuard report {report_path} must contain a JSON object.")
    if "metadata" not in payload or "metrics_by_aov" not in payload:
        raise ValueError(f"JSON file {report_path} is not a canonical AOVGuard analysis report.")
    return payload


def _number(value: object) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _difference(candidate: object, baseline: object) -> float | None:
    candidate_number = _number(candidate)
    baseline_number = _number(baseline)
    if candidate_number is None or baseline_number is None:
        return None
    return candidate_number - baseline_number


def _finding_key(finding: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(finding.get(name) or "") for name in ("rule_id", "severity", "aov", "channel", "file")
    )


def compare_report_payloads(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = 1e-12,
) -> ReportComparison:
    """Compare canonical report payloads with a numeric tolerance."""

    if tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("Comparison tolerance must be finite and non-negative.")
    baseline_metrics = baseline.get("metrics_by_aov", {})
    candidate_metrics = candidate.get("metrics_by_aov", {})
    if not isinstance(baseline_metrics, Mapping) or not isinstance(candidate_metrics, Mapping):
        raise ValueError("Report metrics_by_aov values must be JSON objects.")

    deltas: list[AOVMetricDelta] = []
    for aov_name in sorted(set(baseline_metrics) | set(candidate_metrics)):
        if aov_name not in baseline_metrics:
            deltas.append(AOVMetricDelta(str(aov_name), "added"))
            continue
        if aov_name not in candidate_metrics:
            deltas.append(AOVMetricDelta(str(aov_name), "removed"))
            continue
        baseline_values = baseline_metrics[aov_name]
        candidate_values = candidate_metrics[aov_name]
        if not isinstance(baseline_values, Mapping) or not isinstance(candidate_values, Mapping):
            raise ValueError(f"Metrics for AOV {aov_name!r} must be JSON objects.")
        average_delta = _difference(
            candidate_values.get("avg_luminance"),
            baseline_values.get("avg_luminance"),
        )
        ratio_delta = _difference(
            candidate_values.get("non_black_ratio"),
            baseline_values.get("non_black_ratio"),
        )
        maximum_delta = _difference(
            candidate_values.get("max_luminance"),
            baseline_values.get("max_luminance"),
        )
        finite_deltas = (
            value for value in (average_delta, ratio_delta, maximum_delta) if value is not None
        )
        status = (
            "changed" if any(abs(value) > tolerance for value in finite_deltas) else "unchanged"
        )
        deltas.append(
            AOVMetricDelta(
                aov=str(aov_name),
                status=status,
                average_luminance_delta=average_delta,
                non_black_ratio_delta=ratio_delta,
                max_luminance_delta=maximum_delta,
            )
        )

    baseline_findings = baseline.get("findings", [])
    candidate_findings = candidate.get("findings", [])
    if not isinstance(baseline_findings, list) or not isinstance(candidate_findings, list):
        raise ValueError("Report findings values must be JSON arrays.")
    baseline_by_key = {
        _finding_key(finding): finding
        for finding in baseline_findings
        if isinstance(finding, Mapping)
    }
    candidate_by_key = {
        _finding_key(finding): finding
        for finding in candidate_findings
        if isinstance(finding, Mapping)
    }

    baseline_metadata = baseline.get("metadata", {})
    candidate_metadata = candidate.get("metadata", {})
    if not isinstance(baseline_metadata, Mapping):
        baseline_metadata = {}
    if not isinstance(candidate_metadata, Mapping):
        candidate_metadata = {}
    return ReportComparison(
        baseline_source=str(baseline_metadata.get("source") or ""),
        candidate_source=str(candidate_metadata.get("source") or ""),
        baseline_status=str(baseline_metadata.get("status") or "unknown"),
        candidate_status=str(candidate_metadata.get("status") or "unknown"),
        metric_deltas=tuple(deltas),
        new_findings=tuple(
            candidate_by_key[key]
            for key in sorted(candidate_by_key.keys() - baseline_by_key.keys())
        ),
        resolved_findings=tuple(
            baseline_by_key[key] for key in sorted(baseline_by_key.keys() - candidate_by_key.keys())
        ),
    )


def compare_report_files(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    tolerance: float = 1e-12,
) -> ReportComparison:
    """Load and compare two canonical JSON report files."""

    return compare_report_payloads(
        load_report_payload(baseline_path),
        load_report_payload(candidate_path),
        tolerance=tolerance,
    )


def build_comparison_payload(comparison: ReportComparison) -> dict[str, Any]:
    """Convert a comparison result to a JSON-compatible payload."""

    return {
        "schema_version": "1.0",
        "baseline": {
            "source": comparison.baseline_source,
            "status": comparison.baseline_status,
        },
        "candidate": {
            "source": comparison.candidate_source,
            "status": comparison.candidate_status,
        },
        "summary": {
            "aovs_compared": len(comparison.metric_deltas),
            "aovs_changed": comparison.changed_aov_count,
            "new_findings": len(comparison.new_findings),
            "resolved_findings": len(comparison.resolved_findings),
        },
        "metric_deltas": [
            {
                "aov": delta.aov,
                "status": delta.status,
                "average_luminance_delta": delta.average_luminance_delta,
                "non_black_ratio_delta": delta.non_black_ratio_delta,
                "max_luminance_delta": delta.max_luminance_delta,
            }
            for delta in comparison.metric_deltas
        ],
        "new_findings": [dict(finding) for finding in comparison.new_findings],
        "resolved_findings": [dict(finding) for finding in comparison.resolved_findings],
    }


def write_comparison_json(
    comparison: ReportComparison,
    output_path: str | Path,
) -> None:
    """Write a strict comparison payload to UTF-8 JSON."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_comparison_payload(comparison), indent=2, allow_nan=False),
        encoding="utf-8",
    )
