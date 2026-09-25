"""Command-line entry points for analysis, inspection and report comparison."""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from aovguard.analysis_core import AOVResult, Thresholds, write_csv, write_json
from aovguard.config import load_thresholds, merge_threshold_overrides
from aovguard.core.analysis import analyze as analyze_backend
from aovguard.core.luminance import REC601, REC709, LuminanceWeights
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    FileInspection,
    SequenceCheckResult,
    Severity,
    SourceMode,
)
from aovguard.core.status import AnalysisStatus, analysis_status, severity_counts
from aovguard.discovery.frame_discovery import discover_frames
from aovguard.io.reader import OpenEXRReader
from aovguard.multilayer import analyze_multilayer, inspect_exr
from aovguard.reports.comparison import (
    ReportComparison,
    compare_report_files,
    write_comparison_json,
)
from aovguard.reports.html_report import write_analysis_html
from aovguard.reports.json_report import write_analysis_json
from aovguard.rules.builtin import default_rule_definitions
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.loader import load_rule_preset
from aovguard.sequence.sequence_checker import check_sequences, format_frame_ranges
from aovguard.simple import analyze_simple


def _print_results(
    results: list[AOVResult], input_folder: Path | None = None, total_frames: int | None = None
) -> None:
    if input_folder is not None:
        print(f"Input folder: {input_folder.resolve()}")
    if total_frames is not None:
        print(f"Frames found: {total_frames}")
    print(f"AOVs analyzed: {len(results)}")
    print("-" * 80)
    for result in results:
        print(
            f"{result.aov_name:20} | {result.classification:18} | "
            f"ratio={result.non_black_ratio:.5f} | "
            f"avg={result.avg_luminance:.6f} | "
            f"max={result.max_luminance:.6f}"
        )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", dest="json_path", default=None, help="Write a structured JSON report."
    )
    parser.add_argument(
        "--csv", dest="csv_path", default=None, help="Write a spreadsheet-friendly CSV report."
    )


def _add_threshold_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config",
        default=None,
        help="Optional .toml or .json config file with analysis thresholds.",
    )
    parser.add_argument("--empty-max-luminance", type=float, default=None)
    parser.add_argument("--empty-max-average", type=float, default=None)
    parser.add_argument("--nearly-empty-max-ratio", type=float, default=None)
    parser.add_argument("--nearly-empty-max-average", type=float, default=None)
    parser.add_argument("--review-max-ratio", type=float, default=None)
    parser.add_argument("--review-max-average", type=float, default=None)


def _add_backend_analysis_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", dest="json_path", default=None, help="Write the canonical JSON report."
    )
    parser.add_argument(
        "--html", dest="html_path", default=None, help="Write a readable HTML report."
    )
    parser.add_argument("--preset", default=None, help="Preset name to record in report metadata.")
    parser.add_argument(
        "--luminance-model",
        choices=("rec709", "rec601"),
        default="rec709",
        help="Built-in luminance model for color AOV metrics.",
    )
    parser.add_argument(
        "--luminance-weights",
        nargs=3,
        type=float,
        metavar=("R", "G", "B"),
        default=None,
        help="Custom RGB luminance weights. Overrides --luminance-model.",
    )
    parser.add_argument("--non-black-threshold", type=float, default=1e-5)
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Refuse analysis when discovery exceeds this positive frame limit.",
    )
    parser.add_argument(
        "--expected-frame-range",
        nargs=2,
        type=int,
        metavar=("START", "END"),
        default=None,
        help="Inclusive expected range for one numbered sequence (for example 1 800).",
    )
    parser.add_argument(
        "--source-mode",
        choices=tuple(mode.value for mode in SourceMode),
        default=SourceMode.AUTO.value,
        help="Interpret files automatically, as a numbered sequence, or as a comparison set.",
    )
    parser.add_argument(
        "--rules-config",
        default=None,
        help="Optional .toml or .json preset containing validation rules.",
    )
    _add_discovery_args(parser, include_multiple_sequence_policy=True)
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Return exit code 1 when the report status is WARNING.",
    )


