from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from aovguard.ui_components import LuminanceSeriesChart


def test_luminance_chart_renders_range_symbols_tooltips_and_clicks() -> None:
    _application = QApplication.instance() or QApplication([])
    frames = tuple(Path(f"shot.{frame}.exr") for frame in (1001, 1002, 1003))
    chart = LuminanceSeriesChart()
    chart.resize(800, 220)
    chart.set_series(
        "beauty",
        tuple(zip(frames, (1.0, 8.0, 1.2))),
        median=1.2,
        outliers=(frames[1],),
        normal_range=(0.5, 2.0),
        issues={frames[1]: ("resolution_mismatch: different size",)},
    )
    activated: list[Path] = []
    chart.frame_activated.connect(activated.append)
    chart.show()

    assert not chart.grab().isNull()
    QTest.mouseMove(chart, QPoint(420, 100))
    assert "Frame error" in chart.toolTip()
    assert "Click to locate" in chart.toolTip()
    QTest.mouseClick(chart, Qt.LeftButton, pos=QPoint(420, 100))
    assert activated == [frames[1]]

    chart.clear()
    assert chart.sample_count == 0
    assert not chart.grab().isNull()
    chart.close()


def test_luminance_chart_filters_non_finite_samples() -> None:
    _application = QApplication.instance() or QApplication([])
    chart = LuminanceSeriesChart()

    chart.set_series(
        "beauty",
        ((Path("good.exr"), 1.0), (Path("bad.exr"), float("nan"))),
        median=float("nan"),
        normal_range=(float("nan"), 2.0),
    )

    assert chart.sample_count == 1
    chart.close()
