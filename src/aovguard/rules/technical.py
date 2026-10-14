"""Opt-in numeric range policies for explicitly named technical AOVs."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from aovguard.core.models import AnalysisReport, AOVCategory, ChannelMetricSet, Finding
from aovguard.rules.definitions import RuleDefinition

TECHNICAL_RANGE_CATEGORIES = frozenset(
    {
        AOVCategory.DEPTH,
        AOVCategory.MASK,
        AOVCategory.SCALAR,
        AOVCategory.VECTOR,
    }
)


def _finite_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number.")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")
    return number


def technical_range_parameters(definition: RuleDefinition) -> dict[str, dict[str, float]]:
    """Validate exact AOV targets and inclusive bounds, adding zero tolerance.

    At least one signed finite bound is required per AOV. Tolerance is an
    absolute non-negative allowance in channel units, not a percentage.
    """

    if set(definition.parameters) - {"ranges"}:
        raise ValueError("technical_range accepts only the 'ranges' parameter.")
    raw_ranges = definition.parameters.get("ranges")
    if not isinstance(raw_ranges, Mapping) or not raw_ranges:
        raise ValueError(
            "technical_range requires a non-empty 'ranges' table keyed by exact AOV name."
        )
    ranges: dict[str, dict[str, float]] = {}
    for name, raw in raw_ranges.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Range targets must be non-empty exact AOV names.")
        if not isinstance(raw, Mapping) or set(raw) - {"min", "max", "tolerance"}:
            raise ValueError(
                f"Range for {name!r} must be a table containing min, max or tolerance."
            )
        if "min" not in raw and "max" not in raw:
            raise ValueError(f"Range for {name!r} requires at least one of min or max.")
        bounds = {key: _finite_number(value, f"{name!r}.{key}") for key, value in raw.items()}
        tolerance = bounds.setdefault("tolerance", 0.0)
        if tolerance < 0:
            raise ValueError(f"Tolerance for {name!r} must be non-negative.")
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise ValueError(f"Range for {name!r} must have min <= max.")
        for key, direction in (("min", -1), ("max", 1)):
            if key in bounds and not math.isfinite(bounds[key] + direction * tolerance):
                raise ValueError(f"Range plus tolerance for {name!r} must remain finite.")
        ranges[name] = bounds
    return ranges


def _outside(metrics: ChannelMetricSet, bounds: Mapping[str, float]) -> bool:
    finite_count = (
        metrics.pixel_count - metrics.nan_count - metrics.posinf_count - metrics.neginf_count
    )
    if finite_count <= 0:
        return False
    tolerance = bounds["tolerance"]
    return (
        "min" in bounds
        and math.isfinite(metrics.min_value)
        and metrics.min_value < bounds["min"] - tolerance
    ) or (
        "max" in bounds
        and math.isfinite(metrics.max_value)
        and metrics.max_value > bounds["max"] + tolerance
    )


def validate_technical_range(report: AnalysisReport, definition: RuleDefinition) -> list[Finding]:
    """Check every component of named technical AOVs using per-frame extrema.

    No pixels are reread and no out-of-range pixel count is inferred. NaN/Inf
    remain the responsibility of the independent integrity rule. Names are
    exact, including multipart namespaces, and unobserved targets are errors
    rather than silently passing a misspelled or unqualified policy.
    """

    ranges = technical_range_parameters(definition)
    categories: dict[tuple[Path, str], AOVCategory] = {}
    observed: set[str] = set()
    for inspection in report.inspections:
        for aov in inspection.aovs:
            if aov.name not in ranges:
                continue
            observed.add(aov.name)
            if aov.category not in TECHNICAL_RANGE_CATEGORIES:
                raise ValueError(
                    f"Range target {aov.name!r} in {inspection.path} has category "
                    f"{aov.category.value!r}; expected depth, mask, scalar or vector. "
                    "Review the preset classification before applying a range."
                )
            categories[inspection.path, aov.name] = aov.category
    missing = sorted(set(ranges) - observed)
    if missing:
        raise ValueError(f"No inspected AOV exactly matches range target(s): {', '.join(missing)}.")

    samples: dict[tuple[str, str], dict[Path, ChannelMetricSet]] = {}
    for path, aovs in report.frame_channel_metrics.items():
        for name, channels in aovs.items():
            if name not in ranges:
                continue
            category = categories.get((path, name))
            if category is None:
                raise ValueError(
                    f"Missing inspection category for range target {name!r} in {path}."
                )
            if definition.supported_aov_types and category not in definition.supported_aov_types:
                continue
            for channel, metrics in channels.items():
                if _outside(metrics, ranges[name]):
                    samples.setdefault((name, channel), {})[path] = metrics

    findings: list[Finding] = []
    for (name, channel), affected in sorted(samples.items()):
        paths = tuple(affected)
        findings.append(
            Finding(
                rule_id=definition.id,
                severity=definition.severity,
                message="Finite technical channel values fall outside the configured inclusive range.",
                file=paths[0] if len(paths) == 1 else None,
                aov=name,
                channel=channel,
                affected_files=paths,
                metrics={
                    "expected_min": ranges[name].get("min"),
                    "expected_max": ranges[name].get("max"),
                    "tolerance": ranges[name]["tolerance"],
                    "affected_frame_count": len(paths),
                    "per_frame": {
                        str(path): {
                            "min_value": metrics.min_value,
                            "max_value": metrics.max_value,
                            "pixel_count": metrics.pixel_count,
                            "finite_count": (
                                metrics.pixel_count
                                - metrics.nan_count
                                - metrics.posinf_count
                                - metrics.neginf_count
                            ),
                        }
                        for path, metrics in affected.items()
                    },
                },
            )
        )
    return findings
