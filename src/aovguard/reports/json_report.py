"""Strict canonical JSON serialization for AOVGuard analysis results."""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

from aovguard.core.models import AnalysisOptions, AnalysisReport, FileInspection, Finding
from aovguard.core.status import analysis_status

SCHEMA_VERSION = "1.0"


def _json_safe(value: Any) -> Any:
    """Replace non-finite floats with null-compatible values recursively."""

    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _version() -> str:
    try:
        return metadata.version("aovguard")
    except metadata.PackageNotFoundError:
        return "unknown"


def _inspection_to_dict(inspection: FileInspection) -> dict[str, Any]:
    return {
        "path": str(inspection.path),
        "width": inspection.width,
        "height": inspection.height,
        "channels": list(inspection.channels),
        "aovs": [
            {
                "name": aov.name,
                "channels": list(aov.channels),
                "category": aov.category.value,
                "category_confidence": aov.category_confidence,
            }
            for aov in inspection.aovs
        ],
        "part_count": inspection.part_count,
        "is_deep": inspection.is_deep,
        "warnings": list(inspection.warnings),
    }


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    return {
        "rule_id": finding.rule_id,
        "severity": finding.severity.value,
        "message": finding.message,
        "file": str(finding.file) if finding.file is not None else None,
        "aov": finding.aov,
        "channel": finding.channel,
        "metrics": dict(finding.metrics),
        "affected_files": [str(path) for path in finding.affected_files],
    }


def _options_to_dict(options: AnalysisOptions | None) -> dict[str, Any] | None:
    if options is None:
        return None
    return {
        "preset_name": options.preset_name,
        "enabled_rules": list(options.enabled_rules or ()),
        "luminance_weights": list(options.luminance_weights),
        "non_black_threshold": options.non_black_threshold,
        "frame_pattern": options.frame_pattern,
        "recursive": options.recursive,
        "max_depth": options.max_depth,
        "allow_multiple_sequences": options.allow_multiple_sequences,
        "max_frames": options.max_frames,
        "expected_frame_range": (
            list(options.expected_frame_range) if options.expected_frame_range is not None else None
        ),
        "source_mode": options.source_mode.value,
        "aov_category_overrides": {
            name: category.value for name, category in options.aov_category_overrides.items()
        },
    }


