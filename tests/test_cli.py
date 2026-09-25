import json
from pathlib import Path

import cv2
import Imath
import numpy as np
import OpenEXR
import pytest

from aovguard.cli import main
from aovguard.core.models import FileInspection


def _channel(value: float, width: int, height: int) -> bytes:
    return (np.ones((height, width), dtype=np.float32) * value).tobytes()


def _write_exr(path: Path, width: int, height: int, channels: dict[str, float]) -> None:
    pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
    header = OpenEXR.Header(width, height)
    header["channels"] = {name: Imath.Channel(pixel_type) for name in channels}
    output = OpenEXR.OutputFile(str(path), header)
    try:
        output.writePixels(
            {name: _channel(value, width, height) for name, value in channels.items()}
        )
    finally:
        output.close()


def _test_exr(path: Path) -> Path:
    _write_exr(
        path,
        2,
        2,
        {
            "R": 1.0,
            "G": 2.0,
            "B": 3.0,
            "diffuse.R": 4.0,
            "diffuse.G": 5.0,
            "diffuse.B": 6.0,
            "Z": 10.0,
        },
    )
    return path


def test_cli_help_keeps_legacy_commands(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "analyze-simple" in out
    assert "analyze-multilayer" in out
    assert "inspect" in out
    assert "inspect-structure" in out
    assert "analyze" in out


def test_cli_inspect_structure_prints_detected_aovs(tmp_path: Path, capsys) -> None:
    exr_path = _test_exr(tmp_path / "shot.1001.exr")

    exit_code = main(["inspect-structure", str(exr_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Detected AOVs" in out
    assert "beauty: color" in out
    assert "diffuse: color" in out
    assert "Z: depth" in out


def test_cli_analyze_writes_new_json_report(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "analyze",
            str(tmp_path),
            "--json",
            str(report_path),
            "--preset",
            "lighting_delivery",
            "--luminance-model",
            "rec601",
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Frames discovered: 1" in out
    assert "Frames processed: 1" in out
    assert "Frames failed: 0" in out
    assert "beauty" in out
    assert "diffuse" in out
    payload = json.loads(report_path.read_text())
    assert payload["metadata"]["frames_processed"] == 1
    assert payload["metadata"]["frames_discovered"] == 1
    assert payload["metadata"]["frames_failed"] == 0
    assert payload["metadata"]["aovs_detected"] == 3
    assert payload["metadata"]["aovs_analyzed"] == 2
    assert payload["metadata"]["technical_aovs_diagnosed"] == 1
    assert payload["metadata"]["aovs_diagnosed"] == 3
    assert payload["metadata"]["summary_by_aov_category"] == {
        "color": 2,
        "depth": 1,
    }
    assert payload["metadata"]["options"]["preset_name"] == "lighting_delivery"
    assert payload["metadata"]["options"]["luminance_weights"] == [0.299, 0.587, 0.114]
    assert payload["metadata"]["options"]["frame_pattern"] == "*.exr"
    assert payload["metadata"]["options"]["recursive"] is False
    assert set(payload["metrics_by_aov"]) == {"beauty", "diffuse"}
    assert set(payload["channel_metrics_by_aov"]["beauty"]) == {"R", "G", "B"}
    assert payload["sequence_check"]["summary"]["sequence_count"] == 1
    assert payload["sequence_check"]["sequences"][0]["pattern"] == "shot.####.exr"


def test_cli_check_sequence_and_html_report(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")
    _test_exr(tmp_path / "shot.1003.exr")

    main(["check-sequence", str(tmp_path)])

    out = capsys.readouterr().out
    assert "Sequences detected: 1" in out
    assert "shot.####.exr" in out
    assert "missing=1002" in out

    html_path = tmp_path / "report.html"
    main(["analyze", str(tmp_path), "--html", str(html_path)])
    out = capsys.readouterr().out
    assert "HTML report written" in out
    assert "sequence_gap" in html_path.read_text(encoding="utf-8")


def test_cli_expected_range_flags_undelivered_tail_and_exports_it(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.0001.exr")
    _test_exr(tmp_path / "shot.0002.exr")
    report_path = tmp_path / "report.json"

    assert main([
        "check-sequence", str(tmp_path), "--expected-frame-range", "1", "4"
    ]) == 1
    assert "missing=3-4" in capsys.readouterr().out

    assert main([
        "analyze", str(tmp_path), "--expected-frame-range", "1", "4",
        "--json", str(report_path),
    ]) == 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["options"]["expected_frame_range"] == [1, 4]
    assert payload["sequence_check"]["expected_frame_range"] == [1, 4]
    assert payload["sequence_check"]["sequences"][0]["missing_ranges"] == [[3, 4]]
    assert any(
        finding["rule_id"] == "sequence_gap" and finding["severity"] == "error"
        for finding in payload["findings"]
    )


def test_cli_expected_range_interprets_one_numbered_file_as_sequence(
    tmp_path: Path, capsys
) -> None:
    _test_exr(tmp_path / "shot.0001.exr")
    report_path = tmp_path / "report.json"

    assert main([
        "analyze", str(tmp_path), "--expected-frame-range", "1", "3",
        "--json", str(report_path),
    ]) == 1
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["metadata"]["source_kind"] == "numbered_sequence"
    assert payload["sequence_check"]["sequences"][0]["missing_ranges"] == [[2, 3]]


def test_cli_analyze_rejects_invalid_custom_weights(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")

    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path), "--luminance-weights", "0", "0", "0"])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "positive sum" in err


def test_cli_analyze_reports_missing_source_without_traceback(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path / "missing")])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "aovguard analyze: error:" in err
    assert "Traceback" not in err


def test_cli_analyze_rejects_folder_without_exrs(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path)])

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "No EXR files found" in err
    assert "Traceback" not in err


def test_cli_analyze_loads_rules_config_and_writes_findings(
    tmp_path: Path,
    capsys,
) -> None:
    renders = tmp_path / "renders"
    renders.mkdir()
    _test_exr(renders / "shot.1001.exr")
    rules_path = tmp_path / "rules.toml"
    rules_path.write_text(
        "\n".join(
            [
                'preset = "required_delivery"',
                "[rules.missing_aov]",
                "enabled = true",
                'severity = "error"',
                "[rules.missing_aov.parameters]",
                'required = ["beauty", "emission"]',
                "[rules.empty_aov]",
                "enabled = false",
            ]
        )
    )
    report_path = tmp_path / "report.json"

    exit_code = main(
        [
            "analyze",
            str(renders),
            "--rules-config",
            str(rules_path),
            "--json",
            str(report_path),
        ]
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "[error] missing_aov" in out
    payload = json.loads(report_path.read_text())
    assert payload["metadata"]["options"]["preset_name"] == "required_delivery"
    assert payload["metadata"]["options"]["enabled_rules"] == ["missing_aov"]
    assert payload["metadata"]["rules_executed"] == ["missing_aov"]
    assert payload["metadata"]["summary_by_severity"] == {"error": 1}
    assert payload["findings"][0]["rule_id"] == "missing_aov"
    assert payload["findings"][0]["aov"] == "emission"


def test_cli_analyze_returns_failure_for_corrupt_exr_without_traceback(
    tmp_path: Path,
    capsys,
) -> None:
    broken = tmp_path / "broken.1001.exr"
    broken.write_text("not an EXR", encoding="utf-8")

    exit_code = main(["analyze", str(broken)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Status: FAIL" in captured.out
    assert "Frames failed: 1" in captured.out
    assert "Traceback" not in captured.out
    assert "Traceback" not in captured.err


def test_cli_fail_on_warning_is_optional(tmp_path: Path, capsys) -> None:
    _test_exr(tmp_path / "shot.1001.exr")
    _test_exr(tmp_path / "shot.1003.exr")

    default_exit = main(["analyze", str(tmp_path)])
    capsys.readouterr()
    strict_exit = main(["analyze", str(tmp_path), "--fail-on-warning"])

    assert default_exit == 0
    assert strict_exit == 1


def test_cli_recursive_discovery_requires_multiple_sequence_opt_in(
    tmp_path: Path,
    capsys,
) -> None:
    beauty = tmp_path / "beauty"
    diffuse = tmp_path / "diffuse"
    beauty.mkdir()
    diffuse.mkdir()
    _test_exr(beauty / "beauty.1001.exr")
    _test_exr(diffuse / "diffuse.1001.exr")

    with pytest.raises(SystemExit) as excinfo:
        main(["analyze", str(tmp_path), "--recursive"])

    assert excinfo.value.code == 1
    assert "multiple numbered EXR sequences" in capsys.readouterr().err
    exit_code = main(
        [
            "analyze",
            str(tmp_path),
            "--recursive",
            "--allow-multiple-sequences",
        ]
    )
    assert exit_code == 0


def test_cli_analyze_prints_discovery_warning_and_custom_weights(
    tmp_path: Path,
    capsys,
) -> None:
    _test_exr(tmp_path / "shot.1001.exr")
    nested = tmp_path / "nested"
    nested.mkdir()
    _test_exr(nested / "shot.1002.exr")

    main(
        [
            "analyze",
            str(tmp_path),
            "--luminance-weights",
            "0.2",
            "0.7",
            "0.1",
        ]
    )

    out = capsys.readouterr().out
    assert "Warnings:" in out
    assert "nested EXR files were ignored" in out


def test_cli_inspect_structure_prints_inspection_warnings(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "multipart.exr"
    path.write_bytes(b"")
    inspection = FileInspection(
        path=path,
        width=2,
        height=2,
        channels=("R", "G", "B"),
        aovs=(),
        part_count=2,
        warnings=("Multipart fixture warning.",),
    )

    class FakeReader:
        def inspect(self, selected_path: Path) -> FileInspection:
            assert selected_path == path
            return inspection

    monkeypatch.setattr("aovguard.cli.OpenEXRReader", FakeReader)

    main(["inspect-structure", str(path)])

    out = capsys.readouterr().out
    assert "Parts: 2" in out
    assert "Warnings:" in out
    assert "Multipart fixture warning" in out


def test_cli_inspect_structure_handles_reader_error(tmp_path: Path, capsys) -> None:
    broken = tmp_path / "broken.exr"
    broken.write_text("broken", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        main(["inspect-structure", str(broken)])

    assert excinfo.value.code == 1
    assert "inspect-structure: error" in capsys.readouterr().err


def test_cli_legacy_simple_writes_json_and_csv(tmp_path: Path, capsys) -> None:
    image = np.ones((2, 2, 3), dtype=np.float32)
    assert cv2.imwrite(str(tmp_path / "beauty.1001.exr"), image)
    config_path = tmp_path / "thresholds.json"
    config_path.write_text(
        json.dumps({"analysis": {"review_max_ratio": 0.1}}),
        encoding="utf-8",
    )
    json_path = tmp_path / "simple.json"
    csv_path = tmp_path / "simple.csv"

    main(
        [
            "analyze-simple",
            str(tmp_path),
            "--config",
            str(config_path),
            "--review-max-average",
            "0.2",
            "--json",
            str(json_path),
            "--csv",
            str(csv_path),
        ]
    )

    out = capsys.readouterr().out
    assert "Frames found: 1" in out
    assert "AOVs analyzed: 1" in out
    assert "JSON report written" in out
    assert "CSV report written" in out
    assert json.loads(json_path.read_text())["metadata"]["mode"] == "simple"
    assert csv_path.read_text(encoding="utf-8").startswith("aov_name,classification")


def test_cli_legacy_multilayer_and_inspect_commands(tmp_path: Path, capsys) -> None:
    path = _test_exr(tmp_path / "shot.1001.exr")
    json_path = tmp_path / "multilayer.json"
    csv_path = tmp_path / "multilayer.csv"

    main(["inspect", str(path)])
    inspect_output = capsys.readouterr().out
    assert "Detected RGB AOV groups" in inspect_output
    assert "diffuse" in inspect_output

    main(
        [
            "analyze-multilayer",
            str(tmp_path),
            "--json",
            str(json_path),
            "--csv",
            str(csv_path),
        ]
    )

    out = capsys.readouterr().out
    assert "Frames found: 1" in out
    assert "diffuse" in out
    assert json.loads(json_path.read_text())["metadata"]["mode"] == "multilayer"
    assert csv_path.exists()
