import json
from pathlib import Path

import Imath
import numpy as np
import OpenEXR
import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from aovguard.cli import main as cli_main
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    ChannelMetricSet,
    FileInspection,
    Finding,
    MetricSet,
    SequenceCheckResult,
    SequenceDescriptor,
    SeriesMetricSet,
    Severity,
    SourceKind,
    SourceMode,
)
from aovguard.reports.json_report import build_analysis_report_payload
from aovguard.rules.loader import load_rule_preset
from aovguard.ui import (
    TAB_COMPARISON,
    TAB_FINDINGS,
    TAB_FRAMES,
    TAB_METRICS,
    TAB_OUTLIERS,
    TAB_SEQUENCES,
    TAB_TECHNICAL,
    AnalyzeWorker,
    MainWindow,
    build_analysis_options,
    display_path,
    format_inspection,
    format_percentage_change,
    format_technical_value,
    summarize_analysis_scope,
    summarize_aov_categories,
)


@pytest.fixture
def app():
    application = QApplication.instance() or QApplication([])
    application.setOrganizationName("AOVGuardTests")
    application.setApplicationName("AOVGuardTests")
    settings = QSettings()
    settings.clear()
    yield application
    settings.clear()


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path) -> Path:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(2, 2)
    header["channels"] = {
        name: Imath.Channel(pixel_type)
        for name in ("R", "G", "B", "diffuse.R", "diffuse.G", "diffuse.B")
    }
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {
                "R": _channel(1.0, 2, 2),
                "G": _channel(2.0, 2, 2),
                "B": _channel(3.0, 2, 2),
                "diffuse.R": _channel(4.0, 2, 2),
                "diffuse.G": _channel(5.0, 2, 2),
                "diffuse.B": _channel(6.0, 2, 2),
            }
        )
    finally:
        output.close()
    return path


def _inspection(path: Path) -> FileInspection:
    return FileInspection(
        path=path,
        width=2,
        height=2,
        channels=("R", "G", "B"),
        aovs=(
            AOVDescriptor(
                name="beauty",
                channels=("R", "G", "B"),
                category=AOVCategory.COLOR,
                category_confidence="root_rgb_channels",
            ),
        ),
    )


def test_build_analysis_options_uses_builtin_model_and_rules() -> None:
    options, definitions = build_analysis_options(
        luminance_model="Rec.601",
        rules_config=None,
    )

    assert options.luminance_weights == (0.299, 0.587, 0.114)
    assert options.enabled_rules == (
        "unknown_aov",
        "nan_inf",
        "empty_aov",
        "near_empty_aov",
        "resolution_mismatch",
        "aov_structure_mismatch",
    )
    assert {definition.id for definition in definitions}.issuperset(options.enabled_rules)


def test_build_analysis_options_accepts_custom_luminance() -> None:
    options, _ = build_analysis_options(
        luminance_model="Custom",
        rules_config=None,
        custom_luminance_weights=(0.25, 0.5, 0.25),
    )

    assert options.luminance_weights == (0.25, 0.5, 0.25)

    with pytest.raises(ValueError, match="requires R, G and B"):
        build_analysis_options(luminance_model="Custom", rules_config=None)


def test_build_analysis_options_loads_rule_preset(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text(
        "\n".join(
            [
                'preset = "gui_preset"',
                "[aov_categories]",
                'rendererData = "scalar"',
                "[rules.missing_aov]",
                "enabled = true",
                'severity = "error"',
                "[rules.missing_aov.parameters]",
                'required = ["beauty"]',
            ]
        )
    )

    options, definitions = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=str(path),
    )

    assert options.preset_name == "gui_preset"
    assert options.enabled_rules == ("missing_aov",)
    assert options.aov_category_overrides == {
        "rendererData": AOVCategory.SCALAR,
    }
    assert definitions[0].id == "missing_aov"


def test_format_inspection_contains_structure_details() -> None:
    text = format_inspection(_inspection(Path("shot.1001.exr")))

    assert "Size: 2x2" in text
    assert "R" in text
    assert "beauty: color" in text
    assert summarize_aov_categories(_inspection(Path("shot.1001.exr"))) == (
        "1 AOV detected: 1 color."
    )


def test_format_inspection_includes_reader_warnings() -> None:
    inspection = FileInspection(
        path=Path("unsupported.exr"),
        width=2,
        height=2,
        channels=("R", "G", "B"),
        aovs=(),
        warnings=("Multipart data is only partially supported.",),
    )

    text = format_inspection(inspection)

    assert "Warnings:" in text
    assert "Multipart data is only partially supported." in text
    assert summarize_aov_categories(inspection) == "0 AOVs detected."


def test_ui_path_and_frame_change_formatting() -> None:
    source = Path("renders")

    assert display_path(source / "nested" / "shot.1001.exr", source) == str(
        Path("nested") / "shot.1001.exr"
    )
    assert display_path(Path("elsewhere/shot.1001.exr"), source) == "shot.1001.exr"
    assert format_percentage_change(2.0, 1.0) == "+100.00%"
    assert format_percentage_change(0.5, 1.0) == "-50.00%"
    assert format_percentage_change(0.0, 0.0) == "0.00%"
    assert format_percentage_change(1.0, 0.0) == "new activity"
    assert format_percentage_change(0.99999999, 1.0) == "0.00%"
    assert format_technical_value(-2.8e20) == "-2.800000e+20"
    assert format_technical_value(0.153526) == "0.153526"


