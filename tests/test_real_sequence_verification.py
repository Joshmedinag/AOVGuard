"""Exercise the opt-in verifier without distributing or modifying user renders."""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import OpenEXR
import pytest

from scripts import verify_real_sequence as verifier


def payload_for(source: Path) -> dict[str, Any]:
    path = str(source / "shot.0001.exr")
    metrics = {"pixel_count": 1, "nan_count": 0, "posinf_count": 0,
               "neginf_count": 0, "negative_count": 0}
    channels = {name: dict(metrics) for name in ("R", "G", "B")}
    return {
        "schema_version": "1.2",
        "metadata": {"status": "pass", "frames_discovered": 1, "frames_processed": 1,
                     "frames_failed": 0, "aovs_detected": 1, "summary_by_severity": {}},
        "frames": [path], "successful_frames": [path], "failed_frames": [],
        "warnings": [], "findings": [],
        "inspections": [{"path": path, "width": 1, "height": 1,
                         "channels": ["R", "G", "B"],
                         "aovs": [{"name": "beauty", "category": "color",
                                   "channels": ["R", "G", "B"]}]}],
        "aov_inventory": [{"name": "beauty"}],
        "frame_metrics": {path: {"beauty": {"pixel_count": 1}}},
        "frame_channel_metrics": {path: {"beauty": channels}},
        "channel_metrics_by_aov": {"beauty": copy.deepcopy(channels)},
        "series_metrics_by_aov": {"beauty": {"outlier_frames": []}},
        "sequence_check": {"summary": {"sequence_count": 1, "unnumbered_file_count": 0,
                                       "missing_frame_count": 0, "duplicate_frame_count": 0}},
    }


def arguments(source: Path, output: Path, *extra: str):
    return verifier.parser().parse_args([
        str(source), "--output-directory", str(output), "--frame-pattern", "shot.*.exr",
        "--expected-frame-range", "1", "1", "--luminance-model", "rec709", *extra,
    ])


def fake_runner(command: list[str], log: Path, _deadline: float) -> dict[str, Any]:
    source = Path(command[command.index("analyze") + 1])
    verifier.write_json(log.parent / "analysis.json", payload_for(source))
    (log.parent / "analysis.html").write_text("<html>Evidence</html>", encoding="utf-8")
    log.write_text("CLI executed", encoding="utf-8")
    return {"command": command, "exit_code": 0, "memory": {"available": False}}


@pytest.mark.parametrize("text", [
    '{"value":NaN}', '{"value":Infinity}', '{"value":-Infinity}',
    '{"value":1e999}', '{"value":1,"value":2}', '[]',
])
def test_non_strict_json_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        verifier.read_json(path)


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"unexpected": 0},
    {"metadata": {"frames_failed": True}}, {"metadata": {"frames_processed": -1}},
    {"metadata": {"frames_failed_typo": 0}}, {"metadata": {"status": "OK"}},
    {"dimensions": [0, 10]}, {"dimensions": [10]}, {"channel_count": 1.5},
    {"outliers_by_aov": {"beauty": -1}}, {"nonfinite_counts": {"nan_typo": 0}},
    {"sequence_summary": {"missing_typo": 0}}, {"findings": [{}]},
    {"findings": [{"rule_id": "nan_inf", "severity": "error", "channel": "R"}]},
    {"description": 1}, {"metadata": []}, {"findings": "any"},
])
def test_mistyped_expectations_fail_closed(tmp_path: Path, change: dict[str, Any]) -> None:
    path = tmp_path / "profile.json"
    verifier.write_json(path, {"schema_version": 1, **change})
    with pytest.raises(ValueError):
        verifier.load_expectations(path)


def test_profile_accepts_explicit_counts_findings_and_outliers(tmp_path: Path) -> None:
    expected = {"schema_version": 1, "dimensions": [1920, 810], "channel_count": 55,
                "metadata": {"status": "warning", "summary_by_severity": {"warning": 2}},
                "findings": [{"rule_id": "empty_aov", "severity": "warning", "aov": "light"}],
                "outliers_by_aov": {"beauty": 2}, "nonfinite_counts": {"nan_count": 0}}
    path = tmp_path / "profile.json"
    verifier.write_json(path, expected)
    assert verifier.load_expectations(path) == expected
    assert verifier.load_expectations(None) == {"schema_version": 1}


