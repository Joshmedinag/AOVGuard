"""Reusable Qt widgets for the AOVGuard desktop interface."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """Compact disclosure section used for secondary interface controls."""

    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        """Create a titled section with persistent expanded state."""

        super().__init__(parent)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_button.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.toggle_button.setStyleSheet(
            "QToolButton { border: 0; font-weight: 600; padding: 4px 2px; text-align: left; }"
        )

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 2, 0, 4)
        self.content_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)

        self.toggle_button.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        """Return whether the section content is visible."""

        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        """Set content visibility and update the disclosure arrow."""

        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)
        self.expanded_changed.emit(expanded)


class EmptyStateTable(QWidget):
    """Switch between a table and a centered, informative empty state."""

    def __init__(
        self,
        table: QWidget,
        empty_text: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        """Create a stacked empty message and result table."""

        super().__init__(parent)
        self.table = table
        self.empty_label = QLabel(empty_text)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("QLabel { color: #66717d; padding: 24px; }")

        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.table)
        self.show_empty(empty_text)

    def show_empty(self, message: str | None = None) -> None:
        """Show the empty-state label with an optional new message."""

        if message is not None:
            self.empty_label.setText(message)
        self.stack.setCurrentWidget(self.empty_label)

    def show_table(self) -> None:
        """Show the wrapped result table."""

        self.stack.setCurrentWidget(self.table)


class LuminanceSeriesChart(QWidget):
    """Compact frame-series chart drawn with Qt and no external dependency."""

    frame_activated = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize an empty interactive frame-series chart."""

        super().__init__(parent)
        self._aov_name = ""
        self._samples: tuple[tuple[Path, float], ...] = ()
        self._median: float | None = None
        self._outliers: frozenset[Path] = frozenset()
        self._normal_range: tuple[float, float] | None = None
        self._issues: dict[Path, tuple[str, ...]] = {}
        self._point_positions: tuple[tuple[QPointF, Path, float], ...] = ()
        self._value_label = "Average luminance"
        self._value_suffix = ""
        self.setMinimumHeight(210)
        self.setMouseTracking(True)
        self.setToolTip(
            "Average color-AOV luminance across analyzed frames. "
            "The dashed line is the series median and amber points are outliers."
        )

    @property
    def aov_name(self) -> str:
        """Return the AOV represented by the current series."""

        return self._aov_name

    @property
    def sample_count(self) -> int:
        """Return the number of finite samples currently displayed."""

        return len(self._samples)

    @property
    def samples(self) -> tuple[tuple[Path, float], ...]:
        """Return immutable chart samples for inspection and testing."""

        return self._samples

    def clear(self) -> None:
        """Remove all chart data and interaction state."""

        self._aov_name = ""
        self._samples = ()
        self._median = None
        self._outliers = frozenset()
        self._normal_range = None
        self._issues = {}
        self._point_positions = ()
        self._value_label = "Average luminance"
        self._value_suffix = ""
        self.update()

    def set_series(
        self,
        aov_name: str,
        samples: Sequence[tuple[Path, float]],
        *,
        median: float | None = None,
        outliers: Sequence[Path] = (),
        normal_range: tuple[float, float] | None = None,
        issues: Mapping[Path, Sequence[str]] | None = None,
        value_label: str = "Average luminance",
        value_suffix: str = "",
    ) -> None:
        """Replace the displayed series and its optional diagnostic evidence."""

        self._aov_name = aov_name
        self._samples = tuple(
            (Path(path), float(value)) for path, value in samples if math.isfinite(float(value))
        )
        self._median = (
            float(median) if median is not None and math.isfinite(float(median)) else None
        )
        self._outliers = frozenset(Path(path) for path in outliers)
        if (
            normal_range is not None
            and len(normal_range) == 2
            and all(math.isfinite(float(value)) for value in normal_range)
        ):
            lower, upper = (float(value) for value in normal_range)
            self._normal_range = (min(lower, upper), max(lower, upper))
        else:
            self._normal_range = None
        self._issues = {
            Path(path): tuple(str(reason) for reason in reasons if str(reason))
            for path, reasons in (issues or {}).items()
        }
        self._value_label = str(value_label)
        self._value_suffix = str(value_suffix)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render axes, robust range and accessible point markers."""

        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())

        if not self._samples:
            painter.setPen(self.palette().color(self.foregroundRole()))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No frame-series data available.",
            )
            self._point_positions = ()
            return

        plot = QRectF(
            58.0,
            44.0,
            max(1.0, self.width() - 76.0),
            max(1.0, self.height() - 80.0),
        )
        values = [value for _path, value in self._samples]
        if self._median is not None:
            values.append(self._median)
        if self._normal_range is not None:
            values.extend(self._normal_range)
        minimum = min(values)
        maximum = max(values)
        if math.isclose(minimum, maximum):
            padding = max(1e-6, abs(minimum) * 0.1, 0.01)
            minimum -= padding
            maximum += padding

        def x_position(index: int) -> float:
            if len(self._samples) == 1:
                return plot.center().x()
            return plot.left() + (index / (len(self._samples) - 1)) * plot.width()

        def y_position(value: float) -> float:
            return plot.bottom() - ((value - minimum) / (maximum - minimum)) * plot.height()

        if self._normal_range is not None:
            lower, upper = self._normal_range
            top = y_position(upper)
            bottom = y_position(lower)
            band_color = QColor("#dbeaf7")
            band_color.setAlpha(150)
            painter.fillRect(
                QRectF(plot.left(), top, plot.width(), max(1.0, bottom - top)),
                band_color,
            )

        painter.setPen(QPen(QColor("#d7dce2"), 1.0))
        for step in range(3):
            ratio = step / 2
            y = plot.bottom() - ratio * plot.height()
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            label_value = minimum + ratio * (maximum - minimum)
            painter.setPen(QColor("#5d6670"))
            painter.drawText(
                QRectF(0.0, y - 9.0, 52.0, 18.0),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{label_value:.3g}{self._value_suffix}",
            )
            painter.setPen(QPen(QColor("#d7dce2"), 1.0))

        if self._median is not None:
            median_pen = QPen(QColor("#59636f"), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(median_pen)
            y = y_position(self._median)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        positions = tuple(
            (QPointF(x_position(index), y_position(value)), path, value)
            for index, (path, value) in enumerate(self._samples)
        )
        painter.setPen(QPen(QColor("#1769aa"), 2.0))
        for current, following in zip(positions, positions[1:]):
            painter.drawLine(current[0], following[0])
        for point, path, _value in positions:
            has_issue = bool(self._issues.get(path))
            is_outlier = path in self._outliers
            if has_issue:
                painter.setPen(QPen(QColor("#8b1e1e"), 1.5))
                painter.setBrush(QColor("#ffdcdc"))
                painter.drawRect(QRectF(point.x() - 5.0, point.y() - 5.0, 10.0, 10.0))
            elif is_outlier:
                painter.setPen(QPen(QColor("#795600"), 1.5))
                painter.setBrush(QColor("#f2ad32"))
                painter.drawPolygon(
                    QPolygonF(
                        [
                            QPointF(point.x(), point.y() - 6.0),
                            QPointF(point.x() - 6.0, point.y() + 5.0),
                            QPointF(point.x() + 6.0, point.y() + 5.0),
                        ]
                    )
                )
            else:
                painter.setPen(QPen(QColor("#1769aa"), 1.0))
                painter.setBrush(QColor("#ffffff"))
                painter.drawEllipse(point, 3.5, 3.5)

        painter.setPen(QColor("#18202a"))
        painter.drawText(
            QRectF(plot.left(), 2.0, plot.width(), 20.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{self._value_label} over frames: {self._aov_name}",
        )
        painter.setPen(QColor("#5d6670"))
        painter.drawText(
            QRectF(plot.left(), 22.0, plot.width(), 18.0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "○ normal   ▲ robust outlier   ■ frame error   shaded: normal range",
        )
        painter.setPen(QColor("#5d6670"))
        painter.drawText(
            QRectF(plot.left(), plot.bottom() + 7.0, plot.width() / 2, 20.0),
            Qt.AlignmentFlag.AlignLeft,
            self._samples[0][0].name,
        )
        painter.drawText(
            QRectF(plot.center().x(), plot.bottom() + 7.0, plot.width() / 2, 20.0),
            Qt.AlignmentFlag.AlignRight,
            self._samples[-1][0].name,
        )
        self._point_positions = positions

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Expose exact sample evidence for the nearest plotted point."""

        if not self._point_positions:
            return super().mouseMoveEvent(event)
        nearest = min(
            self._point_positions,
            key=lambda sample: abs(sample[0].x() - event.position().x()),
        )
        if abs(nearest[0].x() - event.position().x()) <= 12.0:
            marker = "\nRobust outlier" if nearest[1] in self._outliers else ""
            issue_text = "".join(
                f"\nFrame error: {reason}" for reason in self._issues.get(nearest[1], ())
            )
            self.setToolTip(
                f"{nearest[1]}\n{self._value_label}: "
                f"{nearest[2]:.6f}{self._value_suffix}"
                f"{marker}{issue_text}\nClick to locate this frame."
            )
        else:
            self.setToolTip(
                f"{self._value_label} across analyzed frames. "
                "The dashed line is the series median and amber points are outliers."
            )
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emit the frame path when a plotted point is activated."""

        if event.button() == Qt.MouseButton.LeftButton and self._point_positions:
            nearest = min(
                self._point_positions,
                key=lambda sample: abs(sample[0].x() - event.position().x()),
            )
            if abs(nearest[0].x() - event.position().x()) <= 12.0:
                self.frame_activated.emit(nearest[1])
                event.accept()
                return
        super().mousePressEvent(event)