def _add_discovery_args(
    parser: argparse.ArgumentParser,
    *,
    include_multiple_sequence_policy: bool = False,
) -> None:
    parser.add_argument(
        "--frame-pattern",
        default="*.exr",
        help="Filename pattern used to discover EXR frames (default: *.exr).",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Search direct and nested folders instead of using direct-first discovery.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=1,
        help="Maximum nested folder depth for --recursive (default: 1).",
    )
    if include_multiple_sequence_policy:
        parser.add_argument(
            "--allow-multiple-sequences",
            action="store_true",
            help="Allow analysis when discovery finds more than one numbered sequence.",
        )


def _thresholds_from_args(args: argparse.Namespace) -> Thresholds:
    base = load_thresholds(getattr(args, "config", None))
    return merge_threshold_overrides(
        base,
        empty_max_luminance=getattr(args, "empty_max_luminance", None),
        empty_max_average=getattr(args, "empty_max_average", None),
        nearly_empty_max_ratio=getattr(args, "nearly_empty_max_ratio", None),
        nearly_empty_max_average=getattr(args, "nearly_empty_max_average", None),
        review_max_ratio=getattr(args, "review_max_ratio", None),
        review_max_average=getattr(args, "review_max_average", None),
    )


def _count_simple_frames(folder: Path) -> int:
    direct = len(list(folder.glob("*.exr")))
    nested = len(list(folder.glob("*/*.exr")))
    return direct if direct else nested


def _count_multilayer_frames(folder: Path) -> int:
    return len(list(folder.glob("*.exr")))


def _options_from_backend_args(args: argparse.Namespace) -> AnalysisOptions:
    if args.luminance_weights is not None:
        weights = LuminanceWeights.from_values(args.luminance_weights)
    elif args.luminance_model == "rec601":
        weights = REC601
    else:
        weights = REC709

    return AnalysisOptions(
        preset_name=args.preset,
        luminance_weights=(weights.r, weights.g, weights.b),
        non_black_threshold=args.non_black_threshold,
        frame_pattern=args.frame_pattern,
        recursive=args.recursive,
        max_depth=args.max_depth,
        allow_multiple_sequences=args.allow_multiple_sequences,
        max_frames=args.max_frames,
        expected_frame_range=(
            tuple(args.expected_frame_range) if args.expected_frame_range is not None else None
        ),
        source_mode=SourceMode(args.source_mode),
    )


def _rules_from_backend_args(
    args: argparse.Namespace,
    options: AnalysisOptions,
) -> tuple[AnalysisOptions, tuple[RuleDefinition, ...]]:
    if args.rules_config:
        preset = load_rule_preset(args.rules_config)
        definitions = preset.rules
        preset_name = args.preset or preset.name
        category_overrides = preset.aov_category_overrides
    else:
        definitions = default_rule_definitions()
        preset_name = args.preset
        category_overrides = {}

    enabled_rules = tuple(definition.id for definition in definitions if definition.enabled)
    return (
        replace(
            options,
            preset_name=preset_name,
            enabled_rules=enabled_rules,
            aov_category_overrides=category_overrides,
        ),
        definitions,
    )


def _print_backend_report(report: AnalysisReport) -> None:
    counts = severity_counts(report)
    print(f"Input source: {Path(report.source).resolve()}")
    print(f"Status: {analysis_status(report).value.upper()}")
    print(f"Source interpretation: {report.source_kind.value}")
    print(f"Frames discovered: {report.discovered_frame_count}")
    print(f"Frames processed: {report.frame_count}")
    print(f"Frames failed: {report.failed_frame_count}")
    print(f"Color AOVs analyzed: {len(report.metrics_by_aov)}")
    print(f"Technical AOVs diagnosed: {report.technical_aov_count}")
    print(
        "Findings: "
        f"{counts[Severity.ERROR]} errors, "
        f"{counts[Severity.WARNING]} warnings, "
        f"{counts[Severity.INFO]} info"
    )
    _print_sequence_check(report.sequence_check)
    if report.warnings:
        print("Warnings:")
        for warning in report.warnings:
            print(f"  - {warning}")
    print("-" * 80)
    for name, metrics in report.metrics_by_aov.items():
        print(
            f"{name:20} | "
            f"ratio={metrics.non_black_ratio:.5f} | "
            f"avg={metrics.avg_luminance:.6f} | "
            f"max={metrics.max_luminance:.6f} | "
            f"nan={metrics.nan_count} | "
            f"+inf={metrics.posinf_count} | "
            f"-inf={metrics.neginf_count}"
        )
    if report.findings:
        print("")
        print("Findings:")
        for finding in report.findings:
            target = finding.aov or finding.channel or finding.file or report.source
            print(f"  [{finding.severity.value}] {finding.rule_id}: {target} - {finding.message}")


