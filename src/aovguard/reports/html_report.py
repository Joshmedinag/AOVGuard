"""Self-contained HTML report generation from canonical analysis results."""

from __future__ import annotations

import html
from collections.abc import Iterable
from importlib import metadata
from pathlib import Path

from aovguard.core.findings import finding_recommendation
from aovguard.core.memory import MIB_BYTES
from aovguard.core.models import AnalysisOptions, AnalysisReport, Finding, Severity
from aovguard.core.status import analysis_status, severity_counts
from aovguard.io.inspector import RGB_SUFFIXES
from aovguard.io.output import atomic_text_writer
from aovguard.sequence.sequence_checker import format_frame_ranges


def _cell(value: object) -> str:
    return html.escape(str(value))


def _finding_source_label(finding: Finding) -> object:
    if finding.file is not None:
        return finding.file
    if finding.affected_files:
        count = len(finding.affected_files)
        return f"{count} file{'s' if count != 1 else ''}"
    return "Selected source"


def _finding_source_html(finding: Finding) -> str:
    if len(finding.affected_files) > 1:
        paths = "".join(f"<li>{_cell(path)}</li>" for path in finding.affected_files)
        return f"<details><summary>{len(finding.affected_files)} files</summary><ul>{paths}</ul></details>"
    return _cell(_finding_source_label(finding))


def _version() -> str:
    try:
        return metadata.version("aovguard")
    except metadata.PackageNotFoundError:
        return "unknown"


def _finding_interpretation(finding: Finding) -> str:
    if finding.rule_id in {"empty_aov", "near_empty_aov"}:
        return "Review: may be intentional"
    if finding.severity is Severity.ERROR:
        return "Action required"
    if finding.severity is Severity.WARNING:
        return "Review required"
    return "Diagnostic information"


