"""Built-in validation rules and their default definitions."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

from aovguard.core.models import (
    AnalysisReport,
    AOVCategory,
    FileInspection,
    Finding,
    Severity,
)
from aovguard.rules.definitions import RuleDefinition


def _float_parameter(
    definition: RuleDefinition,
    name: str,
    default: float,
) -> float:
    raw_value = definition.parameters.get(name, default)
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        raise ValueError(f"Rule parameter {name!r} must be numeric.")
    value = float(raw_value)
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Rule parameter {name!r} must be a finite, non-negative number.")
    return value


def _string_list_parameter(definition: RuleDefinition, name: str) -> tuple[str, ...]:
    value = definition.parameters.get(name, ())
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError(f"Rule parameter {name!r} must be a list of strings.")
    values = tuple(str(item) for item in value)
    if any(not item for item in values):
        raise ValueError(f"Rule parameter {name!r} must not contain empty values.")
    return values


def _bool_parameter(definition: RuleDefinition, name: str, default: bool) -> bool:
    value = definition.parameters.get(name, default)
    if not isinstance(value, bool):
        raise ValueError(f"Rule parameter {name!r} must be a boolean.")
    return value


def _aov_categories(report: AnalysisReport) -> dict[str, AOVCategory]:
    categories: dict[str, AOVCategory] = {}
    for inspection in report.inspections:
        for descriptor in inspection.aovs:
            categories.setdefault(descriptor.name, descriptor.category)
    return categories


def _avg_abs_luminance(value: float | None) -> float:
    """Return the initialized absolute average stored on a metric set."""

    if value is None:
        raise ValueError("MetricSet.avg_abs_luminance was not initialized.")
    return float(value)


def _max_abs_luminance(value: float | None) -> float:
    """Return the initialized absolute maximum stored on a metric set."""

    if value is None:
        raise ValueError("MetricSet.max_abs_luminance was not initialized.")
    return float(value)


def _supports_aov(
    definition: RuleDefinition,
    aov_name: str,
    categories: dict[str, AOVCategory],
) -> bool:
    if not definition.supported_aov_types:
        return True
    category = categories.get(aov_name, AOVCategory.UNKNOWN)
    return category in definition.supported_aov_types


def validate_unknown_aov(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report unclassified AOVs while retaining their channels for diagnostics."""

    occurrences: dict[str, list[tuple[Path, tuple[str, ...], str]]] = {}
    for inspection in report.inspections:
        for descriptor in inspection.aovs:
            if descriptor.category is AOVCategory.UNKNOWN:
                occurrences.setdefault(descriptor.name, []).append(
                    (
                        inspection.path,
                        descriptor.channels,
                        descriptor.category_confidence,
                    )
                )

    findings: list[Finding] = []
    for aov_name, samples in sorted(occurrences.items()):
        affected_files = tuple(sample[0] for sample in samples)
        channels = sorted({channel for _path, names, _confidence in samples for channel in names})
        confidence = samples[0][2]
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message=(
                    "AOV category could not be inferred. Its channels were retained "
                    "and checked for data integrity without color semantics."
                ),
                file=affected_files[0] if len(affected_files) == 1 else None,
                aov=aov_name,
                metrics={
                    "channels": channels,
                    "provisional_category": AOVCategory.UNKNOWN.value,
                    "category_confidence": confidence,
                    "files": [str(path) for path in affected_files],
                },
                affected_files=affected_files,
            )
        )
    return findings


def validate_nan_inf(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report non-finite values using exact channel evidence when available."""

    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, channel_metrics in report.channel_metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        for channel_name, metrics in channel_metrics.items():
            if not metrics.has_non_finite:
                continue
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message="Non-finite channel values were detected.",
                    file=report.source,
                    aov=aov_name,
                    channel=channel_name,
                    metrics={
                        "nan_count": metrics.nan_count,
                        "posinf_count": metrics.posinf_count,
                        "neginf_count": metrics.neginf_count,
                    },
                )
            )
    if findings:
        return findings

    for aov_name, aggregate_metrics in report.metrics_by_aov.items():
        if not aggregate_metrics.has_non_finite or not _supports_aov(
            definition, aov_name, categories
        ):
            continue
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message="Non-finite pixel values were detected.",
                file=report.source,
                aov=aov_name,
                metrics={
                    "nan_count": aggregate_metrics.nan_count,
                    "posinf_count": aggregate_metrics.posinf_count,
                    "neginf_count": aggregate_metrics.neginf_count,
                },
            )
        )
    return findings


def validate_negative_values(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report finite values below zero for supported AOV categories."""

    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, channel_metrics in report.channel_metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        for channel_name, metrics in channel_metrics.items():
            if metrics.negative_count == 0:
                continue
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message="Negative channel values were detected.",
                    file=report.source,
                    aov=aov_name,
                    channel=channel_name,
                    metrics={
                        "negative_count": metrics.negative_count,
                        "min_value": metrics.min_value,
                    },
                )
            )
    return findings


