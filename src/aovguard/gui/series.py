"""Pure transformations for frame-series charts and outlier views."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np

from aovguard.core.models import AnalysisReport


class SeriesDisplayMode(StrEnum):
    """Supported numerical views of a frame luminance series."""

    LUMINANCE = "luminance"
    PREVIOUS_DELTA = "previous_delta"
    PREVIOUS_PERCENT = "previous_percent"


@dataclass(frozen=True, slots=True)
class SeriesDisplay:
    """Chart-ready values and robust statistics for one display mode."""

    mode: SeriesDisplayMode
    samples: tuple[tuple[Path, float], ...]
    median: float | None
    mad: float | None
    normal_range: tuple[float, float] | None
    outlier_frames: tuple[Path, ...]
    value_label: str
    value_suffix: str = ""
    break_before: tuple[Path, ...] = ()


def sequence_frame_context(
    report: AnalysisReport,
) -> tuple[dict[Path, str], dict[Path, Path]]:
    """Map frames to sequence identities and unambiguous adjacent predecessors.

    Missing numbers, duplicate frame numbers and sequence boundaries never
    create temporal edges. Failed frames remain in the predecessor map so a
    caller can detect that their metrics are unavailable instead of skipping
    over them to an earlier successful frame.
    """

    identities: dict[Path, str] = {}
    previous_frames: dict[Path, Path] = {}
    for sequence in report.sequence_check.sequences:
        key = str(sequence.directory / sequence.pattern)
        by_number: dict[int, list[Path]] = {}
        for path in sequence.files:
            end = len(path.name) - len(sequence.suffix) - len(".exr")
            number = int(path.name[len(sequence.prefix) : end])
            identities[path] = key
            by_number.setdefault(number, []).append(path)
        for number, paths in by_number.items():
            preceding = by_number.get(number - 1, ())
            if len(paths) == 1 and len(preceding) == 1:
                previous_frames[paths[0]] = preceding[0]
    return identities, previous_frames


def _previous_percentage(current: float, previous: float) -> float:
    """Return signed change against the previous absolute baseline.

    A transition away from zero is represented as signed 100 percent because
    the conventional percentage is undefined; this matches the GUI's existing
    ``new activity`` interpretation while keeping the chart finite.
    """

    if current == previous:
        return 0.0
    if previous == 0.0:
        return math.copysign(100.0, current)
    return ((current - previous) / abs(previous)) * 100.0


def build_series_display(
    samples: Sequence[tuple[Path, float]],
    mode: SeriesDisplayMode | str = SeriesDisplayMode.LUMINANCE,
    *,
    previous_frames: Mapping[Path, Path] | None = None,
) -> SeriesDisplay:
    """Transform luminance samples and calculate robust display statistics.

    Non-finite source values are excluded and break continuity. An explicit
    predecessor map constrains changes to adjacent frames within one sequence;
    changes with an absent or non-finite predecessor are omitted. Without a map,
    samples form an ordered comparison set and its first point retains a zero
    baseline for backwards compatibility.
    """

    resolved_mode = mode if isinstance(mode, SeriesDisplayMode) else SeriesDisplayMode(mode)
    finite_samples = tuple(
        (Path(path), float(value)) for path, value in samples if math.isfinite(float(value))
    )
    finite_values = dict(finite_samples)
    raw_previous = {
        Path(current[0]): Path(previous[0])
        for previous, current in zip(samples, samples[1:])
    }
    adjacency = raw_previous if previous_frames is None else previous_frames
    breaks: list[Path] = []
    if resolved_mode is SeriesDisplayMode.LUMINANCE:
        transformed = finite_samples
        last_displayed: Path | None = None
        for path, _current in transformed:
            if last_displayed is not None and adjacency.get(path) != last_displayed:
                breaks.append(path)
            last_displayed = path
        value_label = "Average luminance"
        suffix = ""
    else:
        values: list[tuple[Path, float]] = []
        last_displayed = None
        for path, current in finite_samples:
            previous_path = adjacency.get(path)
            previous = finite_values.get(previous_path) if previous_path is not None else None
            if previous is None and previous_frames is None and samples and path == Path(samples[0][0]):
                value = 0.0
            elif previous is None:
                continue
            elif resolved_mode is SeriesDisplayMode.PREVIOUS_DELTA:
                value = current - previous
            else:
                value = _previous_percentage(current, previous)
            if last_displayed is not None and previous_path != last_displayed:
                breaks.append(path)
            values.append((path, value))
            last_displayed = path
        transformed = tuple(values)
        if resolved_mode is SeriesDisplayMode.PREVIOUS_DELTA:
            value_label = "Luminance change from previous frame"
            suffix = ""
        else:
            value_label = "Relative luminance change from previous frame"
            suffix = "%"

    if not transformed:
        return SeriesDisplay(
            mode=resolved_mode,
            samples=(),
            median=None,
            mad=None,
            normal_range=None,
            outlier_frames=(),
            value_label=value_label,
            value_suffix=suffix,
        )

    numeric = np.asarray([value for _path, value in transformed], dtype=np.float64)
    median = float(np.median(numeric))
    deviations = np.abs(numeric - median)
    mad = float(np.median(deviations))
    outlier_indices: np.ndarray
    if len(transformed) < 3:
        outlier_indices = np.asarray([], dtype=np.int64)
        normal_range = None
    elif mad > 0.0:
        robust_scale = 1.4826 * mad
        outlier_indices = np.flatnonzero(deviations / robust_scale > 3.5)
        spread = 3.5 * robust_scale
        normal_range = (median - spread, median + spread)
    else:
        tolerance = max(1e-12, abs(median) * 1e-6)
        outlier_indices = np.flatnonzero(deviations > tolerance)
        normal_range = (median - tolerance, median + tolerance)

    return SeriesDisplay(
        mode=resolved_mode,
        samples=transformed,
        median=median,
        mad=mad,
        normal_range=normal_range,
        outlier_frames=tuple(transformed[index][0] for index in outlier_indices),
        value_label=value_label,
        value_suffix=suffix,
        break_before=tuple(breaks),
    )
