"""Report publication preserves old reports and input data on failure."""

import errno
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest

from aovguard import cli
from aovguard.analysis_core import AOVResult, write_csv, write_json
from aovguard.core.models import AnalysisOptions, AnalysisReport, Finding, Severity
from aovguard.io import output
from aovguard.io.output import atomic_text_writer, validate_output_paths
from aovguard.reports.comparison import ReportComparison, write_comparison_json
from aovguard.reports.html_report import write_analysis_html
from aovguard.reports.json_report import write_analysis_json


def _report(tmp_path):
    frame = tmp_path / "shot.0001.exr"
    return AnalysisReport(source=frame, frames=(frame,), inspections=(), metrics_by_aov={})


def _comparison():
    return ReportComparison("", "", "pass", "pass", (), (), ())


def test_atomic_publish_keeps_old_file_visible_until_commit_and_preserves_mode(tmp_path):
    destination = tmp_path / "result.json"
    destination.write_text("old")
    mode = stat.S_IMODE(destination.stat().st_mode)
    with atomic_text_writer(destination) as stream:
        stream.write('résultat\n{"complete": true}')
        stream.flush()
        assert destination.read_text() == "old"
        (temporary,) = tmp_path.glob(".result.json.*.tmp")
        assert temporary.parent == destination.parent
    assert destination.read_text(encoding="utf-8") == 'résultat\n{"complete": true}'
    assert stat.S_IMODE(destination.stat().st_mode) == mode
    assert not list(tmp_path.glob("*.tmp"))


def test_atomic_publish_creates_missing_parents_and_no_temp_remains(tmp_path):
    path = tmp_path / "new" / "result"
    with atomic_text_writer(path) as stream:
        stream.write("complete")
    assert path.read_bytes() == b"complete"
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize(
    "error", [OSError(errno.ENOSPC, "disk full"), KeyboardInterrupt(), SystemExit(130)]
)
@pytest.mark.parametrize("exists", [False, True])
def test_partial_write_or_interrupt_never_publishes_incomplete_report(tmp_path, error, exists):
    path = tmp_path / "result.json"
    if exists:
        path.write_bytes(b"original report")
    with pytest.raises(type(error)):
        with atomic_text_writer(path) as stream:
            stream.write('{"partial":')
            raise error
    assert path.read_bytes() == b"original report" if exists else not path.exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("stage", ["mkstemp", "fdopen", "fsync", "replace"])
def test_io_failures_keep_destination_and_clean_owned_resources(tmp_path, monkeypatch, stage):
    path = tmp_path / "result.html"
    path.write_text("original")
    descriptor = None
    original_mkstemp = output.tempfile.mkstemp

    def track_temporary(**kwargs):
        nonlocal descriptor
        descriptor, name = original_mkstemp(**kwargs)
        return descriptor, name

    def fail(*args, **kwargs):
        raise PermissionError(f"{stage} denied")

    monkeypatch.setattr(output.tempfile, "mkstemp", track_temporary)
    monkeypatch.setattr(output.tempfile if stage == "mkstemp" else output.os, stage, fail)
    with pytest.raises(PermissionError, match=f"{stage} denied"):
        with atomic_text_writer(path) as stream:
            stream.write("replacement")
    assert path.read_text() == "original"
    assert not list(tmp_path.glob("*.tmp"))
    if descriptor is not None:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_cleanup_failure_keeps_original_exception_and_names_leftover(tmp_path, monkeypatch):
    original_unlink = Path.unlink

    def deny_unlink(path, *args, **kwargs):
        raise PermissionError("temporary locked")

    monkeypatch.setattr(Path, "unlink", deny_unlink)
    with pytest.raises(RuntimeError, match="serialization failed") as error:
        with atomic_text_writer(tmp_path / "result.json") as stream:
            stream.write("partial")
            raise RuntimeError("serialization failed")
    (leftover,) = tmp_path.glob("*.tmp")
    assert str(leftover) in error.value.__notes__[0]
    original_unlink(leftover)


