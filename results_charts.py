"""Matplotlib result charts and common single-axis photometric analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from measurement_run import MeasurementRun


QUANTITY_MAP = {
    "Candela": ("candela_cd", "Luminous intensity", "cd"),
    "Lux": ("lux", "Illuminance", "lx"),
    "Photocurrent": ("current_na", "Photocurrent", "nA"),
}


@dataclass(frozen=True)
class SingleAxisSeries:
    axis_name: str
    fixed_axis_name: str
    fixed_angle: float
    angles: list[float]
    values: list[float]
    quantity_label: str
    unit: str


@dataclass(frozen=True)
class BeamMetrics:
    peak_value: float | None
    peak_angle: float | None
    mean_value: float | None
    fwhm_deg: float | None


def _unique(values, tolerance=1e-6):
    result = []
    for value in sorted(float(v) for v in values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def extract_single_axis_series(run: MeasurementRun, quantity: str) -> SingleAxisSeries | None:
    """Return an angle/value series when exactly one goniometer axis varies."""

    attr, label, unit = QUANTITY_MAP.get(quantity, QUANTITY_MAP["Candela"])
    usable = []
    for point in run.points:
        value = getattr(point, attr, None)
        if value is not None and math.isfinite(float(value)):
            usable.append((point, float(value)))

    if not usable:
        return None

    c_values = _unique([point.c_deg for point, _ in usable], tolerance=1e-4)
    gamma_values = _unique([point.gamma_deg for point, _ in usable], tolerance=1e-4)

    if len(c_values) == 1 and len(gamma_values) >= 1:
        ordered = sorted(usable, key=lambda item: item[0].gamma_deg)
        return SingleAxisSeries(
            axis_name="Gamma",
            fixed_axis_name="C",
            fixed_angle=c_values[0],
            angles=[point.gamma_deg for point, _ in ordered],
            values=[value for _, value in ordered],
            quantity_label=label,
            unit=unit,
        )

    if len(gamma_values) == 1 and len(c_values) >= 1:
        ordered = sorted(usable, key=lambda item: item[0].c_deg)
        return SingleAxisSeries(
            axis_name="C",
            fixed_axis_name="Gamma",
            fixed_angle=gamma_values[0],
            angles=[point.c_deg for point, _ in ordered],
            values=[value for _, value in ordered],
            quantity_label=label,
            unit=unit,
        )

    return None


def _interpolate_crossing(x0, y0, x1, y1, level):
    span = y1 - y0
    if abs(span) < 1e-12:
        return (x0 + x1) / 2.0
    fraction = (level - y0) / span
    fraction = max(0.0, min(1.0, fraction))
    return x0 + fraction * (x1 - x0)


def beam_metrics(series: SingleAxisSeries | None) -> BeamMetrics:
    if series is None or not series.values:
        return BeamMetrics(None, None, None, None)

    peak_index = max(range(len(series.values)), key=series.values.__getitem__)
    peak_value = series.values[peak_index]
    peak_angle = series.angles[peak_index]
    mean_value = sum(series.values) / len(series.values)

    if peak_value <= 0.0 or len(series.values) < 3:
        return BeamMetrics(peak_value, peak_angle, mean_value, None)

    level = 0.5 * peak_value
    left_cross = None
    for index in range(peak_index, 0, -1):
        y_right = series.values[index]
        y_left = series.values[index - 1]
        if (y_left - level) * (y_right - level) <= 0.0 and y_left != y_right:
            left_cross = _interpolate_crossing(
                series.angles[index - 1], y_left,
                series.angles[index], y_right,
                level,
            )
            break

    right_cross = None
    for index in range(peak_index, len(series.values) - 1):
        y_left = series.values[index]
        y_right = series.values[index + 1]
        if (y_left - level) * (y_right - level) <= 0.0 and y_left != y_right:
            right_cross = _interpolate_crossing(
                series.angles[index], y_left,
                series.angles[index + 1], y_right,
                level,
            )
            break

    fwhm = None
    if left_cross is not None and right_cross is not None:
        fwhm = abs(right_cross - left_cross)

    return BeamMetrics(peak_value, peak_angle, mean_value, fwhm)


class ResultsCharts(QWidget):
    """Polar and Cartesian charts driven by the active MeasurementRun.

    A QStackedWidget is used instead of a nested QTabWidget.  On some Windows /
    PySide6 layouts the nested tab pane kept a valid Matplotlib canvas but gave
    its page an unusable viewport height.  The explicit stack is simpler and
    reliably gives the active FigureCanvas all remaining Results space.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run = None
        self.quantity = "Candela"
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumHeight(210)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self.note = QLabel("No plottable single-axis result is loaded.")
        self.note.setWordWrap(False)
        self.note.setObjectName("resultsChartNote")
        top.addWidget(self.note, 1)

        self.polar_button = QPushButton("Polar")
        self.cartesian_button = QPushButton("Cartesian")
        for button in (self.polar_button, self.cartesian_button):
            button.setCheckable(True)
            button.setMinimumWidth(88)
            button.setObjectName("resultsChartModeButton")
        self.polar_button.setChecked(True)

        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.polar_button, 0)
        self.view_group.addButton(self.cartesian_button, 1)
        self.view_group.idClicked.connect(self._select_view)

        top.addWidget(self.polar_button)
        top.addWidget(self.cartesian_button)
        root.addLayout(top)

        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setMinimumHeight(180)
        root.addWidget(self.stack, 1)

        self.polar_figure = Figure(figsize=(6.2, 4.2))
        self.polar_canvas = FigureCanvasQTAgg(self.polar_figure)
        self.polar_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.polar_canvas.setMinimumSize(200, 180)
        self.polar_canvas.setStyleSheet("background-color: #101820;")
        polar_page = QWidget()
        polar_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        polar_layout = QVBoxLayout(polar_page)
        polar_layout.setContentsMargins(0, 0, 0, 0)
        polar_layout.setSpacing(0)
        polar_layout.addWidget(self.polar_canvas, 1)

        self.cartesian_figure = Figure(figsize=(6.8, 4.2))
        self.cartesian_canvas = FigureCanvasQTAgg(self.cartesian_figure)
        self.cartesian_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cartesian_canvas.setMinimumSize(200, 180)
        self.cartesian_canvas.setStyleSheet("background-color: #101820;")
        cartesian_page = QWidget()
        cartesian_page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cartesian_layout = QVBoxLayout(cartesian_page)
        cartesian_layout.setContentsMargins(0, 0, 0, 0)
        cartesian_layout.setSpacing(0)
        cartesian_layout.addWidget(self.cartesian_canvas, 1)

        self.stack.addWidget(polar_page)
        self.stack.addWidget(cartesian_page)
        self.stack.setCurrentIndex(0)

        self.setStyleSheet(
            """
            QPushButton#resultsChartModeButton {
                background-color: #14212B;
                color: #D7E1E8;
                border: 1px solid #34495E;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton#resultsChartModeButton:checked {
                background-color: #1769AA;
                color: white;
                border-color: #2C7DBB;
            }
            """
        )

        self._clear_figures()

    def _select_view(self, index):
        self.stack.setCurrentIndex(index)
        self._draw_visible_canvas()

    def set_run(self, run: MeasurementRun | None):
        self.run = run
        self.refresh()
        QTimer.singleShot(0, self._draw_visible_canvas)

    def set_quantity(self, quantity: str):
        self.quantity = quantity if quantity in QUANTITY_MAP else "Candela"
        self.refresh()
        QTimer.singleShot(0, self._draw_visible_canvas)

    def active_figure(self):
        return self.polar_figure if self.stack.currentIndex() == 0 else self.cartesian_figure

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._draw_visible_canvas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._draw_visible_canvas)

    def _draw_visible_canvas(self):
        if self.stack.currentIndex() == 0:
            self.polar_canvas.draw()
        else:
            self.cartesian_canvas.draw()

    def _clear_figures(self, message="No data"):
        for figure, canvas in (
            (self.polar_figure, self.polar_canvas),
            (self.cartesian_figure, self.cartesian_canvas),
        ):
            figure.clear()
            figure.patch.set_facecolor("#101820")
            axis = figure.add_subplot(111)
            axis.set_facecolor("#111B23")
            axis.text(
                0.5,
                0.5,
                message,
                ha="center",
                va="center",
                color="#8EA6B6",
                transform=axis.transAxes,
            )
            axis.set_axis_off()
            figure.subplots_adjust(left=0.08, right=0.96, bottom=0.10, top=0.90)
            canvas.draw()

    def refresh(self):
        if self.run is None:
            self.note.setText("No plottable single-axis result is loaded.")
            self._clear_figures("No measurement result")
            return

        series = extract_single_axis_series(self.run, self.quantity)
        if series is None:
            self.note.setText(
                "This run varies both C and Gamma — Grid charts will be rendered as Heatmap, selectable planes and 3D distribution."
            )
            self._clear_figures("C × Gamma result — grid charts pending")
            return

        self.note.setText(
            f"{series.axis_name} sweep • {series.fixed_axis_name} fixed at {series.fixed_angle:+.3f}° • {series.quantity_label} ({series.unit})"
        )
        self._draw_polar(series)
        self._draw_cartesian(series)

    @staticmethod
    def _style_axis(axis):
        axis.set_facecolor("#111B23")
        axis.tick_params(colors="#B9CAD6")
        axis.grid(True, alpha=0.30)
        for spine in axis.spines.values():
            spine.set_color("#40586A")

    def _draw_polar(self, series: SingleAxisSeries):
        self.polar_figure.clear()
        self.polar_figure.patch.set_facecolor("#101820")
        axis = self.polar_figure.add_subplot(111, projection="polar")
        axis.set_facecolor("#111B23")
        axis.set_theta_zero_location("N")
        axis.set_theta_direction(-1)

        theta = [math.radians(angle) for angle in series.angles]
        axis.plot(theta, series.values, marker="o", linewidth=2.0, markersize=4.0)
        axis.fill(theta, series.values, alpha=0.08)

        max_abs = max(10.0, max(abs(value) for value in series.angles))
        half_span = min(
            180.0,
            max(30.0, math.ceil((max_abs + 5.0) / 10.0) * 10.0),
        )
        axis.set_thetamin(-half_span)
        axis.set_thetamax(half_span)
        axis.set_rmin(0.0)

        if series.values:
            vmax = max(series.values)
            if vmax > 0:
                axis.set_rmax(vmax * 1.10)

        axis.grid(True, alpha=0.32)
        axis.tick_params(colors="#B9CAD6")
        axis.spines["polar"].set_color("#40586A")
        axis.set_title(
            f"Polar {series.quantity_label} • {series.axis_name} plane",
            color="#E4EEF5",
            pad=14,
            fontweight="bold",
        )
        self.polar_figure.subplots_adjust(left=0.06, right=0.94, bottom=0.08, top=0.88)
        self.polar_canvas.draw()

    def _draw_cartesian(self, series: SingleAxisSeries):
        self.cartesian_figure.clear()
        self.cartesian_figure.patch.set_facecolor("#101820")
        axis = self.cartesian_figure.add_subplot(111)
        self._style_axis(axis)

        axis.plot(
            series.angles,
            series.values,
            marker="o",
            linewidth=2.0,
            markersize=4.0,
        )
        axis.set_xlabel(f"{series.axis_name} angle (°)", color="#CFDDE6")
        axis.set_ylabel(f"{series.quantity_label} ({series.unit})", color="#CFDDE6")
        axis.set_title(
            f"{series.quantity_label} vs {series.axis_name} angle",
            color="#E4EEF5",
            fontweight="bold",
        )
        axis.axvline(0.0, linewidth=0.8, alpha=0.35)
        self.cartesian_figure.subplots_adjust(left=0.10, right=0.97, bottom=0.16, top=0.86)
        self.cartesian_canvas.draw()