def _print_sequence_check(result: SequenceCheckResult) -> None:
    print(f"Sequences detected: {len(result.sequences)}")
    if result.expected_frame_range is not None:
        print(
            "Expected frame range: "
            f"{result.expected_frame_range[0]}-{result.expected_frame_range[1]}"
        )
    for sequence in result.sequences:
        frame_range = (
            f"{sequence.start_frame}-{sequence.end_frame}"
            if sequence.start_frame != sequence.end_frame
            else str(sequence.start_frame)
        )
        missing = format_frame_ranges(sequence.missing_ranges) or "none"
        duplicates = ", ".join(map(str, sequence.duplicate_frames)) or "none"
        print(
            f"  {sequence.pattern} | range={frame_range} | present={sequence.frame_count} | "
            f"missing={missing} | duplicates={duplicates}"
        )
        if sequence.unexpected_ranges:
            print(f"  Outside expected range: {format_frame_ranges(sequence.unexpected_ranges)}")
    if result.unnumbered_files:
        print(f"Unnumbered EXRs: {len(result.unnumbered_files)}")


def _print_structure(inspection: FileInspection) -> None:
    print(f"EXR file: {Path(inspection.path).resolve()}")
    print(f"Size: {inspection.width}x{inspection.height}")
    print(f"Parts: {inspection.part_count}")
    print(f"Deep: {inspection.is_deep}")
    print("")
    print("Channels:")
    for channel in inspection.channels:
        print(f"  - {channel}")
    print("")
    print("Detected AOVs:")
    for aov in inspection.aovs:
        channel_list = ", ".join(aov.channels)
        print(f"  - {aov.name}: {aov.category.value} ({aov.category_confidence}) [{channel_list}]")
    if inspection.warnings:
        print("")
        print("Warnings:")
        for warning in inspection.warnings:
            print(f"  - {warning}")


def _print_report_comparison(comparison: ReportComparison) -> None:
    print(f"Baseline: {comparison.baseline_source}")
    print(f"Candidate: {comparison.candidate_source}")
    print(f"Status: {comparison.baseline_status} -> {comparison.candidate_status}")
    print(f"AOVs changed: {comparison.changed_aov_count}")
    print(f"New findings: {len(comparison.new_findings)}")
    print(f"Resolved findings: {len(comparison.resolved_findings)}")
    print("-" * 80)
    for delta in comparison.metric_deltas:
        print(
            f"{delta.aov:20} | {delta.status:9} | "
            f"avg={delta.average_luminance_delta!s:>12} | "
            f"ratio={delta.non_black_ratio_delta!s:>12} | "
            f"max={delta.max_luminance_delta!s:>12}"
        )


