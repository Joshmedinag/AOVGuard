"""Acceptance-harness regressions using isolated settings and temporary inputs."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    SourceKind,
    SourceMode,
)
from aovguard.reports.json_report import build_analysis_report_payload, write_analysis_json
from aovguard.rules.builtin import default_rule_definitions, effective_rule_parameters
from scripts import verify_gui_sequence as gui


def _options(**changes: Any) -> AnalysisOptions:
    values: dict[str, Any] = {
        "enabled_rules": tuple(rule.id for rule in default_rule_definitions() if rule.enabled),
        "source_mode": SourceMode.SEQUENCE,
        "isolate_frames": True,
        "frame_pattern": "frame.*.exr",
        "max_frames": 3,
        "max_memory_mb": 512.0,
        "frame_timeout_seconds": 20.0,
        "expected_frame_range": (1, 3),
    }
    values.update(changes)
    return AnalysisOptions(**values)


def _baseline(source: Path, options: AnalysisOptions | None = None) -> dict[str, Any]:
    options = options or _options()
    rules = tuple(
        {
            "id": rule.id,
            "enabled": rule.id in (options.enabled_rules or ()),
            "severity": rule.severity.value,
            "parameters": effective_rule_parameters(rule),
            "supported_aov_types": sorted(category.value for category in rule.supported_aov_types),
        }
        for rule in default_rule_definitions()
    )
    report = AnalysisReport(
        source=source,
        frames=(),
        inspections=(),
        metrics_by_aov={},
        source_kind=SourceKind.NUMBERED_SEQUENCE,
        effective_rules=rules,
    )
    return build_analysis_report_payload(report, options=options)


@pytest.fixture
def window(qt_application: Any, tmp_path: Path):
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QSettings

    from aovguard.ui import MainWindow

    result = MainWindow(
        settings=QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    )
    yield result
    result.close()
    qt_application.processEvents()


def test_stable_payload_excludes_only_declared_volatile_diagnostics() -> None:
    original = {
        "metadata": {"generated_utc": "today", "status": "warning"},
        "frame_execution": {
            "a.exr": {"elapsed_seconds": 9, "worker_pid": 12, "status": "completed"}
        },
        "findings": [{"metrics": {"elapsed_seconds": 9, "worker_pid": 12}}],
    }
    normalized = gui.stable_payload(original)
    assert normalized == {
        "metadata": {"status": "warning"},
        "frame_execution": {"a.exr": {"status": "completed"}},
        "findings": [{"metrics": {"elapsed_seconds": 9, "worker_pid": 12}}],
    }
    assert "generated_utc" in original["metadata"]


def test_exact_json_does_not_confuse_boolean_numeric_evidence() -> None:
    assert not gui.same_json({"value": True}, {"value": 1})
    assert not gui.same_json({"value": 1.0}, {"value": 1})


def test_help_and_requirements_work_without_qt_and_with_optimized_python(tmp_path: Path) -> None:
    script = Path(gui.__file__).resolve()
    code = """
import importlib.abc, runpy, sys
class DenyQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('PySide6'):
            raise ImportError('Qt deliberately unavailable')