def test_summarize_analysis_scope_explains_excluded_technical_passes() -> None:
    inspection = FileInspection(
        path=Path("technical.exr"),
        width=2,
        height=2,
        channels=("R", "G", "B", "N.X", "N.Y", "N.Z", "Z"),
        aovs=(
            AOVDescriptor(
                name="beauty",
                channels=("R", "G", "B"),
                category=AOVCategory.COLOR,
            ),
            AOVDescriptor(
                name="N",
                channels=("N.X", "N.Y", "N.Z"),
                category=AOVCategory.VECTOR,
            ),
            AOVDescriptor(
                name="Z",
                channels=("Z",),
                category=AOVCategory.DEPTH,
            ),
        ),
    )

    summary = summarize_analysis_scope(inspection, {"beauty"}, {"beauty", "N", "Z"})

    assert "3 AOVs detected: 1 color, 1 vector, 1 depth" in summary
    assert "1 color AOV analyzed" in summary
    assert "2 technical passes excluded from luminance (1 vector, 1 depth)" in summary
    assert "2 technical AOVs diagnosed per channel" in summary


def test_build_analysis_options_applies_gui_rule_selection() -> None:
    options, definitions = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=None,
        selected_rule_ids={"nan_inf", "negative_values"},
    )

    assert options.enabled_rules == ("nan_inf", "negative_values")
    enabled = {definition.id for definition in definitions if definition.enabled}
    assert enabled == {"nan_inf", "negative_values"}


def test_build_analysis_options_applies_discovery_settings() -> None:
    options, _ = build_analysis_options(
        luminance_model="Rec.709",
        rules_config=None,
        frame_pattern="shot.*.exr",
        recursive=True,
        max_depth=3,
        allow_multiple_sequences=True,
        max_frames=500,
        expected_frame_range=(1, 800),
    )

    assert options.frame_pattern == "shot.*.exr"
    assert options.recursive
    assert options.max_depth == 3
    assert options.allow_multiple_sequences
    assert options.max_frames == 500
    assert options.expected_frame_range == (1, 800)


def test_analyze_worker_runs_common_backend(tmp_path: Path, app) -> None:
    _write_exr(tmp_path / "shot.1001.exr")
    worker = AnalyzeWorker(
        str(tmp_path),
        frame_pattern="shot.*.exr",
        recursive=True,
        max_depth=2,
        allow_multiple_sequences=True,
    )
    payloads: list[object] = []
    errors: list[tuple[str, str]] = []
    progress: list[tuple[int, str]] = []
    worker.finished.connect(payloads.append)
    worker.error.connect(lambda message, details: errors.append((message, details)))
    worker.progress.connect(lambda percent, message: progress.append((percent, message)))

    worker.run()

    assert errors == []
    assert len(payloads) == 1
    report, options = payloads[0]
    assert set(report.metrics_by_aov) == {"beauty", "diffuse"}
    assert options.enabled_rules == (
        "unknown_aov",
        "nan_inf",
        "empty_aov",
        "near_empty_aov",
        "resolution_mismatch",
        "aov_structure_mismatch",
    )
    assert options.frame_pattern == "shot.*.exr"
    assert options.recursive
    assert options.max_depth == 2
    assert options.allow_multiple_sequences
    assert progress[-1] == (100, "Analysis complete.")


