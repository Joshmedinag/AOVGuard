"""Tests for pure frame-series display transformations."""

from pathlib import Path

import pytest

from aovguard.gui.series import SeriesDisplayMode, build_series_display


def test_series_display_supports_luminance_delta_and_percentage_modes() -> None:
    frames = tuple(Path(f"shot.{number}.exr") for number in (1001, 1002, 1003, 1004))
    samples = tuple(zip(frames, (1.0, 2.0, 1.0, 10.0)))

    luminance = build_series_display(samples)
    delta = build_series_display(samples, SeriesDisplayMode.PREVIOUS_DELTA)
    percentage = build_series_display(samples, "previous_percent")

    assert [value for _path, value in luminance.samples] == [1.0, 2.0, 1.0, 10.0]
    assert [value for _path, value in delta.samples] == [0.0, 1.0, -1.0, 9.0]
    assert [value for _path, value in percentage.samples] == pytest.approx(
        [0.0, 100.0, -50.0, 900.0]
    )
    assert frames[-1] in luminance.outlier_frames
    assert percentage.value_suffix == "%"
    assert percentage.value_label == "Relative luminance change from previous frame"
    assert delta.normal_range is not None


def test_percentage_mode_represents_zero_transitions_and_filters_non_finite_values() -> None:
    frames = tuple(Path(f"frame.{number}.exr") for number in range(4))
    display = build_series_display(
        tuple(zip(frames, (0.0, 2.0, 0.0, float("nan")))),
        SeriesDisplayMode.PREVIOUS_PERCENT,
    )

    assert display.samples == (
        (frames[0], 0.0),
        (frames[1], 100.0),
        (frames[2], -100.0),
    )


def test_empty_series_has_no_derived_statistics() -> None:
    display = build_series_display((), SeriesDisplayMode.PREVIOUS_DELTA)

    assert display.samples == ()
    assert display.median is None
    assert display.mad is None
    assert display.normal_range is None
    assert display.outlier_frames == ()