def test_descriptor_cleanup_failure_does_not_mask_fdopen_error(tmp_path, monkeypatch):
    close = output.os.close

    def bad_close(descriptor):
        close(descriptor)
        raise OSError("close failed")

    def bad_open(*args, **kwargs):
        raise ValueError("open failed")

    monkeypatch.setattr(output.os, "close", bad_close)
    monkeypatch.setattr(output.os, "fdopen", bad_open)
    with pytest.raises(ValueError, match="open failed") as error:
        with atomic_text_writer(tmp_path / "result.json"):
            pytest.fail("Unreachable")
    assert "close failed" in error.value.__notes__[0]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("name", ["input.exr", "input.EXR"])
def test_exr_destinations_are_rejected_even_when_they_do_not_exist(tmp_path, name):
    with pytest.raises(ValueError, match="must not be an EXR"):
        with atomic_text_writer(tmp_path / name):
            pytest.fail("Must not start writing")
    assert not list(tmp_path.iterdir())


def test_directories_readonly_files_and_nonregular_targets_are_rejected(tmp_path, monkeypatch):
    with pytest.raises(ValueError, match="regular file"):
        validate_output_paths((tmp_path,))
    path = tmp_path / "readonly.json"
    path.write_bytes(b"keep")
    path.chmod(stat.S_IREAD)
    try:
        with pytest.raises(PermissionError, match="read-only"):
            validate_output_paths((path,))
        assert path.read_bytes() == b"keep"
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)
    monkeypatch.setattr(output.stat, "S_ISREG", lambda mode: False)
    with pytest.raises(ValueError, match="regular file"):
        validate_output_paths((path,))


def test_symbolic_link_destinations_are_rejected(tmp_path, monkeypatch):
    target = tmp_path / "baseline.json"
    target.write_text("keep")
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(target)
    except OSError:
        # Unprivileged Windows may forbid symlink creation. Exercise the
        # rejection branch without requiring elevated permissions there.
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == alias or original(path))
    with pytest.raises(ValueError, match="symbolic link"):
        validate_output_paths((alias,))
    assert target.read_text() == "keep"


def test_input_aliases_and_duplicate_output_paths_are_rejected(tmp_path):
    source = tmp_path / "input.json"
    source.write_bytes(b"input")
    alias = tmp_path / "hardlink.json"
    alias.hardlink_to(source)
    for candidate in (source, tmp_path / "sub" / ".." / "input.json", alias):
        with pytest.raises(ValueError, match="overwrite an input"):
            validate_output_paths((candidate,), protected_paths=(source,))
    for candidate in (source, alias):
        with pytest.raises(ValueError, match="different files"):
            validate_output_paths((source, candidate))
    assert source.read_bytes() == alias.read_bytes() == b"input"


def test_stat_and_samefile_access_errors_are_not_ignored(tmp_path, monkeypatch):
    path = tmp_path / "output.json"
    path.write_text("old")

    def deny(*args, **kwargs):
        raise PermissionError("access denied")

    with monkeypatch.context() as context:
        context.setattr(Path, "samefile", deny)
        with pytest.raises(PermissionError, match="access denied"):
            validate_output_paths((path,), protected_paths=(tmp_path / "input.json",))
    with monkeypatch.context() as context:
        context.setattr(Path, "stat", deny)
        with pytest.raises(PermissionError, match="access denied"):
            validate_output_paths((path,))


def test_destination_is_revalidated_before_commit(tmp_path):
    protected = tmp_path / "preset.json"
    protected.write_bytes(b"preset")
    destination = tmp_path / "report.json"
    with pytest.raises(ValueError, match="overwrite an input"):
        with atomic_text_writer(destination, protected_paths=(protected,)) as stream:
            stream.write("new report")
            destination.hardlink_to(protected)
    assert protected.read_bytes() == destination.read_bytes() == b"preset"
    assert not list(tmp_path.glob("*.tmp"))