def test_cli_and_gui_produce_equivalent_canonical_payloads(
    tmp_path: Path,
    app,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_exr(tmp_path / "shot.1001.exr")
    worker = AnalyzeWorker(str(tmp_path), luminance_model="Rec.601")
    payloads: list[object] = []
    worker.finished.connect(payloads.append)

    worker.run()

    assert len(payloads) == 1
    gui_report, gui_options = payloads[0]
    gui_payload = build_analysis_report_payload(gui_report, options=gui_options)

    output_path = tmp_path / "cli-report.json"
    cli_main(
        [
            "analyze",
            str(tmp_path),
            "--luminance-model",
            "rec601",
            "--json",
            str(output_path),
        ]
    )
    capsys.readouterr()
    cli_payload = json.loads(output_path.read_text(encoding="utf-8"))

    gui_payload["metadata"].pop("generated_utc")
    cli_payload["metadata"].pop("generated_utc")
    assert gui_payload == cli_payload


def test_analyze_worker_reports_backend_errors(tmp_path: Path, app) -> None:
    worker = AnalyzeWorker(str(tmp_path))
    errors: list[tuple[str, str]] = []
    worker.error.connect(lambda message, details: errors.append((message, details)))

    worker.run()

    assert len(errors) == 1
    assert "No EXR files" in errors[0][0]
    assert errors[0][1] == ""


def test_analyze_worker_preserves_traceback_for_unexpected_errors(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = AnalyzeWorker(str(tmp_path))
    errors: list[tuple[str, str]] = []
    worker.error.connect(lambda message, details: errors.append((message, details)))
    monkeypatch.setattr(
        "aovguard.gui.worker.analyze",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("backend bug")),
    )

    worker.run()

    assert len(errors) == 1
    assert errors[0][0] == "backend bug"
    assert "Traceback" in errors[0][1]


def test_analyze_worker_emits_cancelled_before_first_frame(tmp_path: Path, app) -> None:
    _write_exr(tmp_path / "shot.1001.exr")
    worker = AnalyzeWorker(str(tmp_path))
    cancelled: list[bool] = []
    finished: list[object] = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.finished.connect(finished.append)

    worker.request_cancel()
    worker.run()

    assert cancelled == [True]
    assert finished == []


def test_main_window_uses_automatic_backend_and_displays_results(app) -> None:
    window = MainWindow()
    path = Path("shot.1001.exr")
    report = AnalysisReport(
        source=Path("renders"),
        frames=(path,),
        inspections=(_inspection(path),),
        metrics_by_aov={
            "beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=4),
        },
        findings=(
            Finding(
                rule_id="empty_aov",
                severity=Severity.WARNING,
                message="Test finding",
                file=path,
                aov="beauty",
            ),
        ),
        rules_executed=("empty_aov",),
        frame_metrics={
            path: {"beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=4)},
        },
    )
    options = AnalysisOptions(enabled_rules=("empty_aov",))

    window.on_analysis_finished((report, options))

    assert not hasattr(window, "mode_combo")
    assert window.metrics_table.rowCount() == 1
    assert window.findings_table.rowCount() == 1
    assert window.metrics_table.item(0, 0).text() == "beauty"
    assert "Combined rendered image" in window.metrics_table.item(0, 0).toolTip()
    assert "Fraction of analyzed pixels" in window.metrics_table.item(0, 2).toolTip()
    assert window.findings_table.item(0, 1).text() == "empty_aov"
    assert "no visible contribution" in window.findings_table.item(0, 1).toolTip()
    assert window.tabs.tabText(TAB_FINDINGS) == "Findings (1)"
    assert window.tabs.tabText(TAB_FRAMES) == "Frames (1)"
    assert window.tabs.currentIndex() == TAB_FINDINGS
    assert window.frame_table.rowCount() == 1
    assert window.frame_table.item(0, 1).text() == "beauty"
    assert "1 color" in window.structure_label.text()
    assert "1 color AOV analyzed" in window.structure_label.text()
    assert window.export_json_btn.isEnabled()
    assert "1/1 frames processed" in window.progress_label.text()
    assert "1 color AOV analyzed" in window.progress_label.text()
    assert window.status_label.text() == "WARNING | 0 errors | 1 warnings | 0 info"
    assert window.rule_checkboxes["nan_inf"].isChecked()
    assert not window.rule_checkboxes["negative_values"].isChecked()
    window.close()


def test_main_window_shows_aggregate_file_evidence_and_collapses_warning_log(
    tmp_path: Path,
    app,
) -> None:
    frame_a = tmp_path / "look_a.exr"
    frame_b = tmp_path / "look_b.exr"
    report = AnalysisReport(
        source=tmp_path,
        frames=(frame_a, frame_b),
        inspections=(),
        metrics_by_aov={},
        findings=(
            Finding(
                rule_id="empty_aov",
                severity=Severity.WARNING,
                message="No visible contribution.",
                aov="emission",
                affected_files=(frame_a, frame_b),
            ),
        ),
        warnings=("Informational discovery note.",),
        source_kind=SourceKind.COMPARISON_SET,
    )
    window = MainWindow()
    window.log_section.set_expanded(True)

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.findings_table.item(0, 5).text() == "2 files"
    assert str(frame_a) in window.findings_table.item(0, 5).toolTip()
    assert "Affected files:" in window.finding_details.toPlainText()
    assert str(frame_b) in window.finding_details.toPlainText()
    window.copy_finding_path()
    assert QApplication.clipboard().text() == f"{frame_a}\n{frame_b}"
    assert not window.log_section.is_expanded()
    window.close()


def test_main_window_displays_technical_aov_diagnostics(app) -> None:
    window = MainWindow()
    path = Path("shot.1001.exr")
    inspection = FileInspection(
        path=path,
        width=2,
        height=2,
        channels=("R", "G", "B", "Z"),
        aovs=(
            AOVDescriptor("beauty", ("R", "G", "B"), AOVCategory.COLOR),
            AOVDescriptor("Z", ("Z",), AOVCategory.DEPTH),
        ),
    )
    report = AnalysisReport(
        source=path,
        frames=(path,),
        inspections=(inspection,),
        metrics_by_aov={"beauty": MetricSet(1.0, 0.5, 1.0, pixel_count=4)},
        channel_metrics_by_aov={"Z": {"Z": ChannelMetricSet(4, 2.5, 1.0, 4.0, negative_count=0)}},
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.technical_table.rowCount() == 1
    assert window.technical_table.item(0, 0).text() == "Z"
    assert window.technical_table.item(0, 1).text() == "depth"
    assert "depth" in window.technical_table.item(0, 0).toolTip().casefold()
    assert "not treated as color" in window.technical_table.item(0, 1).toolTip()
    assert window.tabs.tabText(TAB_TECHNICAL) == "Technical (1)"
    assert window.tabs.currentIndex() == TAB_METRICS
    assert "1 technical AOV diagnosed" in window.progress_label.text()
    assert "diagnosed per channel" in window.structure_label.text()
    window.close()


def test_main_window_browse_actions_and_rule_preset(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    preset = tmp_path / "rules.toml"
    preset.write_text(
        "\n".join(
            [
                'preset = "gui_selected"',
                "[rules.negative_values]",
                "enabled = true",
                'severity = "warning"',
            ]
        ),
        encoding="utf-8",
    )
    window = MainWindow()

    file_dialog_calls: list[tuple[object, ...]] = []

    def select_exr(*args):
        file_dialog_calls.append(args)
        return str(source), "EXR Files (*.exr *.EXR)"

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        select_exr,
    )
    window.browse_file()
    assert window.source_edit.text() == str(source)
    assert file_dialog_calls[0][3] == "EXR Files (*.exr *.EXR);;All Files (*)"

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getExistingDirectory",
        lambda *args: str(tmp_path),
    )
    window.browse_folder()
    assert window.source_edit.text() == str(tmp_path)

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *args: (str(preset), "Rule Presets (*.toml *.json)"),
    )
    window.browse_rules()
    assert window.rules_edit.text() == str(preset)
    assert window.rule_checkboxes["negative_values"].isChecked()
    assert not window.rule_checkboxes["nan_inf"].isChecked()
    window.close()


def test_main_window_rejects_invalid_preset(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset = tmp_path / "invalid.toml"
    preset.write_text("not valid = [", encoding="utf-8")
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *args: (str(preset), "Rule Presets (*.toml *.json)"),
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()

    window.browse_rules()

    assert warnings and "Could not load rule preset" in warnings[0]
    window.close()


def test_main_window_validates_source(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()

    assert window._source() is None
    window.source_edit.setText(str(tmp_path / "missing.exr"))
    assert window._source() is None
    window.source_edit.setText(str(tmp_path))
    assert window._source() == tmp_path

    assert warnings == [
        "Please choose an EXR file or folder first.",
        "The selected source does not exist.",
    ]
    window.close()


def test_main_window_inspects_exr_and_reports_inspection_errors(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _write_exr(tmp_path / "shot.1001.exr")
    monkeypatch.setattr("aovguard.ui.QMessageBox.exec", lambda _self: 0)
    critical: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: critical.append(message),
    )
    window = MainWindow()
    window.source_edit.setText(str(source))

    window.inspect_source()

    assert "6 channels" in window.structure_label.text()
    assert "2 AOVs detected" in window.structure_label.text()

    empty = tmp_path / "empty"
    empty.mkdir()
    window.source_edit.setText(str(empty))
    window.inspect_source()
    assert critical and "No EXR files found" in critical[0]
    window.close()


class _SignalStub:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)


class _ThreadStub:
    def __init__(self, *_args: object) -> None:
        self.started = _SignalStub()
        self.finished = _SignalStub()
        self.was_started = False

    def start(self) -> None:
        self.was_started = True

    def quit(self) -> None:
        return None

    def deleteLater(self) -> None:
        return None


def test_main_window_starts_worker_with_selected_options(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    monkeypatch.setattr("aovguard.ui.QThread", _ThreadStub)
    monkeypatch.setattr(
        "aovguard.ui.AnalyzeWorker.moveToThread",
        lambda _worker, _thread: None,
    )
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.rule_checkboxes["nan_inf"].setChecked(True)
    window.rule_checkboxes["empty_aov"].setChecked(False)
    window.luminance_combo.setCurrentText("Custom")
    window.frame_pattern_edit.setText("shot.*.exr")
    window.recursive_checkbox.setChecked(True)
    window.max_depth_spin.setValue(4)
    window.allow_multiple_sequences_checkbox.setChecked(True)
    window.max_frames_spin.setValue(1000)
    window.source_mode_buttons[SourceMode.COMPARISON].setChecked(True)
    for spin, value in zip(window.custom_weight_spins, (0.25, 0.5, 0.25)):
        spin.setValue(value)

    window.start_analysis()

    assert isinstance(window.analysis_thread, _ThreadStub)
    assert window.analysis_thread.was_started
    assert window.worker is not None
    assert "nan_inf" in window.worker.selected_rule_ids
    assert "empty_aov" not in window.worker.selected_rule_ids
    assert window.worker.custom_luminance_weights == (0.25, 0.5, 0.25)
    assert window.worker.frame_pattern == "shot.*.exr"
    assert window.worker.recursive
    assert window.worker.max_depth == 4
    assert window.worker.allow_multiple_sequences
    assert window.worker.max_frames == 1000
    assert window.worker.source_mode is SourceMode.COMPARISON
    assert not window.custom_weights_widget.isHidden()
    assert not window.analyze_btn.isEnabled()
    assert window.cancel_btn.isEnabled()
    assert window.status_label.text() == "RUNNING"
    assert window.progress_label.text() == "Starting analysis..."
    assert "Starting automatic EXR analysis" in window.log_output.toPlainText()
    window.cancel_analysis()
    assert window.worker._cancel_requested
    assert not window.cancel_btn.isEnabled()
    assert window.status_label.text() == "CANCELLING"
    window.close()


def test_main_window_validates_and_passes_expected_range(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.0001.exr"
    source.touch()
    monkeypatch.setattr("aovguard.ui.QThread", _ThreadStub)
    monkeypatch.setattr("aovguard.ui.AnalyzeWorker.moveToThread", lambda *_args: None)
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.expected_range_checkbox.setChecked(True)
    window.expected_start_spin.setValue(800)
    window.expected_end_spin.setValue(1)

    window.start_analysis()
    assert warnings == ["Expected frame start must not exceed end."]
    assert window.worker is None

    window.expected_start_spin.setValue(1)
    window.expected_end_spin.setValue(800)
    window.start_analysis()
    assert window.worker is not None
    assert window.worker.expected_frame_range == (1, 800)
    window.close()


def test_main_window_rejects_missing_rule_preset_before_starting(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "shot.1001.exr"
    source.touch()
    warnings: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: warnings.append(message),
    )
    window = MainWindow()
    window.source_edit.setText(str(source))
    window.rules_edit.setText(str(tmp_path / "missing.toml"))

    window.start_analysis()

    assert window.analysis_thread is None
    assert warnings == ["The selected rule preset does not exist."]
    window.close()


def test_main_window_progress_error_and_json_export(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: errors.append(message),
    )
    window = MainWindow()

    window.on_progress(45, "Reading frame 2 of 4")
    assert window.progress_bar.value() == 45
    assert window.progress_label.text() == "Reading frame 2 of 4"

    window.set_busy(True)
    window.on_analysis_error("Broken EXR", "reader traceback")
    assert window.analyze_btn.isEnabled()
    assert window.progress_bar.value() == 0
    assert window.progress_label.text() == "Analysis failed."
    assert window.status_label.text() == "FAIL | ANALYSIS ERROR"
    assert "reader traceback" in window.log_output.toPlainText()
    assert errors == ["Broken EXR"]

    window.export_json()
    report = AnalysisReport(
        source=tmp_path,
        frames=(),
        inspections=(),
        metrics_by_aov={"unknown": MetricSet(0.0, 0.0, 0.0, pixel_count=0)},
        warnings=("No frames were processed.",),
    )
    window.on_analysis_finished((report, AnalysisOptions()))
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *args: (str(output), "JSON Files (*.json)"),
    )

    window.export_json()
    assert output.is_file()
    assert '"schema_version": "1.0"' in output.read_text(encoding="utf-8")
    assert "Warning: No frames were processed." in window.log_output.toPlainText()
    assert window.metrics_table.item(0, 1).text() == "unknown"
    assert window.progress_label.text().endswith("0 findings.")
    assert window.status_label.text().startswith("WARNING")
    window.close()


def test_main_window_expected_source_error_is_concise(
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: errors.append(message),
    )
    window = MainWindow()

    window.on_analysis_error("No EXR files found in examples", "")

    log = window.log_output.toPlainText()
    assert "Error: No EXR files found in examples" in log
    assert "Traceback" not in log
    assert errors == ["No EXR files found in examples"]
    window.close()


def test_main_window_filters_findings_shows_details_and_sequences(
    tmp_path: Path,
    app,
) -> None:
    frame_a = tmp_path / "shot.1001.exr"
    frame_b = tmp_path / "shot.1003.exr"
    sequence = SequenceDescriptor(
        directory=tmp_path,
        prefix="shot.",
        suffix="",
        padding=4,
        frame_numbers=(1001, 1003),
        files=(frame_a, frame_b),
        missing_ranges=((1002, 1002),),
        padding_widths=(4,),
    )
    report = AnalysisReport(
        source=tmp_path,
        frames=(frame_a, frame_b),
        successful_frames=(frame_a,),
        failed_frames=(frame_b,),
        inspections=(),
        metrics_by_aov={},
        findings=(
            Finding(
                rule_id="read_frame",
                severity=Severity.ERROR,
                message="Could not read frame.",
                file=frame_b,
            ),
            Finding(
                rule_id="sequence_gap",
                severity=Severity.WARNING,
                message="Missing frame 1002.",
                file=tmp_path,
                metrics={"missing_frame": 1002},
            ),
            Finding(
                rule_id="constant_channel",
                severity=Severity.INFO,
                message="Channel is constant.",
                file=frame_a,
                aov="beauty",
                channel="R",
            ),
        ),
        sequence_check=SequenceCheckResult(source=tmp_path, sequences=(sequence,)),
    )
    window = MainWindow()

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.findings_table.rowCount() == 3
    assert window.findings_table.item(0, 0).text() == "error"
    assert window.findings_table.item(1, 0).text() == "warning"
    assert window.findings_table.item(2, 0).text() == "info"
    assert window.findings_table.currentRow() == 0
    assert "Could not read frame" in window.finding_details.toPlainText()
    assert window.findings_table.item(0, 5).text() == "shot.1003.exr"
    assert not window.findings_table.item(0, 0).icon().isNull()
    assert window.sequence_table.rowCount() == 1
    assert window.sequence_table.item(0, 0).text() == "shot.####.exr"
    assert window.sequence_table.item(0, 4).text() == "1002"

    window.severity_filter.setCurrentIndex(window.severity_filter.findData("warning"))
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "sequence_gap"

    window.severity_filter.setCurrentIndex(0)
    window.finding_search.setText("beauty")
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "constant_channel"

    window.finding_search.clear()
    window.failed_only_checkbox.setChecked(True)
    assert window.findings_table.rowCount() == 1
    assert window.findings_table.item(0, 1).text() == "read_frame"
    window.findings_table.setCurrentCell(0, 0)
    app.processEvents()
    assert "Could not read frame" in window.finding_details.toPlainText()
    assert "Verify that the file exists" in window.finding_details.toPlainText()
    assert window.copy_path_btn.isEnabled()
    window.copy_finding_path()
    assert QApplication.clipboard().text() == str(frame_b)
    window.close()


def test_main_window_rule_controls_sections_and_columns(app) -> None:
    window = MainWindow()

    assert not window.analysis_settings_section.is_expanded()
    assert window.rules_section.is_expanded()
    assert window.rule_checkboxes["nan_inf"].toolTip()
    assert window.source_edit.toolTip()
    assert window.inspect_btn.toolTip()
    assert window.export_json_btn.toolTip()
    assert window.analysis_settings_section.toggle_button.toolTip()
    assert window.log_section.toggle_button.toolTip()
    assert all(window.tabs.tabToolTip(index) for index in range(window.tabs.count()))
    for table in (
        window.findings_table,
        window.metrics_table,
        window.frame_table,
        window.technical_table,
        window.sequence_table,
        window.comparison_table,
    ):
        assert table.toolTip()
        assert all(
            table.horizontalHeaderItem(column).toolTip() for column in range(table.columnCount())
        )

    rec709_help = window.luminance_combo.toolTip()
    window.luminance_combo.setCurrentText("Rec.601")
    assert window.luminance_combo.toolTip() != rec709_help
    assert "0.299 R" in window.luminance_combo.toolTip()

    window.clear_rules()
    assert not any(checkbox.isChecked() for checkbox in window.rule_checkboxes.values())
    window.select_all_rules()
    assert all(checkbox.isChecked() for checkbox in window.rule_checkboxes.values())
    window.restore_rule_selection()
    assert window.rule_checkboxes["nan_inf"].isChecked()
    assert not window.rule_checkboxes["negative_values"].isChecked()

    window.frame_table.setColumnHidden(2, True)
    window.restore_table_columns(window.frame_table)
    assert not window.frame_table.isColumnHidden(2)

    window.analysis_settings_section.set_expanded(True)
    assert window.analysis_settings_section.is_expanded()
    assert not window.analysis_settings_section.content.isHidden()
    window.close()


def test_main_window_persists_last_analysis_preferences(tmp_path: Path, app) -> None:
    settings_path = tmp_path / "ui-settings.ini"
    source = tmp_path / "renders"
    source.mkdir()
    settings = QSettings(str(settings_path), QSettings.IniFormat)
    settings.clear()
    window = MainWindow(settings=settings)
    window.source_edit.setText(str(source))
    window.rules_edit.setText(str(tmp_path / "lighting.toml"))
    window.luminance_combo.setCurrentText("Rec.601")
    window.frame_pattern_edit.setText("shot.*.exr")
    window.recursive_checkbox.setChecked(True)
    window.max_depth_spin.setValue(3)
    window.allow_multiple_sequences_checkbox.setChecked(True)
    window.clear_rules()
    window.rule_checkboxes["nan_inf"].setChecked(True)
    window.analysis_settings_section.set_expanded(True)
    window.rules_section.set_expanded(False)
    window.log_section.set_expanded(True)
    window.close()

    restored = MainWindow(settings=QSettings(str(settings_path), QSettings.IniFormat))

    assert restored.source_edit.text() == str(source)
    assert restored.rules_edit.text().endswith("lighting.toml")
    assert restored.luminance_combo.currentText() == "Rec.601"
    assert restored.frame_pattern_edit.text() == "shot.*.exr"
    assert restored.recursive_checkbox.isChecked()
    assert restored.max_depth_spin.value() == 3
    assert restored.allow_multiple_sequences_checkbox.isChecked()
    assert restored.rule_checkboxes["nan_inf"].isChecked()
    assert not restored.rule_checkboxes["empty_aov"].isChecked()
    assert restored.analysis_settings_section.is_expanded()
    assert not restored.rules_section.is_expanded()
    assert restored.log_section.is_expanded()
    restored.close()


def test_main_window_compacts_paths_compares_frames_and_explains_standalone_files(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame_a = tmp_path / "beauty.exr"
    frame_b = tmp_path / "beauty_no_light.exr"
    report = AnalysisReport(
        source=tmp_path,
        frames=(frame_a, frame_b),
        inspections=(),
        metrics_by_aov={"beauty": MetricSet(0.625, 1.5, 2.0, pixel_count=8)},
        sequence_check=SequenceCheckResult(
            source=tmp_path,
            unnumbered_files=(frame_a, frame_b),
        ),
        frame_metrics={
            frame_a: {"beauty": MetricSet(0.5, 1.0, 1.5, pixel_count=4)},
            frame_b: {"beauty": MetricSet(0.75, 2.0, 2.0, pixel_count=4)},
        },
        source_kind=SourceKind.COMPARISON_SET,
        series_metrics_by_aov={
            "beauty": SeriesMetricSet(
                frame_count=2,
                median_luminance=1.5,
                mad_luminance=0.5,
                min_luminance=1.0,
                max_luminance=2.0,
                max_frame_delta=1.0,
                max_frame_delta_from=frame_a,
                max_frame_delta_to=frame_b,
            )
        },
    )
    opened = []
    monkeypatch.setattr(
        "aovguard.ui.QDesktopServices.openUrl",
        lambda url: opened.append(url) or True,
    )
    window = MainWindow()

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.tabs.currentIndex() == TAB_METRICS
    assert window.frame_table.item(0, 0).text() == "beauty.exr"
    assert window.frame_table.item(0, 0).toolTip() == str(frame_a)
    assert window.frame_table.item(0, 8).text() == "-33.33%"
    assert window.frame_table.item(1, 8).text() == "+33.33%"
    assert window.frame_table.item(1, 9).text() == "+100.00%"
    assert not window.series_chart.isHidden()
    assert window.series_chart.aov_name == "beauty"
    assert window.series_chart.sample_count == 2
    assert window.series_aov_combo.currentText() == "beauty"
    window.series_mode_combo.setCurrentIndex(window.series_mode_combo.findData("previous_delta"))
    assert [value for _path, value in window.series_chart.samples] == [0.0, 1.0]
    window.series_mode_combo.setCurrentIndex(window.series_mode_combo.findData("previous_percent"))
    assert [value for _path, value in window.series_chart.samples] == [0.0, 100.0]
    assert not window.series_mode_explanation.isHidden()
    assert "new activity" in window.series_mode_explanation.text()
    window.series_chart.resize(800, 180)
    assert not window.series_chart.grab().isNull()
    window.locate_frame_from_chart(frame_b)
    assert window.tabs.currentIndex() == TAB_FRAMES
    assert window.frame_table.currentItem().data(int(Qt.UserRole) + 1) == str(frame_b)
    assert window.tabs.tabText(TAB_SEQUENCES) == "Discovery | 2 samples"
    assert (
        "Comparison set: 2 independent EXR files analyzed"
        in window.sequence_panel.empty_label.text()
    )
    window.frame_table.cellDoubleClicked.emit(0, 0)
    assert Path(opened[0].toLocalFile()).resolve() == tmp_path.resolve()
    window.close()


def test_main_window_exports_html(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    window.report = AnalysisReport(
        source=tmp_path,
        frames=(),
        inspections=(),
        metrics_by_aov={},
    )
    output = tmp_path / "report.html"
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *args: (str(output), "HTML Files (*.html)"),
    )

    window.export_html()

    assert output.is_file()
    assert "AOVGuard Analysis Report" in output.read_text(encoding="utf-8")
    assert "HTML report written" in window.log_output.toPlainText()
    window.close()


def test_main_window_classifies_unknown_aov_only_after_confirmation(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection = FileInspection(
        path=Path("custom.exr"),
        width=1,
        height=1,
        channels=("RendererData.foo", "RendererData.bar"),
        aovs=(
            AOVDescriptor(
                "RendererData",
                ("RendererData.foo", "RendererData.bar"),
                AOVCategory.UNKNOWN,
                "insufficient_evidence",
            ),
        ),
    )
    preset_path = tmp_path / "rules.toml"
    window = MainWindow()
    window.rules_edit.setText(str(preset_path))
    window._set_classifiable_aovs((inspection,))
    window.aov_category_combo.setCurrentText("ignored")

    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.No,
    )
    window.save_aov_category()
    assert not preset_path.exists()

    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.information",
        lambda *_args, **_kwargs: QMessageBox.Ok,
    )
    window.save_aov_category()

    assert load_rule_preset(preset_path).aov_category_overrides == {
        "RendererData": AOVCategory.IGNORED,
    }
    assert "Saved AOV category override" in window.log_output.toPlainText()
    window.close()


def test_main_window_export_error_is_concise_and_logs_traceback(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = MainWindow()
    window.report = AnalysisReport(
        source=tmp_path,
        frames=(),
        inspections=(),
        metrics_by_aov={},
    )
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "blocked.json"), "JSON Files (*.json)"),
    )
    monkeypatch.setattr(
        "aovguard.ui.write_analysis_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )
    messages: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: messages.append(message) or QMessageBox.Ok,
    )

    window.export_json()

    assert messages == ["The JSON report could not be written: denied"]
    assert "Traceback" in window.log_output.toPlainText()
    window.close()


def test_main_window_multiple_metrics_do_not_leave_controls_disabled(app) -> None:
    window = MainWindow()
    window.set_busy(True)
    report = AnalysisReport(
        source=Path("renders"),
        frames=(Path("shot.1001.exr"),),
        inspections=(),
        metrics_by_aov={
            name: MetricSet(1.0, float(index), float(index), pixel_count=4)
            for index, name in enumerate(
                ("albedo", "beauty", "diffuse", "emission", "specular"),
                start=1,
            )
        },
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.metrics_table.rowCount() == 5
    assert window.source_edit.isEnabled()
    assert window.analyze_btn.isEnabled()
    assert window.export_json_btn.isEnabled()
    assert window.export_html_btn.isEnabled()
    assert "5 color AOVs analyzed" in window.progress_label.text()
    window.close()


def test_main_window_handles_cancelled_analysis(app) -> None:
    window = MainWindow()
    window.set_busy(True)

    window.on_analysis_cancelled()

    assert window.analyze_btn.isEnabled()
    assert not window.cancel_btn.isEnabled()
    assert window.status_label.text() == "CANCELLED"
    assert window.progress_label.text() == "Analysis cancelled after the current frame."
    assert "Analysis cancelled" in window.log_output.toPlainText()
    window.close()


def test_main_window_recovers_when_result_display_fails(
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: errors.append(message),
    )
    window = MainWindow()
    window.set_busy(True)

    def fail_display(_report: AnalysisReport) -> None:
        raise RuntimeError("table rendering failed")

    monkeypatch.setattr(window, "_display_analysis_results", fail_display)
    report = AnalysisReport(
        source=Path("renders"),
        frames=(),
        inspections=(),
        metrics_by_aov={},
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.source_edit.isEnabled()
    assert window.analyze_btn.isEnabled()
    assert window.export_json_btn.isEnabled()
    assert window.export_html_btn.isEnabled()
    assert window.progress_label.text() == (
        "Analysis completed, but results could not be displayed."
    )
    assert "table rendering failed" in window.log_output.toPlainText()
    assert errors == ["table rendering failed"]
    window.close()


def test_main_window_compares_current_report_with_json_baseline(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "metadata": {"source": "baseline", "status": "pass"},
                "metrics_by_aov": {
                    "beauty": {
                        "avg_luminance": 1.0,
                        "non_black_ratio": 1.0,
                        "max_luminance": 1.0,
                    }
                },
                "findings": [],
            }
        ),
        encoding="utf-8",
    )
    window = MainWindow()
    window.report = AnalysisReport(
        source=tmp_path / "candidate.exr",
        frames=(),
        inspections=(),
        metrics_by_aov={
            "beauty": MetricSet(1.0, 2.0, 2.0, pixel_count=1),
        },
    )
    window.options = AnalysisOptions()
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(baseline), "JSON Files (*.json)"),
    )

    window.compare_baseline_json()

    assert window.tabs.currentIndex() == TAB_COMPARISON
    assert window.comparison_table.rowCount() == 1
    assert window.comparison_table.item(0, 0).text() == "beauty"
    assert window.comparison_table.item(0, 1).text() == "changed"
    assert window.comparison_table.item(0, 2).text() == "+1.000000"
    assert "1 changed" in window.tabs.tabText(TAB_COMPARISON)
    assert "1 changed AOVs" in window.comparison_summary_label.text()
    window.close()


