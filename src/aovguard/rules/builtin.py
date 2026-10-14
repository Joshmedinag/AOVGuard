"""Built-in validation rules and their default definitions."""

from __future__ import annotations

import math
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Callable

from aovguard.core.models import (
    AnalysisReport,
    AOVCategory,
    ChannelMetricSet,
    FileInspection,
    Finding,
    PartInspection,
    Severity,
    SourceKind,
)
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.technical import TECHNICAL_RANGE_CATEGORIES, technical_range_parameters

_PARAMETER_DEFAULTS: dict[str, dict[str, object]] = {
    "empty_aov": {"max_luminance": 1e-5, "max_average": 1e-6},
    "near_empty_aov": {"max_ratio": 0.02, "max_average": 0.001, "empty_max_luminance": 1e-5},
    "extreme_values": {"max_absolute": 1_000_000.0},
    "constant_channel": {"tolerance": 0.0, "skip_empty_aovs": True, "empty_max_luminance": 1e-5},
    "missing_aov": {"required": []},
    "missing_channels": {"required": []},
}


def effective_rule_parameters(definition: RuleDefinition) -> dict[str, object]:
    """Snapshot parsed built-in parameters, retaining invalid values for diagnostics."""

    if definition.id == "technical_range":
        try:
            return {"ranges": technical_range_parameters(definition)}
        except ValueError:
            return deepcopy(dict(definition.parameters))
    defaults = _PARAMETER_DEFAULTS.get(definition.id, {})
    parameters = deepcopy({**defaults, **definition.parameters})
    for name, default in defaults.items():
        try:
            if isinstance(default, bool):
                parameters[name] = _bool_parameter(definition, name, default)
            elif isinstance(default, (int, float)):
                parameters[name] = _float_parameter(definition, name, float(default))
            elif isinstance(default, list):
                parameters[name] = list(_string_list_parameter(definition, name))
        except ValueError:
            # The rule engine reports invalid parameters without aborting the analysis.
            continue
    return parameters


def _float_parameter(
    definition: RuleDefinition,
    name: str,
    default: float,
) -> float:
    raw_value = definition.parameters.get(
        name, _PARAMETER_DEFAULTS.get(definition.id, {}).get(name, default),
    )
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
        raise ValueError(f"Rule parameter {name!r} must be numeric.")
    try:
        value = float(raw_value)
    except OverflowError as exc:
        raise ValueError(f"Rule parameter {name!r} must be a finite, non-negative number.") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Rule parameter {name!r} must be a finite, non-negative number.")
    return value


def _string_list_parameter(definition: RuleDefinition, name: str) -> tuple[str, ...]:
    value = definition.parameters.get(
        name, _PARAMETER_DEFAULTS.get(definition.id, {}).get(name, ()),
    )
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise ValueError(f"Rule parameter {name!r} must be a list of strings.")
    values = tuple(str(item) for item in value)
    if any(not item for item in values):
        raise ValueError(f"Rule parameter {name!r} must not contain empty values.")
    return values


def _bool_parameter(definition: RuleDefinition, name: str, default: bool) -> bool:
    value = definition.parameters.get(
        name, _PARAMETER_DEFAULTS.get(definition.id, {}).get(name, default),
    )
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


