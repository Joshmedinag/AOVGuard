"""Frame-series regressions for separate sequences and discontinuities."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from aovguard.core.models import (
    AnalysisOptions,
    AnalysisReport,
    MetricSet,
    SeriesMetricSet,
    SourceKind,
)
from aovguard.gui.series import (
    SeriesDisplayMode,
    build_series_display,
    sequence_frame_context,
)
from aovguard.sequence.sequence_checker import check_sequences
from aovguard.ui import FULL_PATH_ROLE, TAB_FRAMES, MainWindow


def _report(
    values: dict[Path, float],
    *,
    failed_frames: tuple[Path, ...] = (),
    series: dict[str, dict[str, SeriesMetricSet]] | None = None,
) -> AnalysisReport:
    frames = tuple(values) + failed_frames
    return AnalysisReport(
        source=Path("renders"),
        frames=frames,
        successful_frames=tuple(values),
        failed_frames=failed_frames,
        inspections=(),
        source_kind=SourceKind.NUMBERED_SEQUENCE,
        sequence_check=check_sequences(frames),
        metrics_by_aov={"beauty": MetricSet(1.0, 1.0, 1.0, len(values))},
        frame_metrics={
            path: {"beauty": MetricSet(1.0, value, value, 1)}
            for path, value in values.items()
        },
        series_metrics_by_sequence=series or {},
    )


def _stats(values: tuple[float, ...], outlier: Path | None = None) -> SeriesMetricSet:
    return SeriesMetricSet(
        frame_count=len(values),
        median_luminance=values[0],
        mad_luminance=0.0,
        min_luminance=min(values),
        max_luminance=max(values),
        max_frame_delta=max(values) - min(values),
        outlier_frames=(outlier,) if outlier else (),
    )


@pytest.fixture
def application(qt_application):
    return qt_application


@pytest.fixture
def window(application, tmp_path: Path):
    settings = QSettings(str(tmp_path / "series-settings.ini"), QSettings.Format.IniFormat)
    result = MainWindow(settings=settings)
    yield result
    result.close()


def test_sequence_context_never_connects_gaps_or_different_sequences() -> None:
    a1, a2, a4 = (Path(f"renders/shotA.{number:04}.exr") for number in (1, 2, 4))
    b1, b2 = (Path(f"renders/shotB.{number:04}.exr") for number in (1, 2))
    report = _report({path: 1.0 for path in (a1, a2, a4, b1, b2)})

    identities, previous = sequence_frame_context(report)

    assert identities[a1] == identities[a4]
    assert identities[a1] != identities[b1]
    assert previous == {a2: a1, b2: b1}


def test_duplicate_frame_numbers_do_not_create_temporal_edges() -> None:
    paths = tuple(Path(f"renders/shot.{token}.exr") for token in ("0001", "0002", "2", "0003"))

    _identities, previous = sequence_frame_context(_report(dict.fromkeys(paths, 1.0)))

    assert previous == {}


def test_delta_series_requires_a_finite_adjacent_predecessor() -> None:
    frames = tuple(Path(f"renders/shot.{number:04}.exr") for number in (1, 2, 3, 4, 7, 8))
    samples = tuple(zip(frames, (1.0, 2.0, float("nan"), 5.0, 10.0, 11.0)))
    _identities, previous = sequence_frame_context(_report(dict(samples)))

    delta = build_series_display(samples, SeriesDisplayMode.PREVIOUS_DELTA, previous_frames=previous)
    luminance = build_series_display(samples, previous_frames=previous)

    assert delta.samples == ((frames[1], 1.0), (frames[-1], 1.0))
    assert delta.break_before == (frames[-1],)
    assert luminance.break_before == (frames[3], frames[4])


def test_comparison_series_does_not_skip_over_a_non_finite_sample() -> None:
    frames = tuple(Path(f"sample{number}.exr") for number in range(4))

    display = build_series_display(
        tuple(zip(frames, (1.0, float("nan"), 10.0, 12.0))),
        SeriesDisplayMode.PREVIOUS_DELTA,
    )

    assert display.samples == ((frames[0], 0.0), (frames[3], 2.0))
    assert display.break_before == (frames[3],)


def test_gui_sequence_selector_filters_samples_and_deltas(window: MainWindow) -> None:
    a = tuple(Path(f"renders/shotA.{number:04}.exr") for number in (1, 2))
    b = tuple(Path(f"renders/shotB.{number:04}.exr") for number in (1, 2))
    a_key, b_key = "renders/shotA.####.exr", "renders/shotB.####.exr"
    # Native paths are used for identities on Windows too.
    a_key, b_key = str(Path(a_key)), str(Path(b_key))
    report = _report(
        dict(zip(a + b, (1.0, 2.0, 100.0, 200.0))),
        series={a_key: {"beauty": _stats((1.0, 2.0))}, b_key: {"beauty": _stats((100.0, 200.0))}},
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.series_sequence_combo.count() == 2
    assert not window.series_sequence_combo.isHidden()
    assert window.series_chart.samples == ((a[0], 1.0), (a[1], 2.0))
    window.series_sequence_combo.setCurrentIndex(window.series_sequence_combo.findData(b_key))
    assert window.series_chart.samples == ((b[0], 100.0), (b[1], 200.0))
    window.series_mode_combo.setCurrentIndex(window.series_mode_combo.findData("previous_delta"))
    assert window.series_chart.samples == ((b[1], 100.0),)


def test_gui_previous_change_omits_failed_frames_and_gaps(window: MainWindow) -> None:
    a1, a2, a3, a4, a7, a8 = (Path(f"renders/shot.{number:04}.exr") for number in (1, 2, 3, 4, 7, 8))
    key = str(Path("renders/shot.####.exr"))
    report = _report(
        {a1: 1.0, a2: 2.0, a4: 4.0, a7: 10.0, a8: 11.0},
        failed_frames=(a3,),
        series={key: {"beauty": _stats((1.0, 2.0, 4.0, 10.0, 11.0))}},
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    changes = {
        Path(window.frame_table.item(row, 0).data(FULL_PATH_ROLE)): window.frame_table.item(row, 9).text()
        for row in range(window.frame_table.rowCount())
    }
    assert changes == {a1: "-", a2: "+100.00%", a4: "-", a7: "-", a8: "+10.00%"}
    assert window.series_chart._break_before == frozenset((a4, a7))
    assert not window.series_chart.grab().isNull()
    window.series_mode_combo.setCurrentIndex(window.series_mode_combo.findData("previous_delta"))
    assert window.series_chart.samples == ((a2, 1.0), (a8, 1.0))
    assert window.series_chart._break_before == frozenset((a8,))


def test_gui_outliers_use_their_own_sequence_median_and_navigation(window: MainWindow) -> None:
    a = tuple(Path(f"renders/shotA.{number:04}.exr") for number in range(1, 5))
    b = tuple(Path(f"renders/shotB.{number:04}.exr") for number in range(1, 5))
    a_key, b_key = str(Path("renders/shotA.####.exr")), str(Path("renders/shotB.####.exr"))
    report = _report(
        dict(zip(a + b, (1.0, 1.0, 1.0, 5.0, 10.0, 10.0, 10.0, 100.0))),
        series={
            a_key: {"beauty": _stats((1.0, 1.0, 1.0, 5.0), a[-1])},
            b_key: {"beauty": _stats((10.0, 10.0, 10.0, 100.0), b[-1])},
        },
    )

    window.on_analysis_finished((report, AnalysisOptions()))

    assert window.outlier_table.rowCount() == 2
    evidence = {
        Path(window.outlier_table.item(row, 0).data(FULL_PATH_ROLE)): (
            window.outlier_table.item(row, 3).text(), window.outlier_table.item(row, 4).text(), row,
        )
        for row in range(window.outlier_table.rowCount())
    }
    assert evidence[a[-1]][:2] == ("1.000000", "4.000000")
    assert evidence[b[-1]][:2] == ("10.000000", "90.000000")
    window.locate_outlier_frame(evidence[b[-1]][2])
    assert window.series_sequence_combo.currentData() == b_key
    assert window.tabs.currentIndex() == TAB_FRAMES
    assert window.frame_table.currentItem().data(FULL_PATH_ROLE) == str(b[-1])
