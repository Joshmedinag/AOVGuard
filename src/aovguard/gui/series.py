"""Pure transformations for frame-series charts and outlier views."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np


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
) -> SeriesDisplay:
    """Transform luminance samples and calculate robust display statistics.

    Non-finite source values are excluded. Delta modes retain the first frame
    with a zero baseline so every displayed point can still navigate to its
    corresponding frame.
    """

    resolved_mode = mode if isinstance(mode, SeriesDisplayMode) else SeriesDisplayMode(mode)
    finite_samples = tuple(
        (Path(path), float(value)) for path, value in samples if math.isfinite(float(value))
    )
    if resolved_mode is SeriesDisplayMode.LUMINANCE:
        transformed = finite_samples
        value_label = "Average luminance"
        suffix = ""
    else:
        values: list[tuple[Path, float]] = []
        previous: float | None = None
        for path, current in finite_samples:
            if previous is None:
                value = 0.0
            elif resolved_mode is SeriesDisplayMode.PREVIOUS_DELTA:
                value = current - previous
            else:
                value = _previous_percentage(current, previous)
            values.append((path, value))
            previous = current
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
    )