def test_main_window_handles_guard_cancel_and_export_error_paths(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.warning",
        lambda _parent, _title, message: messages.append(message) or QMessageBox.Ok,
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda _parent, _title, message: messages.append(message) or QMessageBox.Ok,
    )
    window = MainWindow()

    window.cancel_analysis()
    window.export_json()
    window.export_html()
    window.compare_baseline_json()
    window.save_aov_category()
    window.update_series_chart(-1)
    window._display_series_chart("")
    assert window._source() is None
    window.source_edit.setText(str(tmp_path / "missing.exr"))
    assert window._source() is None

    window.report = AnalysisReport(source=tmp_path, frames=(), inspections=(), metrics_by_aov={})
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    window.export_json()
    window.export_html()
    window.compare_baseline_json()

    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "report.html"), "HTML Files (*.html)"),
    )
    monkeypatch.setattr(
        "aovguard.ui.write_analysis_html",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("html denied")),
    )
    window.export_html()
    assert "The HTML report could not be written: html denied" in messages

    window.on_analysis_error("decode failed", "technical traceback")
    assert "technical traceback" in window.log_output.toPlainText()
    assert window.status_label.text() == "FAIL | ANALYSIS ERROR"
    window.close()


def test_main_window_logs_preset_write_failure_without_mutating_selection(
    tmp_path: Path,
    app,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection = FileInspection(
        path=tmp_path / "custom.exr",
        width=1,
        height=1,
        channels=("vendor.payload",),
        aovs=(
            AOVDescriptor(
                "vendor",
                ("vendor.payload",),
                AOVCategory.UNKNOWN,
                "insufficient_evidence",
            ),
        ),
    )
    window = MainWindow()
    window._set_classifiable_aovs((inspection,))
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(tmp_path / "rules.toml"), "Rule Presets (*.toml)"),
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.question",
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda *_args, **_kwargs: QMessageBox.Ok,
    )
    monkeypatch.setattr(
        "aovguard.ui.save_aov_category_override",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("preset denied")),
    )

    window.save_aov_category()

    assert window.rules_edit.text() == ""
    assert "preset denied" in window.log_output.toPlainText()
    assert "Traceback" in window.log_output.toPlainText()
    window.close()


