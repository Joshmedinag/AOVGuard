"""Numbered EXR sequence grouping and continuity validation."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from aovguard.core.models import (
    Finding,
    SequenceCheckResult,
    SequenceDescriptor,
    Severity,
)

_FRAME_PATTERN = re.compile(
    r"^(?P<prefix>.*?)(?P<frame>\d+)(?P<suffix>[^0-9]*)\.exr$",
    re.IGNORECASE,
)


def _missing_ranges(
    frame_numbers: tuple[int, ...],
    expected_frame_range: tuple[int, int] | None = None,
) -> tuple[tuple[int, int], ...]:
    if expected_frame_range is not None:
        start, end = expected_frame_range
        frame_numbers = tuple(number for number in frame_numbers if start <= number <= end)
        if not frame_numbers:
            return ((start, end),)
        boundaries = (start - 1, *frame_numbers, end + 1)
    else:
        boundaries = frame_numbers
    ranges: list[tuple[int, int]] = []
    for previous, current in zip(boundaries, boundaries[1:]):
        if current > previous + 1:
            ranges.append((previous + 1, current - 1))
    return tuple(ranges)


def _unexpected_ranges(
    frame_numbers: tuple[int, ...], expected_frame_range: tuple[int, int]
) -> tuple[tuple[int, int], ...]:
    start, end = expected_frame_range
    outside = tuple(number for number in frame_numbers if number < start or number > end)
    if not outside:
        return ()
    ranges: list[tuple[int, int]] = []
    first = previous = outside[0]
    for number in outside[1:]:
        if number != previous + 1:
            ranges.append((first, previous))
            first = number
        previous = number
    ranges.append((first, previous))
    return tuple(ranges)


def format_frame_ranges(ranges: Iterable[tuple[int, int]]) -> str:
    """Format inclusive frame ranges compactly for reports and UI."""

    parts = [str(start) if start == end else f"{start}-{end}" for start, end in ranges]
    return ", ".join(parts)


def check_sequences(
    frames: Iterable[str | Path],
    *,
    source: str | Path | None = None,
    expected_frame_range: tuple[int, int] | None = None,
) -> SequenceCheckResult:
    """Group discovered EXRs into numbered sequences and identify objective gaps."""

    if expected_frame_range is not None and (
        len(expected_frame_range) != 2
        or any(type(value) is not int or value < 0 for value in expected_frame_range)
        or expected_frame_range[0] > expected_frame_range[1]
    ):
        raise ValueError("Expected frame range must be two ordered non-negative integers.")

    grouped: dict[
        tuple[Path, str, str],
        list[tuple[int, int, Path, str, str]],
    ] = defaultdict(list)
    unnumbered: list[Path] = []

    for raw_path in frames:
        path = Path(raw_path)
        match = _FRAME_PATTERN.match(path.name)
        if match is None:
            unnumbered.append(path)
            continue
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        frame_text = match.group("frame")
        key = (path.parent, prefix.casefold(), suffix.casefold())
        grouped[key].append((int(frame_text), len(frame_text), path, prefix, suffix))

    sequences: list[SequenceDescriptor] = []
    for entries in grouped.values():
        entries.sort(key=lambda entry: (entry[0], entry[2].name.casefold()))
        frame_occurrences: dict[int, int] = defaultdict(int)
        for frame_number, _padding, _path, _prefix, _suffix in entries:
            frame_occurrences[frame_number] += 1
        frame_numbers = tuple(sorted(frame_occurrences))
        padding_widths = tuple(sorted({entry[1] for entry in entries}))
        first = entries[0]
        sequences.append(
            SequenceDescriptor(
                directory=first[2].parent,
                prefix=first[3],
                suffix=first[4],
                padding=max(padding_widths),
                frame_numbers=frame_numbers,
                files=tuple(entry[2] for entry in entries),
                missing_ranges=_missing_ranges(frame_numbers, expected_frame_range),
                unexpected_ranges=(
                    _unexpected_ranges(frame_numbers, expected_frame_range)
                    if expected_frame_range is not None else ()
                ),
                duplicate_frames=tuple(
                    frame for frame, count in sorted(frame_occurrences.items()) if count > 1
                ),
                padding_widths=padding_widths,
            )
        )

    sequences.sort(
        key=lambda sequence: (
            str(sequence.directory).casefold(),
            sequence.prefix.casefold(),
            sequence.suffix.casefold(),
        )
    )
    if expected_frame_range is not None and (len(sequences) != 1 or unnumbered):
        raise ValueError(
            "Expected frame range requires exactly one numbered sequence and no standalone EXRs."
        )
    warnings: list[str] = []
    if len(sequences) > 1:
        warnings.append(
            f"{len(sequences)} numbered EXR sequences were detected in the selected source."
        )
    if unnumbered and sequences:
        warnings.append(
            f"{len(unnumbered)} unnumbered EXR file(s) were analyzed alongside numbered sequences."
        )
    return SequenceCheckResult(
        source=Path(source) if source is not None else None,
        expected_frame_range=expected_frame_range,
        sequences=tuple(sequences),
        unnumbered_files=tuple(sorted(unnumbered, key=lambda path: str(path).casefold())),
        warnings=tuple(warnings),
    )


def sequence_findings(result: SequenceCheckResult) -> tuple[Finding, ...]:
    """Convert objective sequence defects into canonical findings."""

    findings: list[Finding] = []
    for sequence in result.sequences:
        if sequence.missing_ranges:
            missing = format_frame_ranges(sequence.missing_ranges)
            findings.append(
                Finding(
                    rule_id="sequence_gap",
                    severity=(
                        Severity.ERROR
                        if result.expected_frame_range is not None else Severity.WARNING
                    ),
                    message=(
                        f"Missing expected frame range(s): {missing}."
                        if result.expected_frame_range is not None
                        else f"Missing frame range(s): {missing}."
                    ),
                    file=sequence.directory,
                    metrics={
                        "pattern": sequence.pattern,
                        "missing_ranges": sequence.missing_ranges,
                        "missing_frame_count": sequence.missing_frame_count,
                        "expected_frame_range": result.expected_frame_range,
                    },
                )
            )
        if sequence.unexpected_ranges:
            findings.append(
                Finding(
                    rule_id="sequence_unexpected_frame",
                    severity=Severity.WARNING,
                    message=(
                        "Frame(s) outside the expected range: "
                        f"{format_frame_ranges(sequence.unexpected_ranges)}."
                    ),
                    file=sequence.directory,
                    metrics={
                        "pattern": sequence.pattern,
                        "unexpected_ranges": sequence.unexpected_ranges,
                        "expected_frame_range": result.expected_frame_range,
                    },
                )
            )
        if sequence.duplicate_frames:
            duplicate_text = ", ".join(str(frame) for frame in sequence.duplicate_frames)
            findings.append(
                Finding(
                    rule_id="duplicate_frame",
                    severity=Severity.ERROR,
                    message=f"Duplicate frame number(s): {duplicate_text}.",
                    file=sequence.directory,
                    metrics={
                        "pattern": sequence.pattern,
                        "duplicate_frames": sequence.duplicate_frames,
                    },
                )
            )
        if len(sequence.padding_widths) > 1:
            padding_text = ", ".join(str(width) for width in sequence.padding_widths)
            findings.append(
                Finding(
                    rule_id="inconsistent_padding",
                    severity=Severity.WARNING,
                    message=f"Inconsistent frame padding widths: {padding_text}.",
                    file=sequence.directory,
                    metrics={
                        "pattern": sequence.pattern,
                        "padding_widths": sequence.padding_widths,
                    },
                )
            )
    return tuple(findings)
