from pathlib import Path

import pytest

from aovguard.core.models import AnalysisOptions, Severity, SourceMode
from aovguard.sequence.sequence_checker import (
    check_sequences,
    format_frame_ranges,
    sequence_findings,
)


def test_sequence_checker_detects_ranges_and_missing_frames(tmp_path: Path) -> None:
    frames = (
        tmp_path / "shot.1001.exr",
        tmp_path / "shot.1002.exr",
        tmp_path / "shot.1005.exr",
    )

    result = check_sequences(frames, source=tmp_path)
    sequence = result.sequences[0]

    assert sequence.pattern == "shot.####.exr"
    assert sequence.start_frame == 1001
    assert sequence.end_frame == 1005
    assert sequence.frame_count == 3
    assert sequence.missing_ranges == ((1003, 1004),)
    assert sequence.missing_frame_count == 2
    assert format_frame_ranges(sequence.missing_ranges) == "1003-1004"

    findings = sequence_findings(result)
    assert len(findings) == 1
    assert findings[0].rule_id == "sequence_gap"
    assert findings[0].severity is Severity.WARNING
    assert findings[0].metrics["missing_frame_count"] == 2


def test_sequence_checker_separates_multiple_patterns_and_unnumbered_files(
    tmp_path: Path,
) -> None:
    result = check_sequences(
        (
            tmp_path / "beauty.1001.exr",
            tmp_path / "diffuse_1001.exr",
            tmp_path / "preview.exr",
        ),
        source=tmp_path,
    )

    assert [sequence.pattern for sequence in result.sequences] == [
        "beauty.####.exr",
        "diffuse_####.exr",
    ]
    assert result.unnumbered_files == (tmp_path / "preview.exr",)
    assert len(result.warnings) == 2
    assert "2 numbered" in result.warnings[0]
    assert "unnumbered" in result.warnings[1]


def test_sequence_checker_reports_duplicate_numbers_and_padding(tmp_path: Path) -> None:
    result = check_sequences(
        (
            tmp_path / "shot.001.exr",
            tmp_path / "shot.0001.exr",
            tmp_path / "shot.0002.exr",
        )
    )
    sequence = result.sequences[0]

    assert sequence.frame_numbers == (1, 2)
    assert sequence.duplicate_frames == (1,)
    assert sequence.padding_widths == (3, 4)
    assert result.duplicate_frame_count == 1
    assert {finding.rule_id for finding in sequence_findings(result)} == {
        "duplicate_frame",
        "inconsistent_padding",
    }


def test_sequence_checker_stores_large_gaps_as_compact_ranges(tmp_path: Path) -> None:
    result = check_sequences((tmp_path / "sim.1.exr", tmp_path / "sim.100000.exr"))

    sequence = result.sequences[0]
    assert sequence.missing_ranges == ((2, 99999),)
    assert sequence.missing_frame_count == 99998


def test_sequence_checker_explains_multiple_standalone_files(tmp_path: Path) -> None:
    result = check_sequences(
        (tmp_path / "beauty.exr", tmp_path / "beauty_no_light.exr"),
        source=tmp_path,
    )

    assert result.sequences == ()
    assert len(result.unnumbered_files) == 2
    assert result.warnings == ()


def test_expected_range_reports_leading_trailing_and_outside_frames(tmp_path: Path) -> None:
    result = check_sequences(
        (tmp_path / f"shot.{frame:04}.exr" for frame in (0, 2, 3, 5, 9)),
        expected_frame_range=(1, 8),
    )
    sequence = result.sequences[0]
    assert sequence.missing_ranges == ((1, 1), (4, 4), (6, 8))
    assert sequence.unexpected_ranges == ((0, 0), (9, 9))
    assert result.missing_frame_count == 5
    findings = sequence_findings(result)
    assert findings[0].rule_id == "sequence_gap"
    assert findings[0].severity is Severity.ERROR
    assert findings[0].metrics["expected_frame_range"] == (1, 8)
    assert findings[1].rule_id == "sequence_unexpected_frame"


def test_expected_range_requires_one_numbered_sequence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one numbered sequence"):
        check_sequences(
            (tmp_path / "a.0001.exr", tmp_path / "b.0001.exr"),
            expected_frame_range=(1, 8),
        )
    with pytest.raises(ValueError, match="ordered non-negative"):
        check_sequences((tmp_path / "a.0001.exr",), expected_frame_range=(8, 1))
    with pytest.raises(ValueError, match="numbered sequence"):
        AnalysisOptions(
            source_mode=SourceMode.COMPARISON,
            expected_frame_range=(1, 8),
        )
