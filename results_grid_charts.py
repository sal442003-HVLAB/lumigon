"""C × Gamma grid analysis and visualization for Lumigon Results.

This module is intentionally separate from the proven single-axis
Polar/Cartesian implementation.  A completed grid can therefore add Heatmap,
selectable C/Gamma planes and 3D views without changing single-axis behaviour.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from measurement_run import MeasurementRun
from results_charts import CALCULATED_LUX, QUANTITY_MAP, SingleAxisSeries


@dataclass(frozen=True)
class GridData:
    c_values: list[float]
    gamma_values: list[float]
    values: np.ndarray
    quantity_label: str
    unit: str
    measured_cells: int
    total_cells: int


def _unique(values, tolerance=1e-6):
    result = []
    for value in sorted(float(v) for v in values):
        if not result or abs(value - result[-1]) > tolerance:
            result.append(value)
    return result


def _point_value(point, quantity, calculated_distance_m):
    attr, label, unit = QUANTITY_MAP.get(quantity, QUANTITY_MAP["Candela"])
    if quantity == CALCULATED_LUX:
        try:
            distance_m = float(calculated_distance_m)
        except (TypeError, ValueError):
            return None, label, unit
        if not math.isfinite(distance_m) or distance_m <= 0.0:
            return None, label, unit
        attr = "candela_cd"
        label = f"Calculated illuminance @ {distance_m:g} m"
    else:
        distance_m = None

    source = getattr(point, attr, None)
    if source is None:
        return None, label, unit
    try:
        value = float(source)
    except (TypeError, ValueError):
        return None, label, unit
    if not math.isfinite(value):
        return None, label, unit
    if quantity == CALCULATED_LUX:
        value /= distance_m * distance_m
    return value, label, unit


def extract_grid_data(
    run: MeasurementRun | None,
    quantity: str = "Candela",
    calculated_distance_m: float | None = None,
) -> GridData | None:
    """Build a rectangular C × Gamma matrix from a MeasurementRun.

    Missing cells remain NaN, so interrupted or partially repeated grids can be
    visualized without inventing measurements. Duplicate coordinates are
    averaged rather than silently choosing one acquisition.
    """

    if run is None:
        return None

    usable = []
    quantity_label = QUANTITY_MAP.get(quantity, QUANTITY_MAP["Candela"])[1]
    unit = QUANTITY_MAP.get(quantity, QUANTITY_MAP["Candela"])[2]
    for point in run.points:
        value, quantity_label, unit = _point_value(
            point,
            quantity,
            calculated_distance_m,
        )
        if value is not None:
            usable.append((float(point.c_deg), float(point.gamma_deg), value))

    if not usable:
        return None

    c_values = _unique([item[0] for item in usable], tolerance=1e-4)
    gamma_values = _unique([item[1] for item in usable], tolerance=1e-4)
    if len(c_values) < 2 or len(gamma_values) < 2:
        return None

    c_index = {round(value, 6): index for index, value in enumerate(c_values)}
    gamma_index = {
        round(value, 6): index for index, value in enumerate(gamma_values)
    }
    buckets: dict[tuple[int, int], list[float]] = {}
    for c_deg, gamma_deg, value in usable:
        ci = c_index.get(round(c_deg, 6))
        gi = gamma_index.get(round(gamma_deg, 6))
        if ci is None or gi is None:
            continue
        buckets.setdefault((ci, gi), []).append(float(value))

    matrix = np.full((len(c_values), len(gamma_values)), np.nan, dtype=float)
    for (ci, gi), values in buckets.items():
        matrix[ci, gi] = float(sum(values) / len(values))

    measured_cells = int(np.count_nonzero(np.isfinite(matrix)))
    total_cells = int(matrix.size)
    return GridData(
        c_values=c_values,
        gamma_values=gamma_values,
        values=matrix,
        quantity_label=quantity_label,
        unit=unit,
        measured_cells=measured_cells,
        total_cells=total_cells,
    )


def extract_grid_plane(
    grid: GridData,
    family: str,
    fixed_value: float,
) -> SingleAxisSeries | None:
    """Extract one physical plane from a C × Gamma matrix."""

    if family == "C":
        index = min(
            range(len(grid.c_values)),
            key=lambda i: abs(grid.c_values[i] - fixed_value),
        )
        values = grid.values[index, :]
        pairs = [
            (angle, float(value))
            for angle, value in zip(grid.gamma_values, values)
            if np.isfinite(value)
        ]
        if not pairs:
            return None
        return SingleAxisSeries(
            axis_name="Gamma",
            fixed_axis_name="C",
            fixed_angle=grid.c_values[index],
            angles=[pair[0] for pair in pairs],
            values=[pair[1] for pair in pairs],
            quantity_label=grid.quantity_label,
            unit=grid.unit,
        )

    index = min(
        range(len(grid.gamma_values)),
        key=lambda i: abs(grid.gamma_values[i] - fixed_value),
    )
    values = grid.values[:, index]
    pairs = [
        (angle, float(value))
        for angle, value in zip(grid.c_values, values)
        if np.isfinite(value)
    ]
    if not pairs:
        return None
    return SingleAxisSeries(
        axis_name="C",
        fixed_axis_name="Gamma",
        fixed_angle=grid.gamma_values[index],
        angles=[pair[0] for pair in pairs],
        values=[pair[1] for pair in pairs],
        quantity_label=grid.quantity_label,
        unit=grid.unit,
    )


class GridResultsCharts(QWidget):
    """Heatmap, selectable plane and 3D visualization for C × Gamma runs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.run = None
        self.quantity = "Candela"
        self.calculation_distance_m = 10.0
        self.grid_data: GridData | None = None

        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(5)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)

        self.note = QLabel("No C × Gamma grid is loaded.")
        self.note.setObjectName("resultsChartNote")
        self.note.setMinimumWidth(0)
        self.note.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.note, 1)

        self.heatmap_button = QPushButton("Heatmap")
        self.plane_button = QPushButton("Plane")
        self.distribution_button = QPushButton("3D Distribution")
        for button in (
            self.heatmap_button,
            self.plane_button,
            self.distribution_button,
        ):
            button.setCheckable(True)
            button.setObjectName("resultsChartModeButton")
        self.heatmap_button.setChecked(True)

        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.heatmap_button, 0)
        self.view_group.addButton(self.plane_button, 1)
        self.view_group.addButton(self.distribution_button, 2)
        self.view_group.idClicked.connect(self._select_view)

        top.addWidget(self.heatmap_button)
        top.addWidget(self.plane_button)
        top.addWidget(self.distribution_button)
        root.addLayout(top)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)

        self.plane_controls = QWidget()
        plane_controls_layout = QHBoxLayout(self.plane_controls)
        plane_controls_layout.setContentsMargins(0, 0, 0, 0)
        plane_controls_layout.setSpacing(6)
        plane_controls_layout.addWidget(QLabel("Plane:"))

        self.plane_family_combo = QComboBox()
        self.plane_family_combo.addItem("C fixed / Gamma sweep", "C")
        self.plane_family_combo.addItem("Gamma fixed / C sweep", "Gamma")
        self.plane_family_combo.currentIndexChanged.connect(self._plane_family_changed)
        plane_controls_layout.addWidget(self.plane_family_combo)

        self.plane_value_combo = QComboBox()
        self.plane_value_combo.currentIndexChanged.connect(self._plane_control_changed)
        plane_controls_layout.addWidget(self.plane_value_combo)

        self.plane_view_combo = QComboBox()
        self.plane_view_combo.addItems(["Polar", "Cartesian"])
        self.plane_view_combo.currentIndexChanged.connect(self._plane_control_changed)
        plane_controls_layout.addWidget(self.plane_view_combo)
        controls.addWidget(self.plane_controls)

        self.distribution_controls = QWidget()
        distribution_layout = QHBoxLayout(self.distribution_controls)
        distribution_layout.setContentsMargins(0, 0, 0, 0)
        distribution_layout.setSpacing(6)
        distribution_layout.addWidget(QLabel("3D view:"))
        self.distribution_view_combo = QComboBox()
        self.distribution_view_combo.addItems([
            "Photometric solid",
            "C / Gamma surface",
        ])
        self.distribution_view_combo.currentIndexChanged.connect(
            self._distribution_control_changed
        )
        distribution_layout.addWidget(self.distribution_view_combo)
        controls.addWidget(self.distribution_controls)
        controls.addStretch(1)
        root.addLayout(controls)

        self.stack = QStackedWidget()
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        root.addWidget(self.stack, 1)

        self.heatmap_figure = Figure(figsize=(7.0, 4.8))
        self.heatmap_canvas = FigureCanvasQTAgg(self.heatmap_figure)
        heatmap_page = self._canvas_page(self.heatmap_canvas)

        self.plane_figure = Figure(figsize=(7.0, 4.8))
        self.plane_canvas = FigureCanvasQTAgg(self.plane_figure)
        plane_page = self._canvas_page(self.plane_canvas)

        self.distribution_figure = Figure(figsize=(7.4, 5.2))
        self.distribution_canvas = FigureCanvasQTAgg(self.distribution_figure)
        distribution_page = self._canvas_page(self.distribution_canvas)

        self.stack.addWidget(heatmap_page)
        self.stack.addWidget(plane_page)
        self.stack.addWidget(distribution_page)
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

        self._sync_control_visibility()
        self._clear_all("No C × Gamma grid")

    @staticmethod
    def _configure_canvas(canvas):
        canvas.setMinimumSize(0, 0)
        canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        canvas.setStyleSheet("background-color: #101820;")

    def _canvas_page(self, canvas):
        self._configure_canvas(canvas)
        page = QWidget()
        page.setMinimumSize(0, 0)
        page.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(canvas, 1)
        return page

    def _select_view(self, index):
        self.stack.setCurrentIndex(index)
        self._sync_control_visibility()
        self.refresh_active_view()

    def _sync_control_visibility(self):
        index = self.stack.currentIndex()
        self.plane_controls.setVisible(index == 1)
        self.distribution_controls.setVisible(index == 2)

    def set_run(self, run: MeasurementRun | None):
        self.run = run
        self.refresh()

    def set_quantity(self, quantity: str):
        self.quantity = quantity if quantity in QUANTITY_MAP else "Candela"
        self.refresh()

    def set_calculation_distance(self, distance_m: float):
        try:
            distance_m = float(distance_m)
        except (TypeError, ValueError):
            return
        if not math.isfinite(distance_m) or distance_m <= 0.0:
            return
        self.calculation_distance_m = distance_m
        if self.quantity == CALCULATED_LUX:
            self.refresh()

    def active_figure(self):
        index = self.stack.currentIndex()
        if index == 1:
            return self.plane_figure
        if index == 2:
            return self.distribution_figure
        return self.heatmap_figure

    def active_view_name(self):
        return ("heatmap", "plane", "3d")[self.stack.currentIndex()]

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._draw_visible_canvas)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._draw_visible_canvas)

    def _draw_visible_canvas(self):
        canvas = (
            self.heatmap_canvas,
            self.plane_canvas,
            self.distribution_canvas,
        )[self.stack.currentIndex()]
        if canvas.width() > 1 and canvas.height() > 1:
            canvas.draw()

    def _plane_family_changed(self, *_args):
        self._populate_plane_values()
        self.refresh_active_view()

    def _plane_control_changed(self, *_args):
        self.refresh_active_view()

    def _distribution_control_changed(self, *_args):
        self.refresh_active_view()

    def _populate_plane_values(self):
        self.plane_value_combo.blockSignals(True)
        self.plane_value_combo.clear()
        grid = self.grid_data
        if grid is not None:
            family = self.plane_family_combo.currentData()
            values = grid.c_values if family == "C" else grid.gamma_values
            if values:
                # Prefer the plane physically closest to zero.
                zero_index = min(range(len(values)), key=lambda i: abs(values[i]))
                for value in values:
                    self.plane_value_combo.addItem(f"{value:+.3f}°", float(value))
                self.plane_value_combo.setCurrentIndex(zero_index)
        self.plane_value_combo.blockSignals(False)

    def refresh(self):
        self.grid_data = extract_grid_data(
            self.run,
            self.quantity,
            self.calculation_distance_m,
        )
        if self.grid_data is None:
            self.note.setText("No plottable C × Gamma grid is loaded.")
            self._clear_all("No C × Gamma grid")
            return

        grid = self.grid_data
        self.note.setText(
            f"C × Gamma grid • {len(grid.c_values)} C positions × "
            f"{len(grid.gamma_values)} Gamma positions • "
            f"{grid.measured_cells}/{grid.total_cells} cells • "
            f"{grid.quantity_label} ({grid.unit})"
        )
        self.note.setToolTip(self.note.text())
        self._populate_plane_values()
        self._draw_heatmap()
        self._draw_plane()
        self._draw_distribution()
        QTimer.singleShot(0, self._draw_visible_canvas)

    def refresh_active_view(self):
        if self.grid_data is None:
            return
        index = self.stack.currentIndex()
        if index == 1:
            self._draw_plane()
        elif index == 2:
            self._draw_distribution()
        else:
            self._draw_heatmap()
        QTimer.singleShot(0, self._draw_visible_canvas)

    @staticmethod
    def _style_axis(axis):
        axis.set_facecolor("#111B23")
        axis.tick_params(colors="#B9CAD6")
        axis.grid(True, alpha=0.25)
        for spine in axis.spines.values():
            spine.set_color("#40586A")

    @staticmethod
    def _clear_figure(figure, canvas, message):
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
        canvas.draw()

    def _clear_all(self, message):
        for figure, canvas in (
            (self.heatmap_figure, self.heatmap_canvas),
            (self.plane_figure, self.plane_canvas),
            (self.distribution_figure, self.distribution_canvas),
        ):
            self._clear_figure(figure, canvas, message)

    def _draw_heatmap(self):
        grid = self.grid_data
        if grid is None:
            return
        self.heatmap_figure.clear()
        self.heatmap_figure.patch.set_facecolor("#101820")
        axis = self.heatmap_figure.add_subplot(111)
        self._style_axis(axis)

        z = np.ma.masked_invalid(grid.values)
        mesh = axis.pcolormesh(
            np.asarray(grid.gamma_values),
            np.asarray(grid.c_values),
            z,
            shading="auto",
        )
        colorbar = self.heatmap_figure.colorbar(mesh, ax=axis, pad=0.02)
        colorbar.set_label(f"{grid.quantity_label} ({grid.unit})", color="#CFDDE6")
        colorbar.ax.tick_params(colors="#B9CAD6")

        axis.set_xlabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_ylabel("C angle (°)", color="#CFDDE6")
        axis.set_title(
            f"C × Gamma Heatmap • {grid.quantity_label}",
            color="#E4EEF5",
            fontweight="bold",
        )
        self.heatmap_figure.subplots_adjust(left=0.09, right=0.92, bottom=0.13, top=0.88)
        self.heatmap_canvas.draw()

    def _selected_plane(self):
        grid = self.grid_data
        if grid is None or self.plane_value_combo.count() == 0:
            return None
        family = self.plane_family_combo.currentData() or "C"
        fixed_value = self.plane_value_combo.currentData()
        if fixed_value is None:
            return None
        return extract_grid_plane(grid, family, float(fixed_value))

    def _draw_plane(self):
        series = self._selected_plane()
        if series is None:
            self._clear_figure(self.plane_figure, self.plane_canvas, "No plane data")
            return

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor("#101820")
        if self.plane_view_combo.currentText() == "Polar":
            axis = self.plane_figure.add_subplot(111, projection="polar")
            axis.set_facecolor("#111B23")
            axis.set_theta_zero_location("N")
            axis.set_theta_direction(-1)
            theta = np.radians(np.asarray(series.angles, dtype=float))
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
            vmax = max(series.values) if series.values else 0.0
            if vmax > 0.0:
                axis.set_rmax(vmax * 1.10)
            axis.grid(True, alpha=0.30)
            axis.tick_params(colors="#B9CAD6")
            axis.spines["polar"].set_color("#40586A")
            axis.set_title(
                f"{series.fixed_axis_name} {series.fixed_angle:+.3f}° • "
                f"{series.axis_name} polar plane",
                color="#E4EEF5",
                pad=14,
                fontweight="bold",
            )
            self.plane_figure.subplots_adjust(
                left=0.06,
                right=0.94,
                bottom=0.08,
                top=0.88,
            )
        else:
            axis = self.plane_figure.add_subplot(111)
            self._style_axis(axis)
            axis.plot(
                series.angles,
                series.values,
                marker="o",
                linewidth=2.0,
                markersize=4.0,
            )
            axis.set_xlabel(f"{series.axis_name} angle (°)", color="#CFDDE6")
            axis.set_ylabel(
                f"{series.quantity_label} ({series.unit})",
                color="#CFDDE6",
            )
            axis.set_title(
                f"{series.fixed_axis_name} {series.fixed_angle:+.3f}° plane",
                color="#E4EEF5",
                fontweight="bold",
            )
            axis.axvline(0.0, linewidth=0.8, alpha=0.35)
            self.plane_figure.subplots_adjust(
                left=0.10,
                right=0.97,
                bottom=0.15,
                top=0.87,
            )
        self.plane_canvas.draw()

    def _draw_distribution(self):
        grid = self.grid_data
        if grid is None:
            return

        self.distribution_figure.clear()
        self.distribution_figure.patch.set_facecolor("#101820")
        axis = self.distribution_figure.add_subplot(111, projection="3d")
        axis.set_facecolor("#111B23")

        gamma_mesh, c_mesh = np.meshgrid(
            np.asarray(grid.gamma_values, dtype=float),
            np.asarray(grid.c_values, dtype=float),
        )
        radial = np.asarray(grid.values, dtype=float)
        radial = np.where(np.isfinite(radial), radial, np.nan)

        if self.distribution_view_combo.currentText() == "C / Gamma surface":
            axis.plot_surface(
                gamma_mesh,
                c_mesh,
                radial,
                linewidth=0,
                antialiased=True,
            )
            axis.set_xlabel("Gamma (°)")
            axis.set_ylabel("C (°)")
            axis.set_zlabel(f"{grid.quantity_label} ({grid.unit})")
            title = f"3D C / Gamma Surface • {grid.quantity_label}"
        else:
            # Development photometric solid around the optical +Z direction.
            # Signed Gamma bends in X and signed C bends in Y. This is a useful
            # local visualization for the present ± angular scans; the final
            # standard C-γ coordinate convention can later replace this mapping
            # without changing the stored measurement data.
            c_rad = np.radians(c_mesh)
            gamma_rad = np.radians(gamma_mesh)
            positive_radial = np.where(radial >= 0.0, radial, 0.0)
            x = positive_radial * np.sin(gamma_rad)
            y = positive_radial * np.sin(c_rad) * np.cos(gamma_rad)
            z = positive_radial * np.cos(c_rad) * np.cos(gamma_rad)
            axis.plot_surface(x, y, z, linewidth=0, antialiased=True)
            axis.set_xlabel("Gamma-side distribution")
            axis.set_ylabel("C-side distribution")
            axis.set_zlabel(f"Optical-axis {grid.unit}")
            title = f"3D Photometric Solid • radius = {grid.quantity_label}"

        axis.set_title(title, color="#E4EEF5", fontweight="bold", pad=12)
        axis.tick_params(colors="#B9CAD6")
        axis.xaxis.label.set_color("#CFDDE6")
        axis.yaxis.label.set_color("#CFDDE6")
        axis.zaxis.label.set_color("#CFDDE6")
        self.distribution_figure.subplots_adjust(
            left=0.02,
            right=0.98,
            bottom=0.04,
            top=0.90,
        )
        self.distribution_canvas.draw()
