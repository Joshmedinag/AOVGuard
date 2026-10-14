"""Comparison models and operations for canonical JSON reports."""

from __future__ import annotations

import json
import math
import posixpath
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aovguard.io.output import atomic_text_writer


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
    warnings: tuple[str, ...] = ()

    @property
    def changed_aov_count(self) -> int:
        """Return the number of AOVs not verified as numerically unchanged."""

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
    _validate_schema(payload)
    return payload


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _difference(candidate: object, baseline: object) -> float | None:
    candidate_number = _number(candidate)
    baseline_number = _number(baseline)
    if candidate_number is None or baseline_number is None:
        return None
    difference = candidate_number - baseline_number
    return difference if math.isfinite(difference) else None


def _json_safe(value: Any) -> Any:
    """Sanitize non-finite numbers while rejecting non-JSON evidence values."""

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    raise ValueError(f"Report evidence contains a non-JSON value: {type(value).__name__}.")


def _canonical_json(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, dict):
            return {key: normalize(child) for key, child in item.items()}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        return item

    return json.dumps(
        normalize(_json_safe(value)), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _validate_schema(payload: Mapping[str, Any]) -> None:
    version = payload.get("schema_version")
    if version not in ("1.0", "1.1", "1.2"):
        raise ValueError(
            f"Unsupported AOVGuard report schema_version {version!r}; expected 1.0, 1.1 or 1.2."
        )


def _metadata(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("Report metadata values must be JSON objects.")
    return metadata


def _semantic_option(name: str, value: Any) -> Any:
    if name == "luminance_weights":
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 3
            or any(_number(weight) is None for weight in value)
        ):
            raise ValueError("Report luminance_weights must contain three finite numbers.")
        return [float(weight) for weight in value]
    if name == "non_black_threshold":
        number = _number(value)
        if number is None:
            raise ValueError("Report non_black_threshold must be a finite number.")
        return number
    if not isinstance(value, Mapping):
        raise ValueError("Report aov_category_overrides values must be JSON objects.")
    if any(not isinstance(key, str) or not isinstance(category, str) for key, category in value.items()):
        raise ValueError("Report aov_category_overrides must map AOV names to category strings.")
    # Match the reader's case-insensitive, last-key-wins preset semantics.
    return {key.casefold(): category.lower() for key, category in value.items()}


def _effective_rules(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(rule, Mapping) for rule in value
    ):
        raise ValueError("Report effective_rules values must be JSON arrays of rule objects.")
    rules: list[dict[str, Any]] = []
    for rule in value:
        sanitized = _json_safe(rule)
        if not isinstance(sanitized.get("id"), str):
            raise ValueError("Report effective_rules entries must have a string id.")
        supported_types = sanitized.get("supported_aov_types")
        if supported_types is not None:
            if not isinstance(supported_types, list) or any(
                not isinstance(category, str) for category in supported_types
            ):
                raise ValueError("Report supported_aov_types must contain category strings.")
            sanitized["supported_aov_types"] = sorted(set(supported_types))
        # Disabled definitions have no semantic effect. Adding a new opt-in
        # rule must not invalidate otherwise identical historical baselines.
        if sanitized.get("enabled") is not False:
            rules.append(sanitized)
    return sorted(rules, key=lambda rule: rule["id"])


def _compatibility_warnings(
    baseline_metadata: Mapping[str, Any],
    candidate_metadata: Mapping[str, Any],
) -> tuple[str, ...]:
    unavailable: list[str] = []
    baseline_options = baseline_metadata.get("options")
    candidate_options = candidate_metadata.get("options")
    for label, options in (("baseline", baseline_options), ("candidate", candidate_options)):
        if options is None:
            unavailable.append(f"{label} options")
        elif not isinstance(options, Mapping):
            raise ValueError("Report metadata.options values must be JSON objects or null.")

    if isinstance(baseline_options, Mapping) and isinstance(candidate_options, Mapping):
        for name in ("luminance_weights", "non_black_threshold", "aov_category_overrides"):
            if name not in baseline_options or name not in candidate_options:
                unavailable.append(name)
                continue
            baseline_value = _semantic_option(name, baseline_options[name])
            candidate_value = _semantic_option(name, candidate_options[name])
            if _canonical_json(baseline_value) != _canonical_json(candidate_value):
                raise ValueError(f"Incompatible analysis configuration: {name} differs.")

    for name in ("source_kind", "effective_rules"):
        baseline_value = baseline_metadata.get(name)
        candidate_value = candidate_metadata.get(name)
        if baseline_value is None or candidate_value is None:
            unavailable.append(name)
            continue
        if name == "effective_rules":
            baseline_value = _effective_rules(baseline_value)
            candidate_value = _effective_rules(candidate_value)
        if _canonical_json(baseline_value) != _canonical_json(candidate_value):
            raise ValueError(f"Incompatible analysis configuration: {name} differs.")
    baseline_region = baseline_metadata.get("measurement_region")
    candidate_region = candidate_metadata.get("measurement_region")
    if (
        baseline_region is not None
        and candidate_region is not None
        and baseline_region != candidate_region
    ):
        raise ValueError("Incompatible analysis configuration: measurement_region differs.")
    if not unavailable:
        return ()
    return (
        "Analysis compatibility could not be fully verified because configuration is missing: "
        + ", ".join(unavailable)
        + ".",
    )


def _relative_finding_path(value: Any, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Finding file and affected_files values must be strings or null.")
    path = posixpath.normpath(value.replace("\\", "/"))
    if not source:
        return path
    root = posixpath.normpath(source.replace("\\", "/"))
    windows_path = "\\" in source or (len(root) > 1 and root[1] == ":")
    path_identity = path.casefold() if windows_path else path
    root_identity = root.casefold() if windows_path else root
    if path_identity == root_identity:
        return "."
    if root.casefold().endswith(".exr"):
        root = posixpath.dirname(root)
        root_identity = root.casefold() if windows_path else root
    prefix = root_identity.rstrip("/") + "/"
    if path_identity.startswith(prefix):
        return path[len(prefix) :]
    return path


def _finding_metrics(finding: Mapping[str, Any], source: str) -> Any:
    metrics = _json_safe(finding.get("metrics", {}))
    if not isinstance(metrics, Mapping):
        raise ValueError("Finding metrics values must be JSON objects.")
    normalized = dict(metrics)
    if "baseline_file" in metrics:
        normalized["baseline_file"] = _relative_finding_path(metrics["baseline_file"], source)
    per_frame = metrics.get("per_frame")
    if per_frame is not None:
        if not isinstance(per_frame, Mapping):
            raise ValueError("Finding per_frame evidence must be a JSON object.")
        normalized["per_frame"] = {
            _relative_finding_path(path, source): values for path, values in per_frame.items()
        }
    files = metrics.get("files")
    if files is not None:
        if not isinstance(files, (list, tuple)):
            raise ValueError("Finding files evidence must be a JSON array.")
        paths: list[str] = []
        for path in files:
            relative = _relative_finding_path(path, source)
            if relative is None:
                raise ValueError("Finding files evidence must contain file paths.")
            paths.append(relative)
        normalized["files"] = sorted(paths)
    return normalized


def _finding_key(finding: Mapping[str, Any], source: str) -> str:
    affected_files = finding.get("affected_files", [])
    if not isinstance(affected_files, (list, tuple)):
        raise ValueError("Finding affected_files values must be JSON arrays.")
    paths: list[str] = []
    for path in affected_files:
        normalized = _relative_finding_path(path, source)
        if normalized is None:
            raise ValueError("Finding affected_files must contain file paths.")
        paths.append(normalized)
    evidence = {
        name: finding.get(name) for name in ("rule_id", "severity", "aov", "channel")
    }
    evidence["file"] = _relative_finding_path(finding.get("file"), source)
    evidence["affected_files"] = sorted(set(paths))
    evidence["metrics"] = _finding_metrics(finding, source)
    return _canonical_json(evidence)


def _findings_by_key(payload: Mapping[str, Any], source: str) -> dict[str, Mapping[str, Any]]:
    findings = payload.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError("Report findings values must be JSON arrays.")
    result: dict[str, Mapping[str, Any]] = {}
    for finding in findings:
        if not isinstance(finding, Mapping):
            raise ValueError("Report findings entries must be JSON objects.")
        result[_finding_key(finding, source)] = _json_safe(finding)
    return result


def compare_report_payloads(
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    tolerance: float = 1e-12,
) -> ReportComparison:
    """Compare compatible reports and mark missing numeric evidence unavailable.

    Legacy reports without configuration remain readable, with a warning that
    compatibility could not be fully verified. Conflicting recorded settings or
    unsupported schema versions fail explicitly rather than returning a delta.
    """

    if isinstance(tolerance, bool) or tolerance < 0 or not math.isfinite(tolerance):
        raise ValueError("Comparison tolerance must be finite and non-negative.")
    _validate_schema(baseline)
    _validate_schema(candidate)
    baseline_metadata = _metadata(baseline)
    candidate_metadata = _metadata(candidate)
    warnings = _compatibility_warnings(baseline_metadata, candidate_metadata)
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
        values = (average_delta, ratio_delta, maximum_delta)
        if any(value is None for value in values):
            status = "unavailable"
        else:
            status = (
                "changed"
                if any(abs(value) > tolerance for value in values if value is not None)
                else "unchanged"
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

    baseline_source = str(baseline_metadata.get("source") or "")
    candidate_source = str(candidate_metadata.get("source") or "")
    baseline_by_key = _findings_by_key(baseline, baseline_source)
    candidate_by_key = _findings_by_key(candidate, candidate_source)
    return ReportComparison(
        baseline_source=baseline_source,
        candidate_source=candidate_source,
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
        warnings=warnings,
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

    payload = {
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
        "warnings": list(comparison.warnings),
    }
    return _json_safe(payload)


def write_comparison_json(
    comparison: ReportComparison,
    output_path: str | Path,
    *,
    protected_paths: Iterable[str | Path] = (),
) -> None:
    """Atomically publish strict JSON; pass baseline/candidate files as protected paths."""

    sources = tuple(
        value for value in (comparison.baseline_source, comparison.candidate_source) if value
    )
    with atomic_text_writer(output_path, protected_paths=(*sources, *protected_paths)) as handle:
        json.dump(build_comparison_payload(comparison), handle, indent=2, allow_nan=False)