def validate_extreme_values(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report finite channel values outside a configurable absolute limit."""

    max_absolute = _float_parameter(definition, "max_absolute", 1_000_000.0)
    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, channel_metrics in report.channel_metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        for channel_name, metrics in channel_metrics.items():
            observed = max(abs(metrics.min_value), abs(metrics.max_value))
            if not math.isfinite(observed) or observed <= max_absolute:
                continue
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message="Finite channel values exceed the configured absolute limit.",
                    file=report.source,
                    aov=aov_name,
                    channel=channel_name,
                    metrics={
                        "min_value": metrics.min_value,
                        "max_value": metrics.max_value,
                        "max_absolute": max_absolute,
                    },
                )
            )
    return findings


def validate_constant_channel(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report channels whose finite values remain constant."""

    tolerance = _float_parameter(definition, "tolerance", 0.0)
    skip_empty_aovs = _bool_parameter(definition, "skip_empty_aovs", True)
    empty_max_luminance = _float_parameter(
        definition,
        "empty_max_luminance",
        1e-5,
    )
    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, channel_metrics in report.channel_metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        aov_metrics = report.metrics_by_aov.get(aov_name)
        if (
            skip_empty_aovs
            and aov_metrics is not None
            and not aov_metrics.has_non_finite
            and _max_abs_luminance(aov_metrics.max_abs_luminance) <= empty_max_luminance
        ):
            continue
        for channel_name, metrics in channel_metrics.items():
            if metrics.has_non_finite or metrics.pixel_count == 0:
                continue
            if metrics.max_value - metrics.min_value > tolerance:
                continue
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message="Channel is constant across all analyzed pixels.",
                    file=report.source,
                    aov=aov_name,
                    channel=channel_name,
                    metrics={
                        "value": metrics.avg_value,
                        "tolerance": tolerance,
                    },
                )
            )
    return findings


def validate_empty_aov(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report color AOVs with no visible contribution."""

    max_luminance = _float_parameter(definition, "max_luminance", 1e-5)
    max_average = _float_parameter(definition, "max_average", 1e-6)
    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, metrics in report.metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        frame_samples = [
            (frame_path, frame_aovs[aov_name])
            for frame_path, frame_aovs in report.frame_metrics.items()
            if aov_name in frame_aovs
        ]
        if not frame_samples:
            frame_samples = [(report.source, metrics)]
        affected_files = tuple(
            frame_path
            for frame_path, frame_metric in frame_samples
            if not frame_metric.has_non_finite
            and _max_abs_luminance(frame_metric.max_abs_luminance) <= max_luminance
            and _avg_abs_luminance(frame_metric.avg_abs_luminance) <= max_average
        )
        if affected_files:
            if len(frame_samples) == 1:
                message = "No visible AOV contribution was detected."
            else:
                message = (
                    "No visible AOV contribution was detected in "
                    f"{len(affected_files)}/{len(frame_samples)} analyzed files."
                )
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message=message,
                    file=affected_files[0] if len(affected_files) == 1 else None,
                    aov=aov_name,
                    metrics={
                        "avg_luminance": metrics.avg_luminance,
                        "max_luminance": metrics.max_luminance,
                        "avg_abs_luminance": metrics.avg_abs_luminance,
                        "max_abs_luminance": metrics.max_abs_luminance,
                        "affected_file_count": len(affected_files),
                        "analyzed_file_count": len(frame_samples),
                    },
                    affected_files=affected_files,
                )
            )
    return findings


def validate_near_empty_aov(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report color AOVs whose visible contribution is very limited."""

    max_ratio = _float_parameter(definition, "max_ratio", 0.02)
    max_average = _float_parameter(definition, "max_average", 0.001)
    empty_max_luminance = _float_parameter(definition, "empty_max_luminance", 1e-5)
    categories = _aov_categories(report)
    findings: list[Finding] = []
    for aov_name, metrics in report.metrics_by_aov.items():
        if not _supports_aov(definition, aov_name, categories):
            continue
        frame_samples = [
            (frame_path, frame_aovs[aov_name])
            for frame_path, frame_aovs in report.frame_metrics.items()
            if aov_name in frame_aovs
        ]
        if not frame_samples:
            frame_samples = [(report.source, metrics)]
        affected_files = tuple(
            frame_path
            for frame_path, frame_metric in frame_samples
            if not frame_metric.has_non_finite
            and _max_abs_luminance(frame_metric.max_abs_luminance) > empty_max_luminance
            and frame_metric.non_black_ratio <= max_ratio
            and _avg_abs_luminance(frame_metric.avg_abs_luminance) <= max_average
        )
        if affected_files:
            if len(frame_samples) == 1:
                message = "Only a very small AOV contribution was detected."
            else:
                message = (
                    "Only a very small AOV contribution was detected in "
                    f"{len(affected_files)}/{len(frame_samples)} analyzed files."
                )
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message=message,
                    file=affected_files[0] if len(affected_files) == 1 else None,
                    aov=aov_name,
                    metrics={
                        "non_black_ratio": metrics.non_black_ratio,
                        "avg_luminance": metrics.avg_luminance,
                        "max_luminance": metrics.max_luminance,
                        "avg_abs_luminance": metrics.avg_abs_luminance,
                        "max_abs_luminance": metrics.max_abs_luminance,
                        "affected_file_count": len(affected_files),
                        "analyzed_file_count": len(frame_samples),
                    },
                    affected_files=affected_files,
                )
            )
    return findings