def main(argv: list[str] | None = None) -> int:
    """Run the AOVGuard CLI and return its process-style exit code."""

    parser = argparse.ArgumentParser(
        prog="aovguard",
        description="Validate EXR light AOVs and report empty, near-empty, or review-worthy passes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="Analyze EXR files using automatic structure inspection.")
    p.add_argument("source")
    _add_backend_analysis_args(p)

    p = sub.add_parser(
        "inspect-structure", help="Inspect EXR structure using the new backend inspector."
    )
    p.add_argument("path")

    p = sub.add_parser(
        "check-sequence", help="Check EXR filename sequences without decoding pixels."
    )
    p.add_argument("source")
    _add_discovery_args(p)
    p.add_argument(
        "--expected-frame-range", nargs=2, type=int, metavar=("START", "END")
    )

    p = sub.add_parser(
        "compare-reports",
        help="Compare two canonical AOVGuard JSON analysis reports.",
    )
    p.add_argument("baseline")
    p.add_argument("candidate")
    p.add_argument("--json", dest="json_path", default=None)
    p.add_argument("--tolerance", type=float, default=1e-12)

    p = sub.add_parser("analyze-simple", help="Analyze simple RGB/RGBA EXR files in one folder.")
    p.add_argument("input_folder")
    _add_output_args(p)
    _add_threshold_args(p)

    p = sub.add_parser("inspect", help="List channels and RGB AOV groups in one EXR file.")
    p.add_argument("path")

    p = sub.add_parser("analyze-multilayer", help="Analyze multilayer EXR files in one folder.")
    p.add_argument("input_folder")
    _add_output_args(p)
    _add_threshold_args(p)

    args = parser.parse_args(argv)

    if args.command == "analyze":
        try:
            options = _options_from_backend_args(args)
            options, rule_definitions = _rules_from_backend_args(args, options)
            reader = OpenEXRReader(options.aov_category_overrides)
            report = analyze_backend(
                Path(args.source),
                options,
                reader,
                rule_definitions=rule_definitions,
            )
        except Exception as exc:
            parser.exit(1, f"aovguard analyze: error: {exc}\n")
        _print_backend_report(report)
        if args.json_path:
            write_analysis_json(report, args.json_path, options=options)
            print(f"JSON report written to: {args.json_path}")
        if args.html_path:
            write_analysis_html(report, args.html_path, options=options)
            print(f"HTML report written to: {args.html_path}")
        status = analysis_status(report)
        if status is AnalysisStatus.FAIL:
            return 1
        if status is AnalysisStatus.WARNING and args.fail_on_warning:
            return 1
        return 0

    if args.command == "inspect-structure":
        reader = OpenEXRReader()
        try:
            inspection = reader.inspect(Path(args.path))
        except Exception as exc:
            parser.exit(1, f"aovguard inspect-structure: error: {exc}\n")
        _print_structure(inspection)
        return 0

    if args.command == "check-sequence":
        try:
            discovery = discover_frames(
                Path(args.source),
                pattern=args.frame_pattern,
                recursive=args.recursive,
                max_depth=args.max_depth,
            )
            if not discovery.frames:
                raise FileNotFoundError(f"No EXR files found in {discovery.source}")
            result = check_sequences(
                discovery.frames,
                source=discovery.source,
                expected_frame_range=(
                    tuple(args.expected_frame_range)
                    if args.expected_frame_range is not None else None
                ),
            )
        except Exception as exc:
            parser.exit(1, f"aovguard check-sequence: error: {exc}\n")
        _print_sequence_check(result)
        for warning in discovery.warnings + result.warnings:
            print(f"Warning: {warning}")
        return (
            1
            if args.expected_frame_range is not None
            and (
                result.missing_frame_count
                or any(sequence.unexpected_ranges for sequence in result.sequences)
            )
            else 0
        )

    if args.command == "compare-reports":
        try:
            comparison = compare_report_files(
                args.baseline,
                args.candidate,
                tolerance=args.tolerance,
            )
        except Exception as exc:
            parser.exit(1, f"aovguard compare-reports: error: {exc}\n")
        _print_report_comparison(comparison)
        if args.json_path:
            write_comparison_json(comparison, args.json_path)
            print(f"Comparison JSON written to: {args.json_path}")
        return 0

    if args.command == "analyze-simple":
        folder = Path(args.input_folder)
        thresholds = _thresholds_from_args(args)
        results = analyze_simple(folder, thresholds=thresholds)
        total_frames = _count_simple_frames(folder)
        _print_results(results, input_folder=folder, total_frames=total_frames)
        if args.json_path:
            write_json(
                results,
                args.json_path,
                input_folder=folder,
                mode="simple",
                thresholds=thresholds,
                frames_analyzed=total_frames,
            )
            print(f"JSON report written to: {args.json_path}")
        if args.csv_path:
            write_csv(results, args.csv_path)
            print(f"CSV report written to: {args.csv_path}")
        return 0

    if args.command == "inspect":
        print(inspect_exr(args.path))
        return 0

    if args.command == "analyze-multilayer":
        folder = Path(args.input_folder)
        thresholds = _thresholds_from_args(args)
        total_frames = _count_multilayer_frames(folder)
        results = analyze_multilayer(folder, thresholds=thresholds)
        _print_results(results, input_folder=folder, total_frames=total_frames)
        if args.json_path:
            write_json(
                results,
                args.json_path,
                input_folder=folder,
                mode="multilayer",
                thresholds=thresholds,
                frames_analyzed=total_frames,
            )
            print(f"JSON report written to: {args.json_path}")
        if args.csv_path:
            write_csv(results, args.csv_path)
            print(f"CSV report written to: {args.csv_path}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2