def test_simultaneous_writers_publish_whole_documents(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("original")
    barrier = Barrier(3)
    documents = ('{"first": "' + "á" * 10000 + '"}', '{"second": "' + "ß" * 10000 + '"}')

    def publish(text):
        with atomic_text_writer(path) as stream:
            stream.write(text)
            stream.flush()
            barrier.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(publish, text) for text in documents]
        assert path.read_text() == "original"
        barrier.wait(timeout=5)
        committed = []
        for document, future in zip(documents, futures, strict=True):
            try:
                future.result(timeout=5)
            except PermissionError:
                # Windows can reject a contending replace; a writer must
                # report that failure, not truncate or merge either payload.
                if os.name != "nt":
                    raise
            else:
                committed.append(document)
    assert path.read_text(encoding="utf-8") in (committed or ["original"])
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("format", ["json", "html", "comparison", "legacy_json", "csv"])
def test_all_report_writers_use_atomic_replacement(tmp_path, monkeypatch, format):
    path = tmp_path / "report.txt"
    path.write_bytes(b"old complete report")
    report = _report(tmp_path)
    writers = {
        "json": lambda: write_analysis_json(report, path),
        "html": lambda: write_analysis_html(report, path),
        "comparison": lambda: write_comparison_json(_comparison(), path),
        "legacy_json": lambda: write_json([], path),
        "csv": lambda: write_csv([AOVResult("test", "Active", 1, 2, 3)], path),
    }
    with monkeypatch.context() as context:

        def deny_replace(*args):
            raise PermissionError("destination locked")

        context.setattr(output.os, "replace", deny_replace)
        with pytest.raises(PermissionError, match="destination locked"):
            writers[format]()
    assert path.read_bytes() == b"old complete report"
    assert not list(tmp_path.glob("*.tmp"))
    writers[format]()
    text = path.read_text(encoding="utf-8")
    assert text != "old complete report"
    if format in {"json", "comparison", "legacy_json"}:
        assert isinstance(json.loads(text), dict)
    if format == "csv":
        assert b"\r\r\n" not in path.read_bytes()