def build_analysis_html(
    report: AnalysisReport,
    *,
    options: AnalysisOptions | None = None,
) -> str:
    """Build a self-contained escaped HTML analysis report."""

    status = analysis_status(report)
    status_class = f"status-{status.value}"
    counts = severity_counts(report)
    part_rows = [
        "<tr>"
        f"<td>{_cell(inspection.path)}</td>"
        f"<td>{part.index}</td><td>{_cell(part.name or '(unnamed)')}</td>"
        f"<td>{_cell(part.view or '-')}</td>"
        f"<td>{part.width}x{part.height}<br>{_cell(part.data_window)}</td>"
        f"<td>{part.display_width}x{part.display_height}<br>{_cell(part.display_window)}</td>"
        f"<td>{_cell(', '.join(part.channels))}</td>"
        "</tr>"
        for inspection in report.inspections
        for part in inspection.parts
    ]
    sequence_rows = []
    for sequence in report.sequence_check.sequences:
        frame_range = (
            f"{sequence.start_frame}-{sequence.end_frame}"
            if sequence.start_frame != sequence.end_frame
            else str(sequence.start_frame)
        )
        sequence_issues = (
            sequence.missing_frame_count
            + len(sequence.unexpected_ranges)
            + len(sequence.duplicate_frames)
            + max(0, len(sequence.padding_widths) - 1)
        )
        sequence_status = "REVIEW" if sequence_issues else "COMPLETE"
        sequence_rows.append(
            "<tr>"
            f'<td><strong class="sequence-{sequence_status.lower()}">{sequence_status}</strong></td>'
            f"<td>{_cell(sequence.pattern)}</td>"
            f"<td>{_cell(sequence.directory)}</td>"
            f"<td>{_cell(frame_range)}</td>"
            f"<td>{sequence.frame_count}</td>"
            f"<td>{_cell(format_frame_ranges(sequence.missing_ranges) or '-')}</td>"
            f"<td>{_cell(format_frame_ranges(sequence.unexpected_ranges) or '-')}</td>"
            f"<td>{_cell(', '.join(map(str, sequence.duplicate_frames)) or '-')}</td>"
            "</tr>"
        )
    metric_rows = []
    categories = {
        descriptor.name: descriptor.category.value
        for inspection in report.inspections
        for descriptor in inspection.aovs
    }
    channels = {
        descriptor.name: ", ".join(descriptor.channels)
        for inspection in report.inspections
        for descriptor in inspection.aovs
    }
    for name, metrics in report.metrics_by_aov.items():
        series = report.series_metrics_by_aov.get(name)
        median = f"{series.median_luminance:.6f}" if series else "-"
        mad = f"{series.mad_luminance:.6f}" if series else "-"
        outliers = len(series.outlier_frames) if series else 0
        metric_rows.append(
            "<tr>"
            f"<td>{_cell(name)}</td>"
            f"<td>{_cell(categories.get(name, 'unknown'))}</td>"
            f"<td>{_cell(channels.get(name, '-'))}</td>"
            f"<td>{metrics.non_black_ratio:.5f}</td>"
            f"<td>{metrics.avg_luminance:.6f}</td>"
            f"<td>{metrics.max_luminance:.6f}</td>"
            f"<td>{median}</td>"
            f"<td>{mad}</td>"
            f"<td>{outliers}</td>"
            f"<td>{metrics.nan_count + metrics.posinf_count + metrics.neginf_count}</td>"
            "</tr>"
        )
    technical_rows = [
        "<tr>"
        f"<td>{_cell(aov_name)}</td>"
        f"<td>{_cell(categories.get(aov_name, 'unknown'))}</td>"
        f"<td>{_cell(channel_name)}</td>"
        f"<td>{metrics.min_value:.6f}</td>"
        f"<td>{metrics.avg_value:.6f}</td>"
        f"<td>{metrics.max_value:.6f}</td>"
        f"<td>{metrics.nan_count + metrics.posinf_count + metrics.neginf_count}</td>"
        f"<td>{metrics.negative_count}</td>"
        "</tr>"
        for aov_name, channel_metrics in report.channel_metrics_by_aov.items()
        for channel_name, metrics in channel_metrics.items()
        if (
            aov_name not in report.metrics_by_aov
            or channel_name.split("::")[-1].rsplit(".", 1)[-1].casefold() not in RGB_SUFFIXES
        )
    ]
    frame_metric_rows = [
        "<tr>"
        f"<td>{_cell(frame_path)}</td>"
        f"<td>{_cell(aov_name)}</td>"
        f"<td>{metrics.non_black_ratio:.5f}</td>"
        f"<td>{metrics.avg_luminance:.6f}</td>"
        f"<td>{metrics.max_luminance:.6f}</td>"
        f"<td>{metrics.nan_count + metrics.posinf_count + metrics.neginf_count}</td>"
        "</tr>"
        for frame_path, aov_metrics in report.frame_metrics.items()
        for aov_name, metrics in aov_metrics.items()
    ]
    finding_rows = [
        "<tr>"
        f'<td><span class="severity severity-{finding.severity.value}">{finding.severity.value.upper()}</span></td>'
        f"<td>{_cell(finding.rule_id)}</td>"
        f"<td>{_cell(finding.aov or '-')}<br>{_cell(finding.channel or '-')}</td>"
        f"<td>{_cell(finding.message)}</td>"
        f"<td>{_cell(finding_recommendation(finding))}</td>"
        f"<td>{_cell(_finding_interpretation(finding))}</td>"
        f"<td>{_finding_source_html(finding)}</td>"
        "</tr>"
        for finding in report.findings
    ]
    warnings = "".join(f"<li>{_cell(warning)}</li>" for warning in report.warnings)
    preset = options.preset_name if options and options.preset_name else "Default rules"
    luminance = (
        ", ".join(f"{value:.6g}" for value in options.luminance_weights)
        if options
        else "Not recorded"
    )
    frame_limit = options.max_frames if options and options.max_frames else "Unlimited"
    memory_limit = options.max_memory_mb if options is not None else None
    memory_budget = (
        f"{memory_limit:g} MiB" if memory_limit is not None
        else "Unlimited" if options is not None else "Not recorded"
    )
    memory_rows = []
    for path, estimate in report.memory_estimates.items():
        if memory_limit is None:
            decision = "Not gated" if options is not None else "Budget not recorded"
        else:
            numerator, denominator = memory_limit.as_integer_ratio()
            exceeds_budget = estimate.estimated_bytes * denominator > numerator * MIB_BYTES
            decision = "Blocked by estimate budget" if exceeds_budget else "Within estimate budget"
        memory_rows.append(
            "<tr>"
            f"<td>{_cell(path)}</td><td>{estimate.estimated_mib:.2f}</td>"
            f"<td>{_cell(memory_budget)}</td><td>{_cell(decision)}</td>"
            f"<td>{_cell(estimate.model_version)}</td>"
            "</tr>"
        )
    expected_range = (
        f"{report.sequence_check.expected_frame_range[0]}-"
        f"{report.sequence_check.expected_frame_range[1]}"
        if report.sequence_check.expected_frame_range is not None else "Not set"
    )
    execution_mode = (
        "Isolated frame worker" if options and options.isolate_frames
        else "In process" if options is not None else "Not recorded"
    )
    frame_timeout = (
        f"{options.frame_timeout_seconds:g} s" if options and options.frame_timeout_seconds is not None
        else "No frame timeout" if options is not None else "Not recorded"
    )
    execution_rows = []
    for path, record in report.frame_execution.items():
        timeout = (
            f"{record.timeout_seconds:g} s" if record.timeout_seconds is not None else "None"
        )
        elapsed = f"{record.elapsed_seconds:.3f}" if record.elapsed_seconds is not None else "-"
        execution_rows.append(
            "<tr>"
            f"<td>{_cell(path)}</td><td>{_cell(record.mode)}</td><td>{_cell(record.status)}</td>"
            f"<td>{_cell(timeout)}</td><td>{_cell(elapsed)}</td>"
            f"<td>{_cell(record.worker_pid if record.worker_pid is not None else '-')}</td>"
            f"<td>{_cell(record.exit_code if record.exit_code is not None else '-')}</td>"
            f"<td>{_cell(record.stage)}</td>"
            "</tr>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AOVGuard Analysis Report</title>
  <style>
    :root {{ color-scheme: light; --line:#d7dce2; --muted:#5d6670; --surface:#f6f7f8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; color:#18202a; background:#fff; font:14px/1.45 "Segoe UI", Arial, sans-serif; }}
    header {{ padding:24px 32px; border-bottom:1px solid var(--line); background:#202833; color:#fff; }}
    h1 {{ margin:0 0 4px; font-size:24px; letter-spacing:0; }}
    h2 {{ margin:28px 0 10px; font-size:17px; letter-spacing:0; }}
    main {{ max-width:1400px; margin:0 auto; padding:20px 32px 40px; }}
    .source {{ color:#dbe2ea; overflow-wrap:anywhere; }}
    .summary {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; }}
    .metric {{ border:1px solid var(--line); padding:12px; background:var(--surface); border-radius:4px; }}
    .metric strong {{ display:block; margin-top:3px; font-size:20px; }}
    .status {{ display:inline-block; margin-top:12px; padding:5px 10px; border-radius:4px; font-weight:700; }}
    .status-pass {{ background:#d7f2df; color:#145c2c; }}
    .status-warning {{ background:#fff0bd; color:#704f00; }}
    .status-fail {{ background:#ffdcdc; color:#8b1e1e; }}
    table {{ width:100%; border-collapse:collapse; font-size:13px; }}
    th,td {{ padding:8px 9px; border:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ background:#eef1f4; white-space:nowrap; }}
    tbody tr:nth-child(even) {{ background:#fafbfc; }}
    .severity {{ font-weight:700; }}
    .severity-error {{ color:#a11f1f; }} .severity-warning {{ color:#795600; }} .severity-info {{ color:#1c5c8f; }}
    .empty {{ color:var(--muted); font-style:italic; }}
    .sequence-complete {{ color:#145c2c; }} .sequence-review {{ color:#8b1e1e; }}
    footer {{ margin-top:32px; color:var(--muted); }}
  </style>
</head>
<body>
<header>
  <h1>AOVGuard Analysis Report</h1>
  <div class="source">{_cell(report.source)}</div>
  <div class="source">Source interpretation: {_cell(report.source_kind.value)}</div>
  <span class="status {status_class}">{status.value.upper()}</span>
</header>
<main>
  <section class="summary">
    <div class="metric">Frames discovered<strong>{report.discovered_frame_count}</strong></div>
    <div class="metric">Frames processed<strong>{report.frame_count}</strong></div>
    <div class="metric">Frames failed<strong>{report.failed_frame_count}</strong></div>
    <div class="metric">Color AOVs<strong>{len(report.metrics_by_aov)}</strong></div>
    <div class="metric">Technical AOVs<strong>{report.technical_aov_count}</strong></div>
    <div class="metric">Errors<strong>{counts[Severity.ERROR]}</strong></div>
    <div class="metric">Warnings<strong>{counts[Severity.WARNING]}</strong></div>
  </section>
  <h2>Configuration</h2>
  <p>Version: <strong>{_cell(_version())}</strong> &middot;
  Preset: <strong>{_cell(preset)}</strong> &middot;
  Luminance RGB weights: <strong>{_cell(luminance)}</strong> &middot;
  Frame limit: <strong>{_cell(frame_limit)}</strong> &middot;
  Memory estimate budget: <strong>{_cell(memory_budget)}</strong> &middot;
  Frame execution: <strong>{_cell(execution_mode)}</strong> &middot;
  Frame service timeout: <strong>{_cell(frame_timeout)}</strong> &middot;
  Expected frame range: <strong>{_cell(expected_range)}</strong></p>
  <p>Pixel statistics measure the stored data window. Delivery consistency uses the display window, including its origin.</p>
  {f"<h2>Warnings</h2><ul>{warnings}</ul>" if warnings else ""}
  <h2>Pre-decode Memory Estimates</h2>
  <p>MiB means 1,048,576 bytes. These conservative per-frame estimates gate pixel decoding;
  they are not a hard operating-system memory limit or a guarantee of process peak RSS.
  A frame within the estimate budget may still require more memory at runtime.</p>
  <table><thead><tr><th>File</th><th>Estimated MiB</th><th>Budget</th><th>Estimate decision</th><th>Model</th></tr></thead>
  <tbody>{"".join(memory_rows) or '<tr><td colspan="5" class="empty">No pre-decode memory estimates recorded.</td></tr>'}</tbody></table>
  <h2>Frame Execution Diagnostics</h2>
  <p>Isolated execution uses a frame worker process, not a security sandbox or a hard RSS cap.
  The frame-service deadline starts after worker readiness and includes header inspection,
  memory admission, decoding, reductions and result transfer.
  Startup and termination cleanup use separate waits; recorded elapsed time can include
  startup, frame service and cleanup.
  Discovery, final rule evaluation, export and standalone inspection remain in the parent
  outside this frame-service deadline. Unconfirmed worker cleanup is fatal: the job stops
  instead of silently reusing the executor. Bounded waits do not guarantee OS termination
  of an unkillable process.
  In-process native reads cannot be interrupted. Worker PIDs/times are execution
  diagnostics, not numeric-analysis or baseline-finding evidence.</p>
  <table><thead><tr><th>File</th><th>Mode</th><th>Status</th><th>Timeout</th><th>Elapsed seconds</th><th>Worker PID</th><th>Exit code</th><th>Stage</th></tr></thead>
  <tbody>{"".join(execution_rows) or '<tr><td colspan="8" class="empty">No per-frame execution diagnostics recorded.</td></tr>'}</tbody></table>
  <h2>EXR Parts</h2>
  <table><thead><tr><th>File</th><th>Index</th><th>Name</th><th>View</th><th>Stored pixels / data window</th><th>Delivery / display window</th><th>Source channels</th></tr></thead>
  <tbody>{"".join(part_rows) or '<tr><td colspan="7" class="empty">No per-part metadata recorded.</td></tr>'}</tbody></table>
  <h2>Sequences</h2>
  <table><thead><tr><th>Status</th><th>Pattern</th><th>Directory</th><th>Range</th><th>Present</th><th>Missing</th><th>Outside expected</th><th>Duplicates</th></tr></thead>
  <tbody>{"".join(sequence_rows) or '<tr><td colspan="8" class="empty">No numbered sequence detected.</td></tr>'}</tbody></table>
  <h2>AOV Metrics</h2>
  <table><thead><tr><th>AOV</th><th>Category</th><th>Channels analyzed</th><th>Non-black ratio</th><th>Average luminance</th><th>Maximum luminance</th><th>Median</th><th>MAD</th><th>Outliers</th><th>Non-finite values</th></tr></thead>
  <tbody>{"".join(metric_rows) or '<tr><td colspan="10" class="empty">No AOV metrics available.</td></tr>'}</tbody></table>
  <h2>Technical AOV Diagnostics</h2>
  <table><thead><tr><th>AOV</th><th>Category</th><th>Channel</th><th>Minimum</th><th>Average</th><th>Maximum</th><th>Non-finite values</th><th>Negative values</th></tr></thead>
  <tbody>{"".join(technical_rows) or '<tr><td colspan="8" class="empty">No technical AOV diagnostics available.</td></tr>'}</tbody></table>
  <h2>Per-frame Diagnostics</h2>
  <table><thead><tr><th>File</th><th>AOV</th><th>Non-black ratio</th><th>Average luminance</th><th>Maximum luminance</th><th>Non-finite values</th></tr></thead>
  <tbody>{"".join(frame_metric_rows) or '<tr><td colspan="6" class="empty">No per-frame metrics available.</td></tr>'}</tbody></table>
  <h2>Findings</h2>
  <table><thead><tr><th>Severity</th><th>Rule</th><th>Target</th><th>Message</th><th>Recommendation</th><th>Interpretation</th><th>File</th></tr></thead>
  <tbody>{"".join(finding_rows) or '<tr><td colspan="7" class="empty">No findings.</td></tr>'}</tbody></table>
  <footer>Generated by AOVGuard. JSON remains the canonical machine-readable report.</footer>
</main>
</body>
</html>
"""


def write_analysis_html(
    report: AnalysisReport,
    output_path: str | Path,
    *,
    options: AnalysisOptions | None = None,
    protected_paths: Iterable[str | Path] = (),
) -> None:
    """Atomically publish HTML, protecting frames and caller-supplied inputs."""

    document = build_analysis_html(report, options=options)
    with atomic_text_writer(
        output_path, protected_paths=(report.source, *report.frames, *protected_paths),
    ) as handle:
        handle.write(document)