def _aov_inventory(report: AnalysisReport) -> list[dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    for inspection in report.inspections:
        for descriptor in inspection.aovs:
            entry = inventory.setdefault(
                descriptor.name,
                {
                    "name": descriptor.name,
                    "category": descriptor.category.value,
                    "category_confidence": descriptor.category_confidence,
                    "channels": set(),
                    "files": set(),
                },
            )
            entry["channels"].update(descriptor.channels)
            entry["files"].add(str(inspection.path))
    return [
        {
            **entry,
            "channels": sorted(entry["channels"]),
            "files": sorted(entry["files"]),
        }
        for _name, entry in sorted(inventory.items(), key=lambda item: item[0].casefold())
    ]


def build_analysis_report_payload(
    report: AnalysisReport,
    *,
    options: AnalysisOptions | None = None,
) -> dict[str, Any]:
    """Build the canonical JSON payload for the new backend analysis report."""

    severity_summary: dict[str, int] = {}
    for finding in report.findings:
        key = finding.severity.value
        severity_summary[key] = severity_summary.get(key, 0) + 1
    category_summary: dict[str, int] = {}
    if report.inspections:
        for descriptor in report.inspections[0].aovs:
            key = descriptor.category.value
            category_summary[key] = category_summary.get(key, 0) + 1

    payload = {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "tool": "AOVGuard",
            "version": _version(),
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source": str(report.source),
            "source_kind": report.source_kind.value,
            "status": analysis_status(report).value,
            "frames_discovered": report.discovered_frame_count,
            "frames_processed": report.frame_count,
            "frames_failed": report.failed_frame_count,
            "aovs_detected": sum(category_summary.values()),
            "aovs_analyzed": len(report.metrics_by_aov),
            "color_aovs_analyzed": len(report.metrics_by_aov),
            "technical_aovs_diagnosed": report.technical_aov_count,
            "aovs_diagnosed": report.analyzed_aov_count,
            "summary_by_aov_category": category_summary,
            "rules_executed": list(report.rules_executed),
            "summary_by_severity": severity_summary,
            "options": _options_to_dict(options),
        },
        "frames": [str(frame) for frame in report.frames],
        "successful_frames": [str(frame) for frame in report.successful_frames],
        "failed_frames": [str(frame) for frame in report.failed_frames],
        "warnings": list(report.warnings),
        "sequence_check": {
            "expected_frame_range": (
                list(report.sequence_check.expected_frame_range)
                if report.sequence_check.expected_frame_range is not None else None
            ),
            "source": (
                str(report.sequence_check.source)
                if report.sequence_check.source is not None
                else None
            ),
            "summary": {
                "sequence_count": len(report.sequence_check.sequences),
                "unnumbered_file_count": len(report.sequence_check.unnumbered_files),
                "missing_frame_count": report.sequence_check.missing_frame_count,
                "duplicate_frame_count": report.sequence_check.duplicate_frame_count,
            },
            "sequences": [
                {
                    "directory": str(sequence.directory),
                    "pattern": sequence.pattern,
                    "prefix": sequence.prefix,
                    "suffix": sequence.suffix,
                    "padding": sequence.padding,
                    "padding_widths": list(sequence.padding_widths),
                    "start_frame": sequence.start_frame,
                    "end_frame": sequence.end_frame,
                    "frame_count": sequence.frame_count,
                    "frame_numbers": list(sequence.frame_numbers),
                    "missing_ranges": [list(item) for item in sequence.missing_ranges],
                    "unexpected_ranges": [list(item) for item in sequence.unexpected_ranges],
                    "missing_frame_count": sequence.missing_frame_count,
                    "duplicate_frames": list(sequence.duplicate_frames),
                    "files": [str(path) for path in sequence.files],
                }
                for sequence in report.sequence_check.sequences
            ],
            "unnumbered_files": [str(path) for path in report.sequence_check.unnumbered_files],
            "warnings": list(report.sequence_check.warnings),
        },
        "inspections": [_inspection_to_dict(inspection) for inspection in report.inspections],
        "aov_inventory": _aov_inventory(report),
        "metrics_by_aov": {
            name: asdict(metrics) for name, metrics in report.metrics_by_aov.items()
        },
        "channel_metrics_by_aov": {
            aov_name: {
                channel_name: asdict(metrics) for channel_name, metrics in channel_metrics.items()
            }
            for aov_name, channel_metrics in report.channel_metrics_by_aov.items()
        },
        "frame_metrics": {
            str(frame_path): {
                aov_name: asdict(metrics) for aov_name, metrics in aov_metrics.items()
            }
            for frame_path, aov_metrics in report.frame_metrics.items()
        },
        "series_metrics_by_aov": {
            aov_name: {
                "frame_count": metrics.frame_count,
                "median_luminance": metrics.median_luminance,
                "mad_luminance": metrics.mad_luminance,
                "min_luminance": metrics.min_luminance,
                "max_luminance": metrics.max_luminance,
                "max_frame_delta": metrics.max_frame_delta,
                "max_frame_delta_from": (
                    str(metrics.max_frame_delta_from)
                    if metrics.max_frame_delta_from is not None
                    else None
                ),
                "max_frame_delta_to": (
                    str(metrics.max_frame_delta_to)
                    if metrics.max_frame_delta_to is not None
                    else None
                ),
                "outlier_frames": [str(path) for path in metrics.outlier_frames],
            }
            for aov_name, metrics in report.series_metrics_by_aov.items()
        },
        "findings": [_finding_to_dict(finding) for finding in report.findings],
    }
    return _json_safe(payload)


def write_analysis_json(
    report: AnalysisReport,
    output_path: str | Path,
    *,
    options: AnalysisOptions | None = None,
) -> None:
    """Serialize a canonical strict JSON report to disk."""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_analysis_report_payload(report, options=options)
    output_path.write_text(
        json.dumps(payload, indent=2, allow_nan=False),
        encoding="utf-8",
    )
