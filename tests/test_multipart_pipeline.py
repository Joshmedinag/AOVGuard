"""End-to-end multipart and long-sequence release acceptance checks."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import OpenEXR
import pytest

from aovguard.cli import main
from aovguard.core.analysis import analyze
from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    AOVCategory,
    AOVDescriptor,
    FileInspection,
    PartInspection,
    SequenceCheckResult,
    SequenceDescriptor,
    SourceKind,
)
from aovguard.io.reader import OpenEXRReader
from aovguard.reports.comparison import compare_report_payloads
from aovguard.reports.html_report import build_analysis_html
from aovguard.reports.json_report import build_analysis_report_payload
from aovguard.rules.definitions import RuleDefinition
from aovguard.rules.engine import execute_rules


def _stereo(path: Path, order: tuple[str, ...], bad_alpha: bool = False) -> Path:
    parts = []
    display = (np.array([0, 0], dtype=np.int32), np.array([9, 9], dtype=np.int32))
    for name in order:
        value = 1.0 if name == "left" else 2.0
        pixels = {channel: np.full((2, 3), value, np.float32) for channel in ("R", "G", "B")}
        pixels["A"] = np.full((2, 3), np.nan if bad_alpha and name == "right" else 1, np.float32)
        parts.append(OpenEXR.Part({"view": name, "displayWindow": display}, pixels, name))
    OpenEXR.File(parts).write(str(path))
    return path


def test_multipart_sequence_reorders_parts_without_merging_evidence(tmp_path: Path) -> None:
    first = _stereo(tmp_path / "shot.0001.exr", ("left", "right"))
    second = _stereo(tmp_path / "shot.0002.exr", ("right", "left"), bad_alpha=True)
    report = analyze(tmp_path, AnalysisOptions(), OpenEXRReader())

    assert report.frame_count == 2
    assert report.metrics_by_aov["[part:left]::beauty"].avg_luminance == pytest.approx(1)
    assert report.metrics_by_aov["[part:right]::beauty"].avg_luminance == pytest.approx(2)
    errors = [finding for finding in report.findings if finding.rule_id == "nan_inf"]
    assert len(errors) == 1
    assert errors[0].file == second
    assert errors[0].channel == "[part:right]::A"
    assert errors[0].affected_files == (second,)
    assert first not in errors[0].affected_files
    assert not any(f.rule_id in {"aov_structure_mismatch", "resolution_mismatch"} for f in report.findings)


def test_multipart_reports_and_cli_expose_source_part_metadata(tmp_path: Path, capsys) -> None:
    path = _stereo(tmp_path / "stereo.exr", ("left", "right"), bad_alpha=True)
    options = AnalysisOptions()
    report = analyze(path, options, OpenEXRReader())
    payload = build_analysis_report_payload(report, options=options)
    assert payload["schema_version"] == "1.2"
    parts = payload["inspections"][0]["parts"]
    assert parts[1]["name"] == parts[1]["view"] == "right"
    assert parts[1]["aovs"][0]["original_name"] == "beauty"
    assert set(parts[1]["aovs"][0]["original_channels"]) == {"R", "G", "B", "A"}
    assert parts[1]["display_width"] == 10
    assert parts[1]["width"] == 3
    comparison = compare_report_payloads(payload, payload)
    assert comparison.changed_aov_count == 0
    html = build_analysis_html(report, options=options)
    assert "EXR Parts" in html and "10x10" in html
    technical = html.split("<h2>Technical AOV Diagnostics</h2>")[1].split("<h2>")[0]
    assert "[part:right]::A" in technical
    assert "[part:right]::R" not in technical
    assert main(["inspect-structure", str(path)]) == 0
    output = capsys.readouterr().out
    assert "Part 1: right | view=right" in output


def test_required_names_can_target_all_parts_or_an_exact_part(tmp_path: Path) -> None:
    path = _stereo(tmp_path / "stereo.exr", ("left", "right"))
    report = analyze(path, AnalysisOptions(), OpenEXRReader())
    findings = execute_rules(report, (
        RuleDefinition("missing_aov", parameters={"required": ["beauty", "[part:left]::beauty", "[part:center]::beauty"]}),
        RuleDefinition("missing_channels", parameters={"required": ["R", "[part:right]::R", "[part:center]::R"]}),
    ))
    assert len(findings) == 2
    assert {finding.aov or finding.channel for finding in findings} == {
        "[part:center]::beauty", "[part:center]::R",
    }


def _part(name: str, index: int, width: int) -> PartInspection:
    aov = AOVDescriptor(
        f"[part:{name}]::beauty", (f"[part:{name}]::R",), AOVCategory.COLOR, part_index=index,
    )
    return PartInspection(index, name, width, 2, ("R",), (aov,))


def _inspection(path: Path, parts: tuple[PartInspection, ...]) -> FileInspection:
    return FileInspection(
        path, parts[0].width, parts[0].height,
        tuple(channel for part in parts for channel in part.aovs[0].channels),
        tuple(aov for part in parts for aov in part.aovs),
        part_count=len(parts), parts=parts,
    )


def test_resolution_compares_every_matching_part_not_its_physical_position() -> None:
    first = _inspection(Path("shot.0001.exr"), (_part("left", 0, 3), _part("right", 1, 5)))
    second = _inspection(Path("shot.0002.exr"), (_part("right", 0, 6), _part("left", 1, 3)))
    report = AnalysisReport(Path("."), (first.path, second.path), (first, second), {})
    findings = execute_rules(report, (RuleDefinition("resolution_mismatch"),))
    assert len(findings) == 1
    assert findings[0].metrics["part"] == "[part:right]"
    assert findings[0].metrics["baseline_width"] == 5
    assert findings[0].metrics["width"] == 6


def test_independent_sequences_do_not_share_structure_or_resolution_baseline() -> None:
    first = _inspection(Path("small.0001.exr"), (_part("left", 0, 3), _part("right", 1, 3)))
    second = replace(first, path=Path("small.0002.exr"))
    third = FileInspection(Path("large.0001.exr"), 10, 10, ("Z",), (AOVDescriptor("Z", ("Z",), AOVCategory.DEPTH),))
    fourth = replace(third, path=Path("large.0002.exr"))
    sequences = tuple(
        SequenceDescriptor(Path("."), name + ".", "", 4, (1, 2), paths)
        for name, paths in (("small", (first.path, second.path)), ("large", (third.path, fourth.path)))
    )
    report = AnalysisReport(
        Path("."), (first.path, second.path, third.path, fourth.path),
        (first, second, third, fourth), {}, source_kind=SourceKind.NUMBERED_SEQUENCE,
        sequence_check=SequenceCheckResult(sequences=sequences),
    )
    assert not execute_rules(report, (RuleDefinition("resolution_mismatch"), RuleDefinition("aov_structure_mismatch")))


def test_part_view_metadata_changes_are_structure_findings() -> None:
    first = _inspection(Path("shot.0001.exr"), (_part("left", 0, 3), _part("right", 1, 3)))
    second = replace(first, path=Path("shot.0002.exr"), parts=(
        replace(first.parts[0], view="unexpected"), first.parts[1],
    ))
    report = AnalysisReport(Path("."), (first.path, second.path), (first, second), {})
    findings = execute_rules(report, (RuleDefinition("aov_structure_mismatch"),))
    assert len(findings) == 1
    assert findings[0].file == second.path
    assert findings[0].metrics["changed_aovs"] == ["[part:left]::beauty"]


@pytest.mark.parametrize("enabled", [True, False])
def test_huge_rule_parameters_are_isolated_instead_of_aborting_analysis(tmp_path: Path, enabled: bool) -> None:
    path = _stereo(tmp_path / "stereo.exr", ("left", "right"))
    definition = RuleDefinition("extreme_values", enabled=enabled, parameters={"max_absolute": 10**400})
    report = analyze(path, AnalysisOptions(), OpenEXRReader(), rule_definitions=(definition,))
    assert report.frame_count == 1
    errors = [finding for finding in report.findings if finding.rule_id == "rule_error"]
    assert len(errors) == int(enabled)
    assert report.effective_rules[0]["parameters"]["max_absolute"] == 10**400


def test_800_frame_native_sequence_handles_gaps_corruption_and_cropped_parts(tmp_path: Path) -> None:
    for number in range(1, 801):
        if number == 17:
            continue
        path = tmp_path / f"stress.{number:04d}.exr"
        if number == 401:
            path.write_bytes(b"not a valid EXR")
        else:
            _stereo(path, ("left", "right"))
    report = analyze(
        tmp_path, AnalysisOptions(expected_frame_range=(1, 800), max_frames=800), OpenEXRReader(),
    )
    assert report.discovered_frame_count == 799
    assert report.frame_count == 798
    assert report.failed_frames == (tmp_path / "stress.0401.exr",)
    assert report.sequence_check.sequences[0].missing_ranges == ((17, 17),)
    assert report.metrics_by_aov["[part:left]::beauty"].pixel_count == 798 * 6
    assert report.metrics_by_aov["[part:right]::beauty"].pixel_count == 798 * 6
    assert not any(f.rule_id in {"resolution_mismatch", "aov_structure_mismatch", "nan_inf"} for f in report.findings)