def test_main_window_chart_marks_matching_frame_errors_and_clears_missing_rows(app) -> None:
    frames = tuple(Path(f"shot.{number}.exr") for number in (1001, 1002, 1003))
    metrics = {
        frame: {"beauty": MetricSet(1.0, value, value, pixel_count=1)}
        for frame, value in zip(frames, (1.0, 1.1, 8.0))
    }
    report = AnalysisReport(
        source=Path("renders"),
        frames=frames,
        inspections=(),
        metrics_by_aov={"beauty": MetricSet(1.0, 3.36, 8.0, pixel_count=3)},
        frame_metrics=metrics,
        series_metrics_by_aov={
            "beauty": SeriesMetricSet(
                frame_count=3,
                median_luminance=1.1,
                mad_luminance=0.1,
                min_luminance=1.0,
                max_luminance=8.0,
                max_frame_delta=6.9,
                outlier_frames=(frames[2],),
            )
        },
        findings=(
            Finding(
                "frame_integrity",
                Severity.ERROR,
                "corrupt frame",
                file=frames[2],
                aov="beauty",
            ),
            Finding("warning", Severity.WARNING, "not an error", file=frames[0]),
            Finding("other", Severity.ERROR, "other AOV", file=frames[1], aov="diffuse"),
        ),
    )
    window = MainWindow()
    window.report = report
    window.series_aov_combo.addItem("beauty")
    window._display_series_chart("beauty")

    assert window.series_chart.sample_count == 3
    assert frames[2] in window.series_chart._issues
    window.metrics_table.setRowCount(1)
    window.update_series_chart(0)
    assert window.series_chart.sample_count == 0
    window.close()