sys.meta_path.insert(0, DenyQt())
sys.argv = [sys.argv[1], '--help']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    help_result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(script)], capture_output=True, text=True, timeout=15
    )
    assert help_result.returncode == 0
    assert "--check-cancellation" in help_result.stdout
    optimized = subprocess.run(
        [
            sys.executable,
            "-O",
            "-B",
            "-c",
            "from scripts.verify_gui_sequence import require; require(False, 'must reject')",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert optimized.returncode != 0
    assert "must reject" in optimized.stderr


@pytest.mark.parametrize("target", ["inside", "same", "existing", "input_file"])
def test_output_directory_cannot_overwrite_or_enter_inputs(tmp_path: Path, target: str) -> None:
    source = tmp_path / "renders"
    source.mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text("keep", encoding="utf-8")
    existing = tmp_path / "existing"
    existing.mkdir()
    choices = {
        "inside": source / "verification",
        "same": source,
        "existing": existing,
        "input_file": baseline,
    }
    with pytest.raises(gui.VerificationError):
        gui.prepare_output_directory(choices[target], source, baseline)
    assert baseline.read_text(encoding="utf-8") == "keep"
    assert not (source / "verification").exists()


def test_output_resolves_source_aliases_before_creation(tmp_path: Path, monkeypatch: Any) -> None:
    source = tmp_path / "renders"
    source.mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text("keep", encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(source, target_is_directory=True)
    except OSError:
        original = Path.resolve
        monkeypatch.setattr(
            Path,
            "resolve",
            lambda path, *args, **kwargs: (
                source / "output" if path == alias / "output" else original(path, *args, **kwargs)
            ),
        )
    with pytest.raises(gui.VerificationError, match="outside"):
        gui.prepare_output_directory(alias / "output", source, baseline)
    assert not (source / "output").exists()


def test_new_output_directory_is_created_outside_inputs(tmp_path: Path) -> None:
    source = tmp_path / "renders"
    source.mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text("keep", encoding="utf-8")
    output = gui.prepare_output_directory(tmp_path / "new" / "verification", source, baseline)
    assert output.is_dir()
    assert not list(output.iterdir())


@pytest.mark.parametrize(
    "changes,expected_error",
    [
        ({"max_memory_mb": 512.5}, "integer MiB"),
        ({"max_memory_mb": 1_000_001.0}, "max_memory_mb"),
        ({"max_frames": 1_000_001}, "max_frames"),
        ({"max_depth": None}, "unlimited max_depth"),
        ({"max_depth": 21}, "max_depth"),
        ({"frame_timeout_seconds": 0.123}, "frame_timeout_seconds"),
        ({"frame_timeout_seconds": 86401.0}, "frame_timeout_seconds"),
        ({"luminance_weights": (0.11111, 0.22222, 0.66667)}, "luminance_weights"),
        ({"luminance_weights": (11.0, 1.0, 1.0)}, "luminance_weights"),
        ({"non_black_threshold": 0.001}, "non_black_threshold"),
        ({"expected_frame_range": (1, 1_000_001)}, "expected_frame_range"),
    ],
)
def test_gui_precision_or_spin_limits_are_rejected_before_analysis(
    window: Any, tmp_path: Path, changes: dict[str, Any], expected_error: str
) -> None:
    baseline = _baseline(tmp_path, _options(**changes))
    with pytest.raises(gui.VerificationError, match=expected_error):
        gui.configure_window(window, baseline, None)
    assert not window.analysis_controller.has_job


def test_named_acescg_preserves_full_precision(window: Any, tmp_path: Path) -> None:
    from aovguard.core.luminance import ACESCG

    baseline = _baseline(tmp_path, _options(luminance_weights=(ACESCG.r, ACESCG.g, ACESCG.b)))
    actual = gui.configure_window(window, baseline, None)
    assert actual.luminance_weights == (ACESCG.r, ACESCG.g, ACESCG.b)
    assert window.luminance_combo.currentText() == "ACEScg"


def test_changed_effective_rules_are_rejected_before_analysis(window: Any, tmp_path: Path) -> None:
    baseline = _baseline(tmp_path)
    baseline["metadata"]["effective_rules"][0]["severity"] = "error"
    with pytest.raises(gui.VerificationError, match="effective rules"):
        gui.configure_window(window, baseline, None)
    assert not window.analysis_controller.has_job


def test_cryptomatte_verification_uses_category_not_name() -> None:
    payload = {
        "inspections": [
            {
                "path": "frame.exr",
                "aovs": [
                    {"name": "crypto_diffuse", "category": "color"},
                    {"name": "encoded_ids", "category": "cryptomatte"},
                ],
            }
        ],
        "frame_metrics": {"frame.exr": {"crypto_diffuse": {"avg_luminance": 1.0}}},
    }
    assert gui.verify_cryptomatte_scope(payload) == {"status": "passed", "names": ["encoded_ids"]}
    unsafe = copy.deepcopy(payload)
    unsafe["frame_metrics"]["frame.exr"]["encoded_ids"] = {}
    with pytest.raises(gui.VerificationError, match="encoded_ids"):
        gui.verify_cryptomatte_scope(unsafe)


def test_navigation_rejects_an_incomplete_evidence_table(window: Any) -> None:
    window.outlier_table.setRowCount(1)
    with pytest.raises(gui.VerificationError, match="evidence cell is missing"):
        gui.navigate_results(window)


def test_unrepresentable_configuration_saves_failed_summary_without_reading(
    tmp_path: Path, monkeypatch: Any, qt_application: Any
) -> None:
    from aovguard.ui import MainWindow

    source = tmp_path / "renders"
    source.mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(_baseline(source, _options(max_memory_mb=512.5))), encoding="utf-8"
    )
    monkeypatch.setattr(
        MainWindow,
        "start_analysis",
        lambda _self: pytest.fail("Preflight must reject before EXR reads"),
    )
    output = tmp_path / "result"
    summary = gui.run_verification(baseline, output)
    assert not summary["passed"]
    assert summary["failure"]["type"] == "VerificationError"
    assert (output / "gui-acceptance.json").is_file()
    assert (output / "gui-workflow.log").is_file()
    assert gui.cleanup_confirmed(summary["cleanup"])
    assert not list(source.iterdir())


@pytest.mark.parametrize("failure_mode", ["timeout", "unconfirmed_cleanup"])
def test_running_gui_failures_preserve_diagnostics_and_never_claim_passed(
    tmp_path: Path, monkeypatch: Any, qt_application: Any, failure_mode: str
) -> None:
    from PySide6.QtCore import Slot

    import aovguard.ui as ui
    from aovguard.gui.worker import AnalyzeWorker

    class FailingWorker(AnalyzeWorker):
        @Slot()
        def run(self) -> None:
            if failure_mode == "timeout":
                self._cancel_requested.wait(5)
                self.cancelled.emit()
            else:
                self.cleanup_failed.emit("Simulated cleanup could not be confirmed", "test details")

    source = tmp_path / "renders"
    source.mkdir()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_baseline(source)), encoding="utf-8")
    monkeypatch.setattr(ui, "AnalyzeWorker", FailingWorker)
    output = tmp_path / "result"
    summary = gui.run_verification(baseline, output, deadline_seconds=0.05)
    assert not summary["passed"]
    saved = json.loads((output / "gui-acceptance.json").read_text(encoding="utf-8"))
    assert not saved["passed"]
    assert (output / "gui-workflow.log").stat().st_size > 0
    assert not summary["cleanup"]["has_job"]
    assert not summary["cleanup"]["qthread_reference"]
    assert not summary["cleanup"]["active_children"]
    if failure_mode == "timeout":
        assert summary["failure"]["type"] == "TimeoutError"
        assert gui.cleanup_confirmed(summary["cleanup"])
    else:
        assert summary["cleanup"]["unsafe"]
        assert "cleanup_failure" in summary