def test_existing_output_is_never_replaced(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "evidence"
    output.mkdir()
    marker = output / "report.json"
    marker.write_text("original", encoding="utf-8")
    with pytest.raises(FileExistsError):
        verifier.prepare_output(output, source, [])
    assert marker.read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("suffix", ["inside", "nested/inside"])
def test_output_inside_render_tree_is_rejected(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="outside"):
        verifier.prepare_output(source / suffix, source, [])
    assert not (source / suffix).exists()


def test_linked_output_ancestor_is_rejected(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    real = verifier._is_link
    monkeypatch.setattr(verifier, "_is_link", lambda path: path == linked or real(path))
    with pytest.raises(ValueError, match="Linked"):
        verifier.prepare_output(linked / "new", source, [])
    assert not (linked / "new").exists()


def test_exr_output_suffix_and_protected_ancestor_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="EXR suffix"):
        verifier.prepare_output(tmp_path / "report.exr", source, [])
    with pytest.raises(ValueError, match="protected"):
        verifier.prepare_output(tmp_path / "future", source, [tmp_path / "future/profile.json"])


def test_inventory_uses_canonical_case_insensitive_numeric_discovery(tmp_path: Path) -> None:
    for name in ("shot.10.exr", "shot.2.EXR", "shot.1.exr", "other.1.exr"):
        (tmp_path / name).write_bytes(b"existing pixels")
    result = verifier.inventory(tmp_path, "shot.*.exr", recursive=False, max_depth=1,
                                hash_source=False)
    assert [item["name"] for item in result] == ["shot.1.exr", "shot.2.EXR", "shot.10.exr"]
    assert all(set(item) == {"name", "size", "mtime_ns"} for item in result)


def test_hash_mode_detects_equal_size_equal_timestamp_replacement(tmp_path: Path) -> None:
    frame = tmp_path / "shot.1.exr"
    frame.write_bytes(b"initial")
    info = frame.stat()
    options = {"recursive": False, "max_depth": 1, "hash_source": True}
    before = verifier.inventory(tmp_path, "*.exr", **options)
    frame.write_bytes(b"changed")
    os.utime(frame, ns=(info.st_atime_ns, info.st_mtime_ns))
    after = verifier.inventory(tmp_path, "*.exr", **options)
    assert before[0]["size"] == after[0]["size"]
    assert before[0]["mtime_ns"] == after[0]["mtime_ns"]
    assert before[0]["sha256"] != after[0]["sha256"]


def test_complete_report_passes_default_and_explicit_expectations(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    profile = {"metadata": {"status": "pass", "frames_discovered": 1},
               "channel_count": 3, "dimensions": [1, 1], "findings": [], "outliers_by_aov": {}}
    result = verifier.audit_report(payload, profile, payload["frames"])
    assert result["passed"]
    assert result["checks"] >= 30
    assert result["nonfinite_counts"] == dict.fromkeys(verifier.COUNT_FIELDS, 0)


@pytest.mark.parametrize("field", ["nan_count", "posinf_count", "neginf_count", "pixel_count"])
def test_missing_or_inconsistent_channel_evidence_fails(tmp_path: Path, field: str) -> None:
    payload = payload_for(tmp_path)
    payload["channel_metrics_by_aov"]["beauty"]["R"][field] = 7
    result = verifier.audit_report(payload, {}, payload["frames"])
    assert not result["passed"]
    assert f"aggregate_channel_{field}" in result["problems"]


def test_unknown_channels_are_not_silently_dropped(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    inspection = payload["inspections"][0]
    inspection["channels"].append("custom.scalar")
    inspection["aovs"].append({"name": "custom", "category": "unknown", "channels": ["custom.scalar"]})
    payload["aov_inventory"].append({"name": "custom"})
    payload["metadata"]["aovs_detected"] = 2
    result = verifier.audit_report(payload, {}, payload["frames"])
    assert not result["passed"]
    assert "successful_frame_all_channels" in result["problems"]


def test_partial_pixels_fail_even_when_channel_aggregate_matches(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    payload["frame_channel_metrics"][payload["frames"][0]]["beauty"]["R"]["pixel_count"] = 0
    payload["channel_metrics_by_aov"]["beauty"]["R"]["pixel_count"] = 0
    result = verifier.audit_report(payload, {}, payload["frames"])
    assert not result["passed"]
    assert "channel_pixel_count_matches_part" in result["problems"]


def test_zero_outlier_expectation_cannot_hide_a_mistyped_aov(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    profile = {"outliers_by_aov": {"not_a_real_aov": 0}}
    result = verifier.audit_report(payload, profile, payload["frames"])
    assert not result["passed"]
    assert "expected_outlier_aovs_exist" in result["problems"]


def test_each_multipart_aov_uses_its_own_dimensions(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    path = payload["frames"][0]
    inspection = payload["inspections"][0]
    inspection["width"], inspection["height"] = 1920, 1080
    inspection["part_count"] = 2
    inspection["parts"] = [{"index": 0, "width": 1920, "height": 1080},
                           {"index": 1, "width": 1, "height": 1,
                            "data_window": [[4, 7], [4, 7]]}]
    inspection["aovs"][0]["part_index"] = 1
    assert verifier.audit_report(payload, {}, [path])["passed"]
    inspection["parts"][1]["width"] = 2
    result = verifier.audit_report(payload, {}, [path])
    assert not result["passed"]
    assert "channel_pixel_count_matches_part" in result["problems"]


def test_expected_warning_is_not_hidden_and_unexpected_finding_fails(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    warning = {"rule_id": "empty_aov", "severity": "warning", "aov": "light"}
    payload["findings"] = [warning]
    payload["metadata"].update(status="warning", summary_by_severity={"warning": 1})
    expected = {"metadata": {"status": "warning"}, "findings": [warning]}
    assert verifier.audit_report(payload, expected, payload["frames"])["passed"]
    expected["findings"] = []
    assert not verifier.audit_report(payload, expected, payload["frames"])["passed"]


def test_expected_render_failure_is_distinct_from_verification_failure(tmp_path: Path) -> None:
    payload = payload_for(tmp_path)
    error = {"rule_id": "aov_structure_mismatch", "severity": "error", "aov": None}
    payload["findings"] = [error]
    payload["metadata"].update(status="fail", summary_by_severity={"error": 1})
    assert not verifier.audit_report(payload, {}, payload["frames"])["passed"]
    expected = {"metadata": {"status": "fail"}, "findings": [error]}
    assert verifier.audit_report(payload, expected, payload["frames"])["passed"]


def test_cli_arguments_keep_spaces_shell_characters_and_preset_path_literal(tmp_path: Path) -> None:
    source = tmp_path / "source & special"
    preset = tmp_path / "my preset.toml"
    args = arguments(source, tmp_path / "out", "--preset", str(preset), "--recursive")
    args.max_frames = 1
    command = verifier.build_cli_command(args, tmp_path / "out")
    assert command[0] == sys.executable
    assert command[command.index("analyze") + 1] == str(source)
    assert command[command.index("--rules-config") + 1] == str(preset)
    assert "--recursive" in command
    assert "--in-process" not in command


@pytest.mark.parametrize("flag,value", [
    ("--max-memory-mb", "nan"), ("--max-memory-mb", "inf"),
    ("--frame-timeout-seconds", "0"), ("--deadline-seconds", "-1"), ("--max-frames", "0"),
])
def test_invalid_resources_are_rejected_before_launch(tmp_path: Path, flag: str, value: str) -> None:
    with pytest.raises(SystemExit):
        arguments(tmp_path, tmp_path / "out", flag, value)


def test_verifier_records_summary_and_never_changes_inputs(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    frame = source / "shot.0001.exr"
    frame.write_bytes(b"existing EXR bytes")
    before = (frame.read_bytes(), frame.stat().st_mtime_ns)
    monkeypatch.setattr(verifier, "run_command", fake_runner)
    output = tmp_path / "evidence"
    result = verifier.verify(arguments(source, output))
    assert result["passed"] and result["source_unchanged"]
    assert before == (frame.read_bytes(), frame.stat().st_mtime_ns)
    saved = verifier.read_json(output / "verification-summary.json")
    assert saved["passed"] and saved["render_metadata"]["status"] == "pass"
    assert "analysis.json" in saved["artifacts"]
    assert saved["artifacts"]["analysis.json"]["sha256"] == verifier.sha256(output / "analysis.json")


def test_external_source_change_and_cli_failure_preserve_diagnostics(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    frame = source / "shot.0001.exr"
    frame.write_bytes(b"original")

    def mutate(command, log, deadline):
        frame.write_bytes(b"externally replaced pixels")
        result = fake_runner(command, log, deadline)
        result["exit_code"] = 7
        return result

    monkeypatch.setattr(verifier, "run_command", mutate)
    output = tmp_path / "evidence"
    result = verifier.verify(arguments(source, output))
    assert not result["passed"]
    assert "source_inventory_changed" in result["failures"]
    assert "cli_exit_code_inconsistent" in result["failures"]
    assert verifier.read_json(output / "verification-summary.json")["passed"] is False


def test_missing_report_is_failure_not_an_expected_bad_render(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "shot.0001.exr").write_bytes(b"render")
    monkeypatch.setattr(verifier, "run_command", lambda *_args: {"exit_code": 1})
    result = verifier.verify(arguments(source, tmp_path / "evidence"))
    assert not result["passed"] and result["source_unchanged"]
    assert "FileNotFoundError" in result["failures"][0]


def test_empty_selection_reversed_range_and_cancel_without_gui_write_nothing(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    output = tmp_path / "evidence"
    args = arguments(source, output)
    with pytest.raises(ValueError, match="No EXRs"):
        verifier.verify(args)
    args.expected_frame_range = [2, 1]
    with pytest.raises(ValueError, match="ascending"):
        verifier.verify(args)
    args.expected_frame_range = [1, 1]
    args.check_cancellation = True
    with pytest.raises(ValueError, match="requires --gui"):
        verifier.verify(args)
    assert not output.exists()


def test_real_temporary_exr_runs_the_canonical_cli_without_mutation(tmp_path: Path) -> None:
    source = tmp_path / "external-source"
    source.mkdir()
    frame = source / "shot.0001.exr"
    OpenEXR.File({}, {channel: np.ones((2, 2), dtype=np.float32) for channel in ("R", "G", "B")}).write(str(frame))
    before = (frame.read_bytes(), frame.stat().st_mtime_ns)
    output = tmp_path / "evidence"
    result = verifier.verify(arguments(source, output))
    assert result["passed"], result["failures"]
    assert result["cli"]["exit_code"] == 0
    assert result["audit"]["passed"]
    assert result["cli"]["memory"]["sample_count"] > 0
    assert before == (frame.read_bytes(), frame.stat().st_mtime_ns)
    assert list(source.iterdir()) == [frame]
    assert (output / "cli.measurement.json").is_file()


def test_process_deadline_keeps_measurements_and_reaps_its_child(tmp_path: Path) -> None:
    log = tmp_path / "timeout.log"
    with pytest.raises(TimeoutError):
        verifier.run_command([sys.executable, "-c", "import time; time.sleep(60)"], log, 0.3)
    measurement = verifier.read_json(tmp_path / "timeout.measurement.json")
    assert measurement["exit_code"] is not None
    assert measurement["memory"]["sample_count"] > 0


def test_module_help_does_not_run_analysis() -> None:
    result = subprocess.run([sys.executable, "-m", "scripts.verify_real_sequence", "--help"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert "--hash-source" in result.stdout


@pytest.mark.parametrize("profile", ["maya-arnold", "venator-master", "venator-denoised"])
def test_bundled_profiles_are_valid_and_do_not_contain_local_paths(profile: str) -> None:
    path = Path(__file__).resolve().parents[1] / "config/verification" / f"{profile}.json"
    expected = verifier.load_expectations(path)
    assert expected["metadata"]["frames_failed"] == 0
    assert "D:\\" not in path.read_text(encoding="utf-8")


def test_ctrl_c_before_output_creation_returns_130(tmp_path: Path, monkeypatch, capsys) -> None:
    def interrupt(_args):
        raise KeyboardInterrupt

    monkeypatch.setattr(verifier, "verify", interrupt)
    assert verifier.main([
        str(tmp_path), "--output-directory", str(tmp_path / "out"),
        "--frame-pattern", "*.exr", "--expected-frame-range", "1", "1",
        "--luminance-model", "rec709",
    ]) == 130
    assert '"interrupted": true' in capsys.readouterr().out


def test_gui_dependency_failure_precedes_input_decode_or_output_creation(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "shot.0001.exr").write_bytes(b"existing")
    monkeypatch.setattr(verifier, "find_spec", lambda _name: None)
    output = tmp_path / "out"
    with pytest.raises(ValueError, match="PySide6"):
        verifier.verify(arguments(source, output, "--gui"))
    assert not output.exists()


def test_stop_does_not_skip_descendants_when_parent_has_exited(monkeypatch) -> None:
    events: list[str] = []

    class Captured:
        def stop(self):
            events.append("stopped descendants")

        def close(self):
            events.append("closed handles")

    class Parent:
        pid = 10

        def poll(self):
            return 0

    monkeypatch.setattr(verifier, "capture_descendants", lambda _pid: Captured())
    verifier._stop_process(Parent())
    assert events == ["stopped descendants", "closed handles"]


def test_unconfirmed_descendant_cleanup_is_not_silently_accepted(monkeypatch) -> None:
    def capture(_pid):
        raise RuntimeError("cleanup unconfirmed: access denied")

    class Parent:
        pid = 10

        def poll(self):
            return 0

    monkeypatch.setattr(verifier, "capture_descendants", capture)
    with pytest.raises(RuntimeError, match="cleanup unconfirmed"):
        verifier._stop_process(Parent())