def test_serialization_failure_does_not_truncate_previous_json(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("old report")
    report = replace(
        _report(tmp_path),
        findings=(
            Finding("test", Severity.INFO, "bad payload", metrics={"unsupported": object()}),
        ),
    )
    with pytest.raises(TypeError):
        write_analysis_json(report, path)
    assert path.read_text() == "old report"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("writer", [write_analysis_json, write_analysis_html])
def test_canonical_api_protects_discovered_frames_even_through_hardlink(tmp_path, writer):
    source = tmp_path / "shot.0001.exr"
    source.write_bytes(b"render data")
    alias = tmp_path / "alias.json"
    alias.hardlink_to(source)
    with pytest.raises(ValueError, match="overwrite an input"):
        writer(_report(tmp_path), alias)
    assert source.read_bytes() == alias.read_bytes() == b"render data"


@pytest.mark.parametrize(
    "case",
    ["exr", "preset", "duplicate", "baseline", "candidate", "legacy_config", "legacy_duplicate"],
)
def test_cli_refuses_collisions_before_reading_inputs(tmp_path, monkeypatch, capsys, case):
    source = tmp_path / "source.exr"
    source.write_bytes(b"render")
    config = tmp_path / "preset.json"
    config.write_bytes(b"preset")
    candidate = tmp_path / "candidate.json"
    candidate.write_bytes(b"candidate")
    same = str(tmp_path / "output.json")
    args = {
        "exr": ["analyze", str(source), "--json", str(source)],
        "preset": ["analyze", str(source), "--rules-config", str(config), "--json", str(config)],
        "duplicate": ["analyze", str(source), "--json", same, "--html", same],
        "baseline": ["compare-reports", str(config), str(candidate), "--json", str(config)],
        "candidate": ["compare-reports", str(config), str(candidate), "--json", str(candidate)],
        "legacy_config": [
            "analyze-simple",
            str(tmp_path),
            "--config",
            str(config),
            "--csv",
            str(config),
        ],
        "legacy_duplicate": ["analyze-multilayer", str(tmp_path), "--json", same, "--csv", same],
    }[case]
    monkeypatch.setattr(cli, "analyze_backend", lambda *a, **kw: pytest.fail("Must not decode"))
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 1
    assert "error:" in capsys.readouterr().err
    assert source.read_bytes() == b"render" and config.read_bytes() == b"preset"
    assert candidate.read_bytes() == b"candidate" and not Path(same).exists()


@pytest.mark.parametrize("command", ["analyze", "compare-reports"])
@pytest.mark.parametrize("interrupt", [False, True])
def test_cli_export_failure_is_reported_without_success_or_traceback(
    tmp_path,
    monkeypatch,
    capsys,
    command,
    interrupt,
):
    path = tmp_path / "report.json"
    path.write_bytes(b"old report")
    monkeypatch.setattr(cli, "analyze_backend", lambda *a, **kw: _report(tmp_path))
    monkeypatch.setattr(cli, "compare_report_files", lambda *a, **kw: _comparison())

    def fail(*args):
        if interrupt:
            raise KeyboardInterrupt()
        raise PermissionError("locked")

    monkeypatch.setattr(output.os, "replace", fail)
    args = [command, str(tmp_path / "input")]
    if command == "compare-reports":
        args.append(str(tmp_path / "candidate"))
    args += ["--json", str(path)]
    if interrupt:
        assert cli.main(args) == 130
    else:
        with pytest.raises(SystemExit) as error:
            cli.main(args)
        assert error.value.code == 1
    messages = capsys.readouterr()
    assert "written to" not in messages.out and "Traceback" not in messages.err
    assert path.read_bytes() == b"old report"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("format", ["json", "html"])
@pytest.mark.parametrize("target", ["source", "current_preset", "previous_preset", "baseline"])
def test_gui_export_preserves_inputs_and_analysis_after_invalid_destination(
    tmp_path,
    qt_application,
    monkeypatch,
    format,
    target,
):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from aovguard.ui import MainWindow

    report = _report(tmp_path)
    report.source.write_bytes(b"render")
    preset = tmp_path / "rules.json"
    preset.write_text('{"rules": {}}')
    previous_preset = tmp_path / "previous.json"
    previous_preset.write_text('{"rules": {}}')
    baseline = tmp_path / "baseline.json"
    write_analysis_json(report, baseline, options=AnalysisOptions())
    window = MainWindow(settings=QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    messages = []
    monkeypatch.setattr(
        "aovguard.ui.QMessageBox.critical",
        lambda parent, title, text: messages.append(text) or QMessageBox.Ok,
    )
    try:
        window.source_edit.setText(str(report.source))
        window.rules_edit.setText(str(previous_preset))
        # Exercise the start path without starting an unrelated decoder job.
        monkeypatch.setattr(window.analysis_controller, "start", lambda *a, **kw: False)
        window.start_analysis()
        window.on_analysis_finished((report, AnalysisOptions()))
        window.rules_edit.setText(str(preset))
        monkeypatch.setattr(
            "aovguard.ui.QFileDialog.getOpenFileName",
            lambda *a, **kw: (str(baseline), "JSON Files (*.json)"),
        )
        window.compare_baseline_json()
        assert not messages
        destination = {
            "source": report.source,
            "current_preset": preset,
            "previous_preset": previous_preset,
            "baseline": baseline,
        }[target]
        before = destination.read_bytes()
        monkeypatch.setattr(
            "aovguard.ui.QFileDialog.getSaveFileName", lambda *a, **kw: (str(destination), "")
        )
        getattr(window, f"export_{format}")()
        assert messages and "could not be written" in messages[0]
        assert destination.read_bytes() == before
        assert window.report is report
        assert window.export_json_btn.isEnabled() and window.export_html_btn.isEnabled()
        assert "written to" not in window.log_output.toPlainText()
        assert not list(tmp_path.glob("*.tmp"))
    finally:
        window.close()
        qt_application.processEvents()


def test_gui_can_retry_after_locked_destination_without_reanalysis(
    tmp_path, qt_application, monkeypatch
):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QMessageBox

    from aovguard.ui import MainWindow

    report = _report(tmp_path)
    destination = tmp_path / "report.json"
    destination.write_bytes(b"old report")
    window = MainWindow(settings=QSettings(str(tmp_path / "preferences.ini"), QSettings.IniFormat))
    monkeypatch.setattr(
        "aovguard.ui.QFileDialog.getSaveFileName", lambda *a, **kw: (str(destination), "")
    )
    monkeypatch.setattr("aovguard.ui.QMessageBox.critical", lambda *a: QMessageBox.Ok)
    try:
        window.on_analysis_finished((report, AnalysisOptions()))
        with monkeypatch.context() as context:

            def deny_replace(*args):
                raise PermissionError("locked")

            context.setattr(output.os, "replace", deny_replace)
            window.export_json()
        assert destination.read_bytes() == b"old report"
        assert window.report is report
        assert "JSON export failed" in window.log_output.toPlainText()
        window.export_json()
        assert json.loads(destination.read_text(encoding="utf-8"))["schema_version"] == "1.2"
        assert "JSON report written to" in window.log_output.toPlainText()
    finally:
        window.close()
        qt_application.processEvents()