def _channel_finding(
    report: AnalysisReport,
    definition: RuleDefinition,
    aov: str,
    channel: str,
    message: str,
    metrics: dict[str, object],
    predicate: Callable[[ChannelMetricSet], bool],
) -> Finding:
    samples = {
        path: channels[aov][channel]
        for path, channels in report.frame_channel_metrics.items()
        if aov in channels and channel in channels[aov] and predicate(channels[aov][channel])
    }
    affected = tuple(samples)
    if samples:
        metrics = {
            **metrics,
            "affected_frame_count": len(affected),
            "per_frame": {
                str(path): {
                    "nan_count": value.nan_count,
                    "posinf_count": value.posinf_count,
                    "neginf_count": value.neginf_count,
                    "negative_count": value.negative_count,
                    "min_value": value.min_value,
                    "max_value": value.max_value,
                    "pixel_count": value.pixel_count,
                }
                for path, value in samples.items()
            },
        }
    return Finding(
        rule_id=definition.id,
        severity=definition.severity,
        message=message,
        file=affected[0] if len(affected) == 1 else (None if affected else report.source),
        aov=aov,
        channel=channel,
        metrics=metrics,
        affected_files=affected,
    )


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
                _channel_finding(
                    report, definition, aov_name, channel_name,
                    "Non-finite channel values were detected.",
                    metrics={
                        "nan_count": metrics.nan_count,
                        "posinf_count": metrics.posinf_count,
                        "neginf_count": metrics.neginf_count,
                    },
                    predicate=lambda value: value.has_non_finite,
                )
            )
    channel_aovs = {finding.aov for finding in findings}
    for aov_name, aggregate_metrics in report.metrics_by_aov.items():
        if aov_name in channel_aovs:
            continue
        if not aggregate_metrics.has_non_finite or not _supports_aov(
            definition, aov_name, categories
        ):
            continue
        affected = tuple(
            path for path, aovs in report.frame_metrics.items()
            if aov_name in aovs and aovs[aov_name].has_non_finite
        )
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message="Non-finite pixel values were detected.",
                file=affected[0] if len(affected) == 1 else (None if affected else report.source),
                aov=aov_name,
                metrics={
                    "nan_count": aggregate_metrics.nan_count,
                    "posinf_count": aggregate_metrics.posinf_count,
                    "neginf_count": aggregate_metrics.neginf_count,
                },
                affected_files=affected,
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
                _channel_finding(
                    report, definition, aov_name, channel_name,
                    "Negative channel values were detected.",
                    metrics={
                        "negative_count": metrics.negative_count,
                        "min_value": metrics.min_value,
                    },
                    predicate=lambda value: value.negative_count > 0,
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
                _channel_finding(
                    report, definition, aov_name, channel_name,
                    "Finite channel values exceed the configured absolute limit.",
                    metrics={
                        "min_value": metrics.min_value,
                        "max_value": metrics.max_value,
                        "max_absolute": max_absolute,
                    },
                    predicate=lambda value: (
                        max(abs(value.min_value), abs(value.max_value)) > max_absolute
                    ),
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
        available = {
            name
            for descriptor in inspection.aovs
            for name in (descriptor.name, descriptor.original_name)
            if name is not None
        }
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
        available.update(channel for part in inspection.parts for channel in part.channels)
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


def _inspection_baselines(report: AnalysisReport) -> Iterable[tuple[FileInspection, FileInspection]]:
    """Compare numbered shots independently; comparison sets share one baseline."""

    if report.source_kind is SourceKind.NUMBERED_SEQUENCE and report.sequence_check.sequences:
        by_path = {inspection.path: inspection for inspection in report.inspections}
        groups = [
            [by_path[path] for path in sequence.files if path in by_path]
            for sequence in report.sequence_check.sequences
        ]
    else:
        groups = [list(report.inspections)]
    for inspections in groups:
        if inspections:
            for inspection in inspections[1:]:
                yield inspections[0], inspection


def _part_regions(inspection: FileInspection) -> dict[str, FileInspection | PartInspection]:
    if inspection.part_count == 1 or not inspection.parts:
        return {"primary": inspection}
    return {
        (
            part.aovs[0].name.split("::", 1)[0]
            if part.aovs else f"[part-index:{part.index}]"
        ): part
        for part in inspection.parts
    }


def validate_resolution_mismatch(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Check delivery windows for matching parts within each numbered shot."""

    findings: list[Finding] = []
    for baseline, inspection in _inspection_baselines(report):
        baseline_parts = _part_regions(baseline)
        for identity, part in _part_regions(inspection).items():
            baseline_part = baseline_parts.get(identity)
            if baseline_part is None:
                continue  # Missing/new parts belong to the structure rule.
            baseline_window = baseline_part.display_window or (
                (0, 0), (baseline_part.display_width - 1, baseline_part.display_height - 1)
            )
            window = part.display_window or (
                (0, 0), (part.display_width - 1, part.display_height - 1)
            )
            if window == baseline_window:
                continue
            findings.append(
                Finding(
                    rule_id=definition.id,
                    severity=definition.severity,
                    message=(
                        f"Display window {part.display_width}x{part.display_height} "
                        f"at {window[0]} differs from baseline "
                        f"{baseline_part.display_width}x{baseline_part.display_height} "
                        f"at {baseline_window[0]} (part {identity})."
                    ),
                    file=inspection.path,
                    metrics={
                        "part": identity,
                        "baseline_file": str(baseline.path),
                        "baseline_width": baseline_part.display_width,
                        "baseline_height": baseline_part.display_height,
                        "width": part.display_width,
                        "height": part.display_height,
                        "baseline_display_window": baseline_window,
                        "display_window": window,
                        "data_window": part.data_window,
                    },
                )
            )
    return findings


def _inspection_aov_signature(
    inspection: FileInspection,
) -> dict[str, tuple[str, tuple[str, ...], str | None]]:
    views = {part.index: part.view for part in inspection.parts}
    return {
        descriptor.name: (
            descriptor.category.value,
            tuple(sorted(descriptor.channels)),
            views.get(descriptor.part_index),
        )
        for descriptor in inspection.aovs
    }


def validate_aov_structure_mismatch(
    report: AnalysisReport,
    definition: RuleDefinition,
) -> list[Finding]:
    """Report frames whose AOV categories or channels change over time."""

    findings: list[Finding] = []
    for baseline, inspection in _inspection_baselines(report):
        baseline_signature = _inspection_aov_signature(baseline)
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
        RuleDefinition(
            id="technical_range",
            enabled=False,
            severity=Severity.WARNING,
            supported_aov_types=TECHNICAL_RANGE_CATEGORIES,
        ),
        RuleDefinition(id="missing_aov", enabled=False, severity=Severity.ERROR),
        RuleDefinition(id="missing_channels", enabled=False, severity=Severity.ERROR),
        RuleDefinition(id="resolution_mismatch", severity=Severity.ERROR),
        RuleDefinition(id="aov_structure_mismatch", severity=Severity.ERROR),
    )
