"""Verify the real Qt sequence workflow against a canonical CLI baseline.

Qt is optional until verification starts. The workflow uses an isolated settings
file and automated dialogs, while analysis, Qt threads, worker processes,
navigation, baseline comparison and report exports use the real application.
Screenshots document automated acceptance, not participant usability research.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import multiprocessing
import os
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping, Sequence
from dataclasses import fields
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

if TYPE_CHECKING:
    from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

    from aovguard.core.models import AnalysisOptions
    from aovguard.ui import MainWindow


class VerificationError(RuntimeError):
    """The requested workflow could not be verified without changing its meaning."""


def require(condition: bool, message: str) -> None:
    """Enforce acceptance requirements even when Python runs with optimization."""

    if not condition:
        raise VerificationError(message)


def stable_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only generation time, execution PID and execution duration."""

    result = copy.deepcopy(dict(payload))
    metadata = result.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("generated_utc", None)
    records = result.get("frame_execution", {})
    if isinstance(records, dict):
        for record in records.values():
            if isinstance(record, dict):
                record.pop("worker_pid", None)
                record.pop("elapsed_seconds", None)
    return result


def same_json(first: object, second: object) -> bool:
    """Compare strict JSON without treating booleans as numeric values."""

    return json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
        second, sort_keys=True, allow_nan=False
    )