def test_main_window_outlier_view_navigates_to_exact_frame(app) -> None:
    frames = tuple(Path(f"shot.{number}.exr") for number in (1001, 1002, 1003, 1004))
    values = (1.0, 1.0, 1.0, 9.0)
    report = AnalysisReport(
        source=Path("renders"),
        frames=frames,
        inspections=(),
        metrics_by_aov={"beauty": MetricSet(1.0, 3.0, 9.0, pixel_count=4)},
        frame_metrics={
            frame: {"beauty": MetricSet(1.0, value, value, pixel_count=1)}
            for frame, value in zip(frames, values)
        },
        series_metrics_by_aov={
            "beauty": SeriesMetricSet(
                frame_count=4,
                median_luminance=1.0,
                mad_luminance=0.0,
                min_luminance=1.0,
                max_luminance=9.0,
                max_frame_delta=8.0,
                max_frame_delta_from=frames[2],
                max_frame_delta_to=frames[3],
                outlier_frames=(frames[3],),
            )
        },
    )
    window = MainWindow()

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.outlier_table.rowCount() == 1
    assert window.tabs.tabText(TAB_OUTLIERS) == "Outliers (1)"
    assert window.outlier_table.item(0, 0).data(int(Qt.UserRole) + 1) == str(frames[3])
    assert window.locate_outlier_btn.isEnabled()
    window.locate_outlier_btn.click()
    assert window.tabs.currentIndex() == TAB_FRAMES
    assert window.frame_table.currentItem().data(int(Qt.UserRole) + 1) == str(frames[3])
    window.tabs.setCurrentIndex(TAB_OUTLIERS)
    window.outlier_table.cellDoubleClicked.emit(0, 0)
    assert window.tabs.currentIndex() == TAB_FRAMES
    window.close()


def test_main_window_restores_invalid_preferences_to_safe_defaults(app) -> None:
    settings = QSettings("AOVGuardTests", "InvalidPreferences")
    settings.clear()
    settings.setValue("analysis/source_mode", "unsupported")
    settings.setValue("analysis/custom_weights", "bad,weights")

    window = MainWindow(settings=settings)

    assert window.source_mode_buttons[SourceMode.AUTO].isChecked()
    assert tuple(spin.value() for spin in window.custom_weight_spins) == pytest.approx(
        (0.2126, 0.7152, 0.0722)
    )
    window.close()
    settings.clear()