@pytest.mark.parametrize(
    "field",
    [
        "has_job",
        "qthread_reference",
        "worker_reference",
        "unsafe",
        "active_children",
        "receiver_threads",
    ],
)
def test_cleanup_requires_every_owned_resource_to_be_clear(field: str) -> None:
    snapshot = dict.fromkeys(
        (
            "has_job",
            "qthread_reference",
            "worker_reference",
            "unsafe",
            "active_children",
            "receiver_threads",
        ),
        False,
    )
    snapshot[field] = True
    assert not gui.cleanup_confirmed(snapshot)


@pytest.mark.parametrize("check_cancellation", [False, True])
def test_real_gui_end_to_end_on_temporary_sequence(
    tmp_path: Path, qt_application: Any, check_cancellation: bool
) -> None:
    import Imath
    import numpy as np
    import OpenEXR

    from aovguard.core.analysis import analyze
    from aovguard.io.reader import OpenEXRReader

    source = tmp_path / "renders"
    source.mkdir()
    for number, value in enumerate((1.0, 1.0, 100.0), start=1):
        header = OpenEXR.Header(2, 2)
        header["channels"] = {
            name: Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT))
            for name in ("R", "G", "B", "empty.R", "empty.G", "empty.B")
        }
        target = OpenEXR.OutputFile(str(source / f"frame.{number:04}.exr"), header)
        try:
            target.writePixels(
                {
                    name: np.full(
                        (2, 2), 0.0 if name.startswith("empty.") else value, dtype=np.float32
                    ).tobytes()
                    for name in header["channels"]
                }
            )
        finally:
            target.close()
    original = {path.name: path.read_bytes() for path in source.iterdir()}
    options = _options()
    report = analyze(source, options, OpenEXRReader())
    baseline = tmp_path / "baseline.json"
    write_analysis_json(report, baseline, options=options)
    output = tmp_path / "gui-result"
    summary = gui.run_verification(
        baseline, output, deadline_seconds=60, check_cancellation=check_cancellation
    )
    assert summary["passed"], summary
    assert summary["parity"]["exact_semantic_match"]
    assert summary["analysis"]["frames_processed"] == 3
    assert summary["navigation"]["finding"]["status"] == "passed"
    assert summary["navigation"]["chart"]["status"] == "passed"
    assert summary["cancellation"]["status"] == ("passed" if check_cancellation else "skipped")
    assert gui.cleanup_confirmed(summary["cleanup"])
    assert {path.name: path.read_bytes() for path in source.iterdir()} == original
    assert not list(output.glob("*.exr"))
    assert os.path.getsize(output / "gui-report.html") > 1000