def validate_missing_aov(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report required semantic AOV names absent from inspected files."""

    required = _string_list_parameter(definition, "required")
    findings: list[Finding] = []
    for inspection in report.inspections:
        available = {descriptor.name for descriptor in inspection.aovs}
        for aov_name in required:
            if aov_name not in available:
                findings.append(
                    Finding(
                        rule_id=definition.id,
                        severity=definition.severity,
                        message=f"Required AOV {aov_name!r} is missing.",
                        file=inspection.path,
                        aov=aov_name,
                    )
                )
    return findings


def validate_missing_channels(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report required exact EXR channel names absent from inspected files."""

    required = _string_list_parameter(definition, "required")
    findings: list[Finding] = []
    for inspection in report.inspections:
        available = set(inspection.channels)
        for channel in required:
            if channel not in available:
                findings.append(
                    Finding(
                        rule_id=definition.id,
                        severity=definition.severity,
                        message=f"Required channel {channel!r} is missing.",
                        file=inspection.path,
                        channel=channel,
                    )
                )
    return findings


def validate_resolution_mismatch(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report frames whose resolution differs from the first decoded frame."""

    if len(report.inspections) < 2:
        return []
    baseline = report.inspections[0]
    findings: list[Finding] = []
    for inspection in report.inspections[1:]:
        if (inspection.width, inspection.height) == (baseline.width, baseline.height):
            continue
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message=(
                    f"Resolution {inspection.width}x{inspection.height} differs from "
                    f"baseline {baseline.width}x{baseline.height}."
                ),
                file=inspection.path,
                metrics={
                    "baseline_width": baseline.width,
                    "baseline_height": baseline.height,
                    "width": inspection.width,
                    "height": inspection.height,
                },
            )
        )
    return findings


def _inspection_aov_signature(
    inspection: FileInspection,
) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {
        descriptor.name: (
            descriptor.category.value,
            tuple(sorted(descriptor.channels)),
        )
        for descriptor in inspection.aovs
    }


def validate_aov_structure_mismatch(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report frames whose AOV categories or channels change over time."""

    if len(report.inspections) < 2:
        return []
    baseline_signature = _inspection_aov_signature(report.inspections[0])
    findings: list[Finding] = []
    for inspection in report.inspections[1:]:
        signature = _inspection_aov_signature(inspection)
        if signature == baseline_signature:
            continue
        baseline_names = set(baseline_signature)
        current_names = set(signature)
        changed = sorted(
            name
            for name in baseline_names & current_names
            if baseline_signature[name] != signature[name]
        )
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message="AOV structure differs from the first analyzed frame.",
                file=inspection.path,
                metrics={
                    "missing_aovs": sorted(baseline_names - current_names),
                    "new_aovs": sorted(current_names - baseline_names),
                    "changed_aovs": changed,
                },
            )
        )
    return findings


def default_rule_definitions() -> tuple[RuleDefinition, ...]:
    """Return the immutable built-in rule configuration."""

    color_only = frozenset({AOVCategory.COLOR})
    return (
        RuleDefinition(
            id="unknown_aov",
            severity=Severity.WARNING,
        ),
        RuleDefinition(
            id="nan_inf",
            severity=Severity.ERROR,
        ),
        RuleDefinition(
            id="empty_aov",
            severity=Severity.WARNING,
            supported_aov_types=color_only,
        ),
        RuleDefinition(
            id="near_empty_aov",
            severity=Severity.WARNING,
            supported_aov_types=color_only,
        ),
        RuleDefinition(
            id="negative_values",
            enabled=False,
            severity=Severity.WARNING,
            supported_aov_types=color_only,
        ),
        RuleDefinition(
            id="extreme_values",
            enabled=False,
            severity=Severity.WARNING,
            supported_aov_types=frozenset(
                category for category in AOVCategory if category is not AOVCategory.CRYPTOMATTE
            ),
        ),
        RuleDefinition(
            id="constant_channel",
            enabled=False,
            severity=Severity.INFO,
            supported_aov_types=color_only,
        ),
        RuleDefinition(id="missing_aov", enabled=False, severity=Severity.ERROR),
        RuleDefinition(id="missing_channels", enabled=False, severity=Severity.ERROR),
        RuleDefinition(id="resolution_mismatch", severity=Severity.ERROR),
        RuleDefinition(id="aov_structure_mismatch", severity=Severity.ERROR),
    )