def option_record(options: AnalysisOptions) -> dict[str, Any]:
    """Serialize the complete options model without precision loss."""

    def serialize(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, Mapping):
            return {key: serialize(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [serialize(item) for item in value]
        return value

    return {field.name: serialize(getattr(options, field.name)) for field in fields(options)}


def prepare_output_directory(
    output_directory: Path,
    source: Path,
    baseline: Path,
    preset: Path | None = None,
) -> Path:
    """Create an exclusively new output directory outside resolved input paths."""

    source = source.resolve(strict=True)
    require(source.is_dir(), "The baseline source must be an existing sequence folder.")
    protected = [source, baseline.resolve(strict=True)]
    if preset is not None:
        protected.append(preset.resolve(strict=True))
    output = output_directory.resolve()
    for path in protected:
        require(
            output != path and path not in output.parents,
            f"Verification output must be outside its input: {path}",
        )
    require(
        not output_directory.exists() and not output_directory.is_symlink(),
        "Verification output directory must not already exist.",
    )
    output.mkdir(parents=True, exist_ok=False)
    return output


def configure_window(
    window: MainWindow,
    baseline: Mapping[str, Any],
    preset: Path | None,
) -> AnalysisOptions:
    """Set real GUI controls and reject every unrepresentable option before reads."""

    from aovguard.core.luminance import ACESCG, REC601, REC709
    from aovguard.core.models import AnalysisOptions, SourceKind, SourceMode
    from aovguard.gui.worker import build_analysis_options
    from aovguard.rules.builtin import effective_rule_parameters

    metadata = baseline["metadata"]
    require(isinstance(metadata, Mapping), "Baseline metadata must be an object.")
    require(
        metadata.get("source_kind") == SourceKind.NUMBERED_SEQUENCE.value,
        "GUI sequence verification requires a numbered-sequence baseline.",
    )
    raw = metadata.get("options")
    require(isinstance(raw, dict), "Baseline must include complete analysis options.")
    require(
        set(raw) == {field.name for field in fields(AnalysisOptions)},
        "Baseline options are incomplete or unsupported by this application version.",
    )
    for key in ("recursive", "allow_multiple_sequences", "isolate_frames"):
        require(type(raw[key]) is bool, f"Baseline {key} must be a boolean.")
    for key in ("max_depth", "max_frames"):
        require(raw[key] is None or type(raw[key]) is int, f"Baseline {key} must be an integer.")
    require(
        isinstance(raw["enabled_rules"], list)
        and all(isinstance(rule, str) for rule in raw["enabled_rules"]),
        "Baseline enabled_rules must contain rule identifiers.",
    )
    require(
        isinstance(raw["frame_pattern"], str) and raw["frame_pattern"].casefold().endswith(".exr"),
        "Baseline frame_pattern must select EXR filenames.",
    )
    if raw["expected_frame_range"] is not None:
        require(
            isinstance(raw["expected_frame_range"], list)
            and len(raw["expected_frame_range"]) == 2
            and all(type(value) is int for value in raw["expected_frame_range"]),
            "Baseline expected_frame_range must contain two integers.",
        )
    model_values = dict(raw)
    model_values["enabled_rules"] = tuple(raw["enabled_rules"])
    model_values["luminance_weights"] = tuple(raw["luminance_weights"])
    if raw["expected_frame_range"] is not None:
        model_values["expected_frame_range"] = tuple(raw["expected_frame_range"])
    options = AnalysisOptions(**model_values)
    require(
        options.source_mode is not SourceMode.COMPARISON,
        "A comparison-set policy cannot reproduce a numbered-sequence baseline.",
    )
    require(
        not (options.preset_name or options.aov_category_overrides) or preset is not None,
        "This baseline requires its original --preset file.",
    )
    enabled = set(options.enabled_rules or ())
    require(
        enabled <= set(window.rule_checkboxes), "Baseline enables rules unavailable in the GUI."
    )
    window.source_edit.setText(str(metadata["source"]))
    window.rules_edit.setText(str(preset) if preset is not None else "")
    for rule_id, checkbox in window.rule_checkboxes.items():
        checkbox.setChecked(rule_id in enabled)
    named_weights = {
        (REC709.r, REC709.g, REC709.b): "Rec.709",
        (REC601.r, REC601.g, REC601.b): "Rec.601",
        (ACESCG.r, ACESCG.g, ACESCG.b): "ACEScg",
    }
    window.luminance_combo.setCurrentText(named_weights.get(options.luminance_weights, "Custom"))
    for spin, value in zip(window.custom_weight_spins, options.luminance_weights):
        spin.setValue(value)
    window.frame_pattern_edit.setText(options.frame_pattern)
    window.recursive_checkbox.setChecked(options.recursive)
    if options.max_depth is None:
        raise VerificationError("GUI cannot represent an unlimited max_depth.")
    window.max_depth_spin.setValue(options.max_depth)
    window.allow_multiple_sequences_checkbox.setChecked(options.allow_multiple_sequences)
    window.max_frames_spin.setValue(options.max_frames or 0)
    budget = options.max_memory_mb
    require(budget is None or budget.is_integer(), "GUI memory budget requires integer MiB.")
    window.max_memory_spin.setValue(int(budget) if budget is not None else 0)
    window.isolate_frames_checkbox.setChecked(options.isolate_frames)
    window.frame_timeout_spin.setValue(options.frame_timeout_seconds or 0)
    window.source_mode_buttons[SourceMode(options.source_mode)].setChecked(True)
    expected = options.expected_frame_range
    window.expected_range_checkbox.setChecked(expected is not None)
    if expected is not None:
        window.expected_start_spin.setValue(expected[0])
        window.expected_end_spin.setValue(expected[1])
    custom_spins = window.custom_weight_spins
    require(len(custom_spins) == 3, "The GUI must expose exactly three luminance weights.")
    actual, definitions = build_analysis_options(
        luminance_model=window.luminance_combo.currentText(),
        rules_config=str(preset) if preset is not None else None,
        selected_rule_ids=enabled,
        custom_luminance_weights=(
            custom_spins[0].value(),
            custom_spins[1].value(),
            custom_spins[2].value(),
        ),
        frame_pattern=window.frame_pattern_edit.text(),
        recursive=window.recursive_checkbox.isChecked(),
        max_depth=window.max_depth_spin.value(),
        allow_multiple_sequences=window.allow_multiple_sequences_checkbox.isChecked(),
        max_frames=window.max_frames_spin.value() or None,
        max_memory_mb=float(window.max_memory_spin.value()) or None,
        isolate_frames=window.isolate_frames_checkbox.isChecked(),
        frame_timeout_seconds=window.frame_timeout_spin.value() or None,
        expected_frame_range=(
            (window.expected_start_spin.value(), window.expected_end_spin.value())
            if window.expected_range_checkbox.isChecked()
            else None
        ),
        source_mode=window._selected_source_mode(),
    )
    actual_record = option_record(actual)
    differing = [key for key in raw if not same_json(raw[key], actual_record[key])]
    require(not differing, "GUI cannot reproduce baseline options exactly: " + ", ".join(differing))
    rules = [
        {
            "id": definition.id,
            "enabled": definition.enabled,
            "severity": definition.severity.value,
            "parameters": effective_rule_parameters(definition),
            "supported_aov_types": sorted(
                category.value for category in definition.supported_aov_types
            ),
        }
        for definition in definitions
    ]
    require(
        same_json(metadata.get("effective_rules"), rules),
        "The original preset/effective rules cannot be reproduced exactly.",
    )
    return actual


def pump_until(application: QApplication, condition: Callable[[], bool], seconds: float) -> None:
    """Deliver Qt events while respecting a bounded acceptance deadline."""

    deadline = time.monotonic() + seconds
    while not condition():
        application.processEvents()
        if time.monotonic() >= deadline:
            raise TimeoutError(f"GUI condition exceeded {seconds:g} seconds.")
        time.sleep(0.01)
    application.processEvents()


def resource_snapshot(window: MainWindow, initial_pids: set[int]) -> dict[str, Any]:
    """Describe owned jobs and workers without claiming unrelated jobs were stopped."""

    return {
        "has_job": window.analysis_controller.has_job,
        "qthread_reference": window.analysis_thread is not None,
        "worker_reference": window.worker is not None,
        "unsafe": window.analysis_controller.unsafe,
        "active_children": [
            child.pid
            for child in multiprocessing.active_children()
            if child.pid is not None and child.pid not in initial_pids
        ],
        "receiver_threads": [
            thread.name
            for thread in threading.enumerate()
            if thread.name.startswith("AOVGuard receiver ")
        ],
    }


def cleanup_confirmed(snapshot: Mapping[str, Any]) -> bool:
    """Return true only when thread, worker, receiver and child cleanup are confirmed."""

    return not any(snapshot.values())


def require_table_item(table: QTableWidget, row: int, column: int) -> QTableWidgetItem:
    """Return a populated evidence cell or reject incomplete GUI presentation."""

    item = table.item(row, column)
    if item is None:
        raise VerificationError(f"GUI evidence cell is missing at row {row}, column {column}.")
    return item


def navigate_results(window: MainWindow) -> dict[str, Any]:
    """Verify finding, chart and actual outlier navigation only when evidence exists."""

    from aovguard.ui import FULL_PATH_ROLE, TAB_FRAMES

    evidence: dict[str, Any] = {}
    if window.findings_table.rowCount():
        window.findings_table.setCurrentCell(0, 0)
        window.show_finding_details(0, 0, -1, -1)
        require(window.selected_finding is not None, "Finding selection did not retain evidence.")
        finding = window.selected_finding
        require(
            finding is not None and bool(window.finding_details.toPlainText()),
            "Finding details are empty.",
        )
        if finding is not None:
            evidence["finding"] = {
                "status": "passed",
                "rule_id": finding.rule_id,
                "aov": finding.aov,
            }
    else:
        evidence["finding"] = {"status": "skipped", "reason": "The real report has no findings."}
    if window.outlier_table.rowCount():
        path = require_table_item(window.outlier_table, 0, 0).data(FULL_PATH_ROLE)
        aov = require_table_item(window.outlier_table, 0, 1).text()
        window.outlier_table.setCurrentCell(0, 0)
        window.locate_selected_outlier()
        row = window.frame_table.currentRow()
        require(
            window.tabs.currentIndex() == TAB_FRAMES
            and row >= 0
            and require_table_item(window.frame_table, row, 0).data(FULL_PATH_ROLE) == path
            and require_table_item(window.frame_table, row, 1).text() == aov,
            "Outlier did not navigate to its exact AOV and frame.",
        )
        evidence["outlier"] = {"status": "passed", "path": str(path), "aov": aov, "row": row}
    else:
        evidence["outlier"] = {
            "status": "skipped",
            "reason": "The real report has no robust outliers.",
        }
    if window.frame_table.rowCount():
        path = require_table_item(window.frame_table, 0, 0).data(FULL_PATH_ROLE)
        aov = require_table_item(window.frame_table, 0, 1).text()
        window.series_aov_combo.setCurrentText(aov)
        window.locate_frame_from_chart(path)
        row = window.frame_table.currentRow()
        require(
            window.tabs.currentIndex() == TAB_FRAMES
            and row >= 0
            and require_table_item(window.frame_table, row, 0).data(FULL_PATH_ROLE) == path
            and require_table_item(window.frame_table, row, 1).text() == aov,
            "Chart did not navigate to its exact AOV and frame.",
        )
        evidence["chart"] = {"status": "passed", "path": str(path), "aov": aov, "row": row}
    else:
        evidence["chart"] = {
            "status": "skipped",
            "reason": "No color frame metrics were available.",
        }
    return evidence


def verify_cryptomatte_scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Check color exclusion using per-frame semantic categories, never name substrings."""

    names: set[str] = set()
    frame_metrics = payload.get("frame_metrics", {})
    for inspection in payload.get("inspections", []):
        for descriptor in inspection.get("aovs", []):
            if descriptor.get("category") == "cryptomatte":
                name = descriptor["name"]
                names.add(name)
                require(
                    name not in frame_metrics.get(inspection["path"], {}),
                    f"Cryptomatte AOV entered color luminance metrics: {name}",
                )
    return (
        {"status": "passed", "names": sorted(names)}
        if names
        else {"status": "skipped", "reason": "No Cryptomatte AOVs were present."}
    )


def run_verification(
    baseline: Path,
    output_directory: Path,
    *,
    preset: Path | None = None,
    deadline_seconds: float = 3600,
    check_cancellation: bool = False,
) -> dict[str, Any]:
    """Run real GUI acceptance and retain diagnostics on every recoverable failure."""

    require(
        math.isfinite(deadline_seconds) and deadline_seconds > 0,
        "Deadline must be finite and positive.",
    )
    from aovguard.reports.comparison import load_report_payload

    payload = load_report_payload(baseline)
    metadata = payload.get("metadata")
    require(
        isinstance(metadata, dict) and isinstance(metadata.get("source"), str),
        "Baseline source is missing.",
    )
    source = Path(payload["metadata"]["source"])
    output = prepare_output_directory(output_directory, source, baseline, preset)
    summary: dict[str, Any] = {
        "passed": False,
        "method": "Automated Qt sequence acceptance with real analysis; not a usability study.",
        "baseline": str(baseline.absolute()),
        "source": str(source),
        "cancellation": {"status": "skipped", "reason": "Cancellation check was not requested."},
    }
    logs: list[str] = []
    dialogs: list[dict[str, str]] = []
    initial_pids = {
        child.pid for child in multiprocessing.active_children() if child.pid is not None
    }
    window: MainWindow | None = None
    application: QApplication | None = None
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QSettings
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

        from aovguard.reports.comparison import compare_report_payloads
        from aovguard.reports.json_report import build_analysis_report_payload
        from aovguard.ui import TAB_FINDINGS, TAB_METRICS, MainWindow

        existing = QApplication.instance()
        require(
            existing is None or isinstance(existing, QApplication),
            "A non-widget Qt application is already active.",
        )
        application = existing if isinstance(existing, QApplication) else QApplication([])
        if not QFontDatabase.families() and os.name == "nt":
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf"):
                path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
                if path.is_file():
                    QFontDatabase.addApplicationFont(str(path))
        summary["screenshot_font_family_count"] = len(QFontDatabase.families())
        window = MainWindow(
            settings=QSettings(str(output / "gui-settings.ini"), QSettings.Format.IniFormat)
        )
        window.resize(1460, 980)
        options = configure_window(window, payload, preset)
        summary["options"] = option_record(options)
        require(
            not check_cancellation or options.isolate_frames,
            "Cancellation verification requires isolated analysis.",
        )
        window.show()
        application.processEvents()
        terminal: list[str] = []
        window.analysis_controller.cancelled.connect(lambda: terminal.append("cancelled"))
        window.analysis_controller.finished.connect(lambda _result: terminal.append("finished"))
        window.analysis_controller.error.connect(
            lambda message, _details: terminal.append("error: " + message)
        )
        window.analysis_controller.log.connect(logs.append)

        def dialog(
            _parent: object, title: str, message: str, *_args: object, **_kwargs: object
        ) -> object:
            dialogs.append({"title": title, "message": message})
            return QMessageBox.StandardButton.Ok

        with (
            patch.object(QMessageBox, "critical", dialog),
            patch.object(QMessageBox, "warning", dialog),
            patch.object(QMessageBox, "information", dialog),
        ):
            if check_cancellation:
                window.start_analysis()
                pump_until(
                    application,
                    lambda: (
                        bool(resource_snapshot(window, initial_pids)["active_children"])
                        or bool(terminal)
                    ),
                    min(deadline_seconds, 30),
                )
                before = resource_snapshot(window, initial_pids)
                require(
                    bool(before["active_children"]),
                    "Analysis finished before an active child could be cancelled.",
                )
                requested = time.monotonic()
                window.cancel_analysis()
                pump_until(application, lambda: not window.analysis_controller.has_job, 30)
                snapshot = resource_snapshot(window, initial_pids)
                require(
                    terminal == ["cancelled"] and cleanup_confirmed(snapshot),
                    "Cancellation did not terminate and clean up its analysis job.",
                )
                require(
                    window.report is None and window.analyze_btn.isEnabled(),
                    "Cancellation left a stale report or blocked restart.",
                )
                summary["cancellation"] = {
                    "status": "passed",
                    "seconds_to_idle": time.monotonic() - requested,
                    "observed_worker_pids": before["active_children"],
                    "cleanup": snapshot,
                }
                logs.append("CANCELLATION RUN\n" + window.log_output.toPlainText())
                terminal.clear()
            started = time.monotonic()
            window.start_analysis()
            pump_until(
                application, lambda: not window.analysis_controller.has_job, deadline_seconds
            )
            analysis_elapsed = time.monotonic() - started
            require(
                terminal == ["finished"]
                and window.report is not None
                and window.options is not None,
                "GUI analysis did not finish with a report: " + repr(terminal),
            )
            report = window.report
            if report is None:
                raise VerificationError("GUI report is missing.")
            candidate = build_analysis_report_payload(report, options=window.options)
            # Save evidence before parity/navigation checks to avoid repeating real reads.
            for suffix, export in (("json", window.export_json), ("html", window.export_html)):
                destination = output / f"gui-report.{suffix}"
                with patch.object(
                    QFileDialog, "getSaveFileName", return_value=(str(destination), "")
                ):
                    export()
                require(destination.is_file(), f"GUI {suffix.upper()} export failed.")
            summary["analysis"] = {
                "seconds_to_idle_including_presentation": analysis_elapsed,
                "frames_processed": candidate["metadata"]["frames_processed"],
                "frames_failed": candidate["metadata"]["frames_failed"],
                "findings_count": len(candidate["findings"]),
                "status": candidate["metadata"]["status"],
            }
            first, second = stable_payload(payload), stable_payload(candidate)
            summary["parity"] = {
                "exact_semantic_match": same_json(first, second),
                "differing_top_level_keys": sorted(
                    key
                    for key in set(first) | set(second)
                    if not same_json(first.get(key), second.get(key))
                ),
            }
            comparison = compare_report_payloads(payload, candidate)
            summary["comparison"] = {
                "changed_aovs": comparison.changed_aov_count,
                "new_findings": len(comparison.new_findings),
                "resolved_findings": len(comparison.resolved_findings),
                "warnings": list(comparison.warnings),
            }
            summary["navigation"] = navigate_results(window)
            summary["cryptomatte"] = verify_cryptomatte_scope(candidate)
            captures: list[str] = []
            for tab, name in ((TAB_FINDINGS, "gui-findings.png"), (TAB_METRICS, "gui-metrics.png")):
                window.tabs.setCurrentIndex(tab)
                application.processEvents()
                destination = output / name
                require(window.grab().save(str(destination)), "Qt screenshot could not be saved.")
                captures.append(str(destination))
            summary["screenshots"] = captures
            report = window.report
            previous_dialogs = len(dialogs)
            blocked = output / "blocked-destination.exr"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(blocked), "")):
                window.export_json()
            require(
                len(dialogs) == previous_dialogs + 1
                and dialogs[-1]["title"] == "Export Error"
                and not blocked.exists(),
                "EXR report destination was not safely rejected.",
            )
            require(
                window.report is report and window.export_json_btn.isEnabled(),
                "Export failure lost the report or blocked retry.",
            )
            retry = output / "gui-report-retry.json"
            with patch.object(QFileDialog, "getSaveFileName", return_value=(str(retry), "")):
                window.export_json()
            require(
                same_json(stable_payload(load_report_payload(retry)), second),
                "Export retry altered the report evidence.",
            )
            with patch.object(QFileDialog, "getOpenFileName", return_value=(str(baseline), "")):
                window.compare_baseline_json()
            require(len(dialogs) == previous_dialogs + 1, "GUI baseline comparison failed.")
            summary["exports"] = {
                "json": str(output / "gui-report.json"),
                "html": str(output / "gui-report.html"),
                "retry": str(retry),
                "blocked_exr_destination_absent": not blocked.exists(),
                "baseline_summary": window.comparison_summary_label.text(),
            }
            require(summary["parity"]["exact_semantic_match"], "CLI and GUI evidence differ.")
            require(
                not comparison.changed_aov_count
                and not comparison.new_findings
                and not comparison.resolved_findings
                and not comparison.warnings,
                "Baseline comparison did not confirm unchanged evidence.",
            )
            require(
                cleanup_confirmed(resource_snapshot(window, initial_pids)),
                "Analysis resources are not clean.",
            )
            require(len(dialogs) == 1, "Unexpected GUI errors were displayed.")
            summary["passed"] = True
    except BaseException as exc:
        summary["passed"] = False
        summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        logs.append(traceback.format_exc())
    finally:
        if window is not None and application is not None:
            logs.append("GUI LOG\n" + window.log_output.toPlainText())
            try:
                if window.analysis_controller.has_job:
                    window.analysis_controller.cancel()
                    pump_until(application, lambda: not window.analysis_controller.has_job, 30)
                snapshot = resource_snapshot(window, initial_pids)
                summary["cleanup"] = snapshot
                if not cleanup_confirmed(snapshot):
                    summary["passed"] = False
                    summary["cleanup_failure"] = "Qt worker/process cleanup was not confirmed."
                if not snapshot["has_job"]:

                    def close_dialog(
                        _parent: object,
                        title: str,
                        message: str,
                        *_args: object,
                        **_kwargs: object,
                    ) -> object:
                        dialogs.append({"title": title, "message": message})
                        return QMessageBox.StandardButton.Ok

                    with (
                        patch.object(QMessageBox, "warning", close_dialog),
                        patch.object(QMessageBox, "critical", close_dialog),
                    ):
                        window.close()
                        application.processEvents()
            except BaseException as exc:
                summary["passed"] = False
                summary["cleanup_failure"] = f"{type(exc).__name__}: {exc}"
                summary["cleanup"] = resource_snapshot(window, initial_pids)
                logs.append(traceback.format_exc())
        else:
            summary["cleanup"] = {"status": "not_started"}
        summary["dialogs"] = dialogs
        from aovguard.io.output import atomic_text_writer

        with atomic_text_writer(
            output / "gui-acceptance.json", protected_paths=(baseline, source)
        ) as handle:
            json.dump(summary, handle, indent=2, allow_nan=False)
        with atomic_text_writer(
            output / "gui-workflow.log", protected_paths=(baseline, source)
        ) as handle:
            handle.write("\n\n".join(logs))
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Expose optional Qt acceptance without importing Qt for help or argument parsing."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--preset", type=Path)
    parser.add_argument("--deadline-seconds", type=float, default=3600)
    parser.add_argument("--check-cancellation", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, signal.default_int_handler)
    try:
        summary = run_verification(
            args.baseline,
            args.output_directory,
            preset=args.preset,
            deadline_seconds=args.deadline_seconds,
            check_cancellation=args.check_cancellation,
        )
    except (OSError, ValueError, VerificationError) as exc:
        print(f"aovguard GUI verification: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "passed": summary["passed"],
                "summary": str(args.output_directory.absolute() / "gui-acceptance.json"),
            }
        ),
        flush=True,
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
