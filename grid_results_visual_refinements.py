"""Visual refinements for Lumigon C × Gamma result charts.

This is presentation-only: stored MeasurementRun data are never modified.
It adds an absolute/relative display scale, measured-angle ticks and peak markers
for Heatmap, Plane and 3D Grid views.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtWidgets import QComboBox, QLabel

from results_charts import SingleAxisSeries
from results_grid_charts import GridResultsCharts


RELATIVE_SCALE_TEXT = "Relative to Imax (%)"
ABSOLUTE_SCALE_TEXT = "Absolute"


def _angle_text(value: float) -> str:
    value = float(value)
    if abs(value) < 5e-7:
        return "0°"
    if abs(value - round(value)) < 1e-6:
        return f"{value:+.0f}°"
    return f"{value:+.2f}°".rstrip("0").rstrip(".") + "°"


def _measured_ticks(values, max_ticks=13):
    values = [float(v) for v in values]
    if len(values) <= max_ticks:
        return values
    indices = np.linspace(0, len(values) - 1, max_ticks).round().astype(int)
    selected = [values[int(i)] for i in sorted(set(indices.tolist()))]
    if values:
        zero = min(values, key=abs)
        if abs(zero) <= max(1e-6, (max(values) - min(values)) / max(1, len(values) - 1)):
            selected.append(zero)
    return sorted(set(selected))


def _display_matrix(widget):
    grid = widget.grid_data
    if grid is None:
        return None, "", ""
    values = np.asarray(grid.values, dtype=float).copy()
    label = grid.quantity_label
    unit = grid.unit
    relative = (
        hasattr(widget, "grid_scale_combo")
        and widget.grid_scale_combo.currentText() == RELATIVE_SCALE_TEXT
    )
    if relative:
        finite = values[np.isfinite(values)]
        peak = float(np.max(finite)) if finite.size else 0.0
        if peak > 0.0:
            values = values / peak * 100.0
        label = "Relative intensity"
        unit = "% of Imax"
    return values, label, unit


def _display_series(widget, series):
    if series is None:
        return None
    if not (
        hasattr(widget, "grid_scale_combo")
        and widget.grid_scale_combo.currentText() == RELATIVE_SCALE_TEXT
    ):
        return series
    peak = max(series.values) if series.values else 0.0
    values = [value / peak * 100.0 for value in series.values] if peak > 0.0 else list(series.values)
    return SingleAxisSeries(
        axis_name=series.axis_name,
        fixed_axis_name=series.fixed_axis_name,
        fixed_angle=series.fixed_angle,
        angles=list(series.angles),
        values=values,
        quantity_label="Relative intensity",
        unit="% of Imax",
    )


def install_grid_results_visual_refinements():
    if getattr(GridResultsCharts, "_lumigon_visual_refinements", False):
        return
    GridResultsCharts._lumigon_visual_refinements = True

    original_init = GridResultsCharts.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        root = self.layout()
        controls = root.itemAt(1).layout() if root is not None and root.count() > 1 else None
        if controls is not None:
            controls.addWidget(QLabel("Scale:"))
            self.grid_scale_combo = QComboBox()
            self.grid_scale_combo.addItems([ABSOLUTE_SCALE_TEXT, RELATIVE_SCALE_TEXT])
            self.grid_scale_combo.setToolTip(
                "Absolute shows stored photometric values. Relative normalizes the active grid/plane to Imax = 100%."
            )
            self.grid_scale_combo.currentIndexChanged.connect(self.refresh_active_view)
            controls.addWidget(self.grid_scale_combo)

    def patched_draw_heatmap(self):
        grid = self.grid_data
        if grid is None:
            return
        values, label, unit = _display_matrix(self)

        self.heatmap_figure.clear()
        self.heatmap_figure.patch.set_facecolor("#101820")
        axis = self.heatmap_figure.add_subplot(111)
        self._style_axis(axis)

        z = np.ma.masked_invalid(values)
        mesh = axis.pcolormesh(
            np.asarray(grid.gamma_values),
            np.asarray(grid.c_values),
            z,
            shading="auto",
        )
        colorbar = self.heatmap_figure.colorbar(mesh, ax=axis, pad=0.02)
        colorbar.set_label(f"{label} ({unit})", color="#CFDDE6")
        colorbar.ax.tick_params(colors="#B9CAD6")

        xticks = _measured_ticks(grid.gamma_values)
        yticks = _measured_ticks(grid.c_values)
        axis.set_xticks(xticks)
        axis.set_xticklabels([_angle_text(v) for v in xticks])
        axis.set_yticks(yticks)
        axis.set_yticklabels([_angle_text(v) for v in yticks])

        finite = np.isfinite(values)
        if np.any(finite):
            peak_flat = int(np.nanargmax(values))
            ci, gi = np.unravel_index(peak_flat, values.shape)
            peak_c = grid.c_values[ci]
            peak_gamma = grid.gamma_values[gi]
            axis.scatter([peak_gamma], [peak_c], marker="*", s=150, zorder=5)
            axis.annotate(
                "Imax",
                (peak_gamma, peak_c),
                xytext=(7, 7),
                textcoords="offset points",
                color="#E4EEF5",
                fontweight="bold",
            )

        axis.set_xlabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_ylabel("C angle (°)", color="#CFDDE6")
        axis.set_title(
            f"C × Gamma Heatmap • {label}",
            color="#E4EEF5",
            fontweight="bold",
        )
        self.heatmap_figure.subplots_adjust(left=0.09, right=0.92, bottom=0.13, top=0.88)
        self.heatmap_canvas.draw()

    def patched_draw_plane(self):
        source_series = self._selected_plane()
        series = _display_series(self, source_series)
        if series is None:
            self._clear_figure(self.plane_figure, self.plane_canvas, "No plane data")
            return

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor("#101820")
        peak_index = max(range(len(series.values)), key=series.values.__getitem__) if series.values else None

        if self.plane_view_combo.currentText() == "Polar":
            axis = self.plane_figure.add_subplot(111, projection="polar")
            axis.set_facecolor("#111B23")
            axis.set_theta_zero_location("N")
            axis.set_theta_direction(-1)
            theta = np.radians(np.asarray(series.angles, dtype=float))
            axis.plot(theta, series.values, marker="o", linewidth=2.0, markersize=4.0)
            axis.fill(theta, series.values, alpha=0.08)

            measured_ticks = _measured_ticks(series.angles, max_ticks=11)
            axis.set_thetagrids(
                measured_ticks,
                labels=[_angle_text(v) for v in measured_ticks],
            )
            max_abs = max(10.0, max(abs(value) for value in series.angles))
            half_span = min(180.0, max(30.0, math.ceil((max_abs + 5.0) / 10.0) * 10.0))
            axis.set_thetamin(-half_span)
            axis.set_thetamax(half_span)
            axis.set_rmin(0.0)
            vmax = max(series.values) if series.values else 0.0
            if vmax > 0.0:
                axis.set_rmax(105.0 if series.unit == "% of Imax" else vmax * 1.10)
            if peak_index is not None:
                axis.scatter([theta[peak_index]], [series.values[peak_index]], marker="*", s=120, zorder=5)
            axis.grid(True, alpha=0.30)
            axis.tick_params(colors="#B9CAD6")
            axis.spines["polar"].set_color("#40586A")
            axis.set_title(
                f"{series.fixed_axis_name} {series.fixed_angle:+.3f}° • {series.axis_name} polar plane • {series.quantity_label}",
                color="#E4EEF5",
                pad=14,
                fontweight="bold",
            )
            self.plane_figure.subplots_adjust(left=0.06, right=0.94, bottom=0.08, top=0.88)
        else:
            axis = self.plane_figure.add_subplot(111)
            self._style_axis(axis)
            axis.plot(series.angles, series.values, marker="o", linewidth=2.0, markersize=4.0)
            ticks = _measured_ticks(series.angles)
            axis.set_xticks(ticks)
            axis.set_xticklabels([_angle_text(v) for v in ticks])
            if peak_index is not None:
                axis.scatter(
                    [series.angles[peak_index]],
                    [series.values[peak_index]],
                    marker="*",
                    s=120,
                    zorder=5,
                )
                axis.annotate(
                    "Imax",
                    (series.angles[peak_index], series.values[peak_index]),
                    xytext=(7, 7),
                    textcoords="offset points",
                    color="#E4EEF5",
                    fontweight="bold",
                )
            axis.set_xlabel(f"{series.axis_name} angle (°)", color="#CFDDE6")
            axis.set_ylabel(f"{series.quantity_label} ({series.unit})", color="#CFDDE6")
            axis.set_title(
                f"{series.fixed_axis_name} {series.fixed_angle:+.3f}° plane",
                color="#E4EEF5",
                fontweight="bold",
            )
            axis.axvline(0.0, linewidth=0.8, alpha=0.35)
            self.plane_figure.subplots_adjust(left=0.10, right=0.97, bottom=0.15, top=0.87)
        self.plane_canvas.draw()

    def patched_draw_distribution(self):
        grid = self.grid_data
        if grid is None:
            return
        radial, label, unit = _display_matrix(self)

        self.distribution_figure.clear()
        self.distribution_figure.patch.set_facecolor("#101820")
        axis = self.distribution_figure.add_subplot(111, projection="3d")
        axis.set_facecolor("#111B23")

        gamma_mesh, c_mesh = np.meshgrid(
            np.asarray(grid.gamma_values, dtype=float),
            np.asarray(grid.c_values, dtype=float),
        )
        radial = np.where(np.isfinite(radial), radial, np.nan)
        peak_flat = int(np.nanargmax(radial)) if np.any(np.isfinite(radial)) else None

        if self.distribution_view_combo.currentText() == "C / Gamma surface":
            axis.plot_surface(gamma_mesh, c_mesh, radial, linewidth=0, antialiased=True)
            xticks = _measured_ticks(grid.gamma_values)
            yticks = _measured_ticks(grid.c_values)
            axis.set_xticks(xticks)
            axis.set_xticklabels([_angle_text(v) for v in xticks])
            axis.set_yticks(yticks)
            axis.set_yticklabels([_angle_text(v) for v in yticks])
            axis.set_xlabel("Gamma")
            axis.set_ylabel("C")
            axis.set_zlabel(f"{label} ({unit})")
            title = f"3D C / Gamma Surface • {label}"
            if peak_flat is not None:
                ci, gi = np.unravel_index(peak_flat, radial.shape)
                axis.scatter(
                    [grid.gamma_values[gi]],
                    [grid.c_values[ci]],
                    [radial[ci, gi]],
                    marker="*",
                    s=120,
                )
                axis.text(
                    grid.gamma_values[gi],
                    grid.c_values[ci],
                    radial[ci, gi],
                    " Imax",
                    color="#E4EEF5",
                )
        else:
            c_rad = np.radians(c_mesh)
            gamma_rad = np.radians(gamma_mesh)
            positive_radial = np.where(radial >= 0.0, radial, 0.0)
            x = positive_radial * np.sin(gamma_rad)
            y = positive_radial * np.sin(c_rad) * np.cos(gamma_rad)
            z = positive_radial * np.cos(c_rad) * np.cos(gamma_rad)
            axis.plot_surface(x, y, z, linewidth=0, antialiased=True)
            axis.set_xlabel("Gamma-side distribution")
            axis.set_ylabel("C-side distribution")
            axis.set_zlabel(f"Optical-axis {unit}")
            title = f"3D Photometric Solid • radius = {label}"
            if peak_flat is not None:
                ci, gi = np.unravel_index(peak_flat, radial.shape)
                axis.scatter([x[ci, gi]], [y[ci, gi]], [z[ci, gi]], marker="*", s=120)
                axis.text(x[ci, gi], y[ci, gi], z[ci, gi], " Imax", color="#E4EEF5")

        axis.set_title(title, color="#E4EEF5", fontweight="bold", pad=12)
        axis.tick_params(colors="#B9CAD6")
        axis.xaxis.label.set_color("#CFDDE6")
        axis.yaxis.label.set_color("#CFDDE6")
        axis.zaxis.label.set_color("#CFDDE6")
        self.distribution_figure.subplots_adjust(left=0.02, right=0.98, bottom=0.04, top=0.90)
        self.distribution_canvas.draw()

    GridResultsCharts.__init__ = patched_init
    GridResultsCharts._draw_heatmap = patched_draw_heatmap
    GridResultsCharts._draw_plane = patched_draw_plane
    GridResultsCharts._draw_distribution = patched_draw_distribution
