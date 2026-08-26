"""EULUMDAT-specific Results refinements for imported full C-gamma photometry.

Lumigon's native commissioning grids use signed local C/Gamma motion.  A full
EULUMDAT data set has a different, standard photometric interpretation: C is an
azimuth around the optical axis and gamma is the polar angle.  This layer is
activated only for imported/full EULUMDAT runs so native Lumigon grid behaviour
is unchanged.
"""

from __future__ import annotations

import math

import numpy as np

from results_charts import SingleAxisSeries
from results_grid_charts import GridResultsCharts
from grid_results_visual_refinements import _display_matrix, _display_series, _measured_ticks, _angle_text


C_PAIR_DATA = "C_PAIR"
C_PAIR_TEXT = "Opposite C planes (C / C+180)"


def _is_eulumdat_run(widget) -> bool:
    run = getattr(widget, "run", None)
    grid = getattr(widget, "grid_data", None)
    if run is None or grid is None:
        return False

    metadata = " ".join(
        str(value or "")
        for value in (
            getattr(run, "profile", ""),
            getattr(run, "scan_mode", ""),
            getattr(run, "execution_mode", ""),
            getattr(run, "standard", ""),
        )
    ).upper()
    if "EULUMDAT" in metadata or "IMPORTED LDT" in metadata:
        return True

    c_values = grid.c_values
    gamma_values = grid.gamma_values
    return bool(
        len(c_values) >= 4
        and len(gamma_values) >= 3
        and (max(c_values) - min(c_values)) >= 300.0
        and min(gamma_values) >= -1e-6
        and max(gamma_values) >= 170.0
    )


def _nearest_index(values, target):
    return min(range(len(values)), key=lambda i: abs(float(values[i]) - float(target)))


def _opposite_c_pairs(grid):
    values = [float(v) for v in grid.c_values]
    if not values:
        return []

    pairs = []
    for base in values:
        base_mod = base % 360.0
        if base_mod >= 180.0 - 1e-6:
            continue
        opposite = (base_mod + 180.0) % 360.0
        oi = _nearest_index(values, opposite)
        if abs((values[oi] % 360.0) - opposite) <= 0.51 * max(
            0.1,
            min(
                [abs(values[i + 1] - values[i]) for i in range(len(values) - 1)]
                or [1.0]
            ),
        ):
            pairs.append((base, values[oi]))
    return pairs


def _paired_plane_series(widget):
    grid = widget.grid_data
    if grid is None or widget.plane_value_combo.count() == 0:
        return None, None, None

    base_c = widget.plane_value_combo.currentData()
    if base_c is None:
        return None, None, None
    base_c = float(base_c)
    opposite_c = (base_c + 180.0) % 360.0

    bi = _nearest_index(grid.c_values, base_c)
    oi = _nearest_index(grid.c_values, opposite_c)

    base_values = grid.values[bi, :]
    opposite_values = grid.values[oi, :]

    samples = {}
    for gamma, value in zip(grid.gamma_values, opposite_values):
        if np.isfinite(value):
            samples.setdefault(round(-float(gamma), 6), []).append(float(value))
    for gamma, value in zip(grid.gamma_values, base_values):
        if np.isfinite(value):
            samples.setdefault(round(float(gamma), 6), []).append(float(value))

    if not samples:
        return None, base_c, float(grid.c_values[oi])

    ordered_angles = sorted(samples)
    values = [sum(samples[a]) / len(samples[a]) for a in ordered_angles]
    series = SingleAxisSeries(
        axis_name="Gamma",
        fixed_axis_name="C-pair",
        fixed_angle=base_c,
        angles=[float(a) for a in ordered_angles],
        values=values,
        quantity_label=grid.quantity_label,
        unit=grid.unit,
    )
    return series, base_c, float(grid.c_values[oi])


def install_eulumdat_results_refinements():
    """Patch GridResultsCharts after the general visual refinements are installed."""

    if getattr(GridResultsCharts, "_lumigon_eulumdat_refinements", False):
        return
    GridResultsCharts._lumigon_eulumdat_refinements = True

    original_set_run = GridResultsCharts.set_run
    original_populate = GridResultsCharts._populate_plane_values
    original_draw_plane = GridResultsCharts._draw_plane
    original_draw_distribution = GridResultsCharts._draw_distribution

    def patched_set_run(self, run):
        original_set_run(self, run)

        pair_index = self.plane_family_combo.findData(C_PAIR_DATA)
        is_ldt = _is_eulumdat_run(self)
        if is_ldt and pair_index < 0:
            self.plane_family_combo.addItem(C_PAIR_TEXT, C_PAIR_DATA)
            pair_index = self.plane_family_combo.findData(C_PAIR_DATA)
        elif not is_ldt and pair_index >= 0:
            if self.plane_family_combo.currentData() == C_PAIR_DATA:
                self.plane_family_combo.setCurrentIndex(0)
            self.plane_family_combo.removeItem(pair_index)
            pair_index = -1

        # Imported full C-gamma photometry defaults to the conventional paired
        # C-plane view rather than a one-sided C=const local sweep.
        if is_ldt and pair_index >= 0:
            self.plane_family_combo.blockSignals(True)
            self.plane_family_combo.setCurrentIndex(pair_index)
            self.plane_family_combo.blockSignals(False)
            patched_populate(self)
            patched_draw_plane(self)

    def patched_populate(self):
        if self.plane_family_combo.currentData() != C_PAIR_DATA or not _is_eulumdat_run(self):
            return original_populate(self)

        self.plane_value_combo.blockSignals(True)
        self.plane_value_combo.clear()
        pairs = _opposite_c_pairs(self.grid_data)
        for base, opposite in pairs:
            self.plane_value_combo.addItem(
                f"C{base:g}° / C{opposite:g}°",
                float(base),
            )
        if pairs:
            zero_index = min(range(len(pairs)), key=lambda i: abs(pairs[i][0]))
            self.plane_value_combo.setCurrentIndex(zero_index)
        self.plane_value_combo.blockSignals(False)

    def _plot_paired_plane(self):
        source_series, base_c, opposite_c = _paired_plane_series(self)
        series = _display_series(self, source_series)
        if series is None:
            self._clear_figure(self.plane_figure, self.plane_canvas, "No paired C-plane data")
            return

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor("#101820")
        peak_index = max(range(len(series.values)), key=series.values.__getitem__) if series.values else None
        pair_title = f"C{base_c:g}° – C{opposite_c:g}°"

        if self.plane_view_combo.currentText() == "Polar":
            axis = self.plane_figure.add_subplot(111, projection="polar")
            axis.set_facecolor("#111B23")
            axis.set_theta_zero_location("N")
            axis.set_theta_direction(-1)
            theta = np.radians(np.asarray(series.angles, dtype=float))
            axis.plot(theta, series.values, marker="o", linewidth=1.8, markersize=3.0)

            # A paired C-plane is a complete vertical photometric plane:
            # +gamma = selected C side, -gamma = opposite C+180 side.
            measured_ticks = [-180, -135, -90, -45, 0, 45, 90, 135, 180]
            axis.set_thetagrids(measured_ticks, labels=[f"{v:+d}°" if v else "0°" for v in measured_ticks])
            axis.set_thetamin(-180.0)
            axis.set_thetamax(180.0)
            axis.set_rmin(0.0)
            vmax = max(series.values) if series.values else 0.0
            if vmax > 0.0:
                axis.set_rmax(105.0 if series.unit == "% of Imax" else vmax * 1.08)
            if peak_index is not None:
                axis.scatter([theta[peak_index]], [series.values[peak_index]], marker="*", s=120, zorder=5)
            axis.grid(True, alpha=0.30)
            axis.tick_params(colors="#B9CAD6")
            axis.spines["polar"].set_color("#40586A")
            axis.set_title(
                f"{pair_title} polar plane • {series.quantity_label}",
                color="#E4EEF5",
                pad=14,
                fontweight="bold",
            )
            self.plane_figure.subplots_adjust(left=0.04, right=0.96, bottom=0.06, top=0.90)
        else:
            axis = self.plane_figure.add_subplot(111)
            self._style_axis(axis)
            axis.plot(series.angles, series.values, marker="o", linewidth=1.8, markersize=3.0)
            axis.set_xticks([-180, -135, -90, -45, 0, 45, 90, 135, 180])
            axis.set_xlim(-180, 180)
            if peak_index is not None:
                axis.scatter([series.angles[peak_index]], [series.values[peak_index]], marker="*", s=120, zorder=5)
                axis.annotate(
                    "Imax",
                    (series.angles[peak_index], series.values[peak_index]),
                    xytext=(7, 7),
                    textcoords="offset points",
                    color="#E4EEF5",
                    fontweight="bold",
                )
            axis.set_xlabel(
                f"Signed Gamma (°)   − = C{opposite_c:g}° side   + = C{base_c:g}° side",
                color="#CFDDE6",
            )
            axis.set_ylabel(f"{series.quantity_label} ({series.unit})", color="#CFDDE6")
            axis.set_title(f"{pair_title} photometric plane", color="#E4EEF5", fontweight="bold")
            axis.axvline(0.0, linewidth=0.8, alpha=0.35)
            self.plane_figure.subplots_adjust(left=0.10, right=0.97, bottom=0.16, top=0.87)

        self.plane_canvas.draw()

    def patched_draw_plane(self):
        if self.plane_family_combo.currentData() == C_PAIR_DATA and _is_eulumdat_run(self):
            return _plot_paired_plane(self)
        return original_draw_plane(self)

    def patched_draw_distribution(self):
        if not _is_eulumdat_run(self) or self.distribution_view_combo.currentText() == "C / Gamma surface":
            return original_draw_distribution(self)

        grid = self.grid_data
        if grid is None:
            return
        radial, label, unit = _display_matrix(self)
        radial = np.asarray(radial, dtype=float)
        radial = np.where(np.isfinite(radial), radial, np.nan)

        # Close the C seam by repeating the first C plane at C+360°.
        c_values = np.asarray(grid.c_values, dtype=float)
        gamma_values = np.asarray(grid.gamma_values, dtype=float)
        c_closed = np.concatenate([c_values, [c_values[0] + 360.0]])
        radial_closed = np.vstack([radial, radial[0:1, :]])
        gamma_mesh, c_mesh = np.meshgrid(gamma_values, c_closed)

        c_rad = np.radians(c_mesh)
        gamma_rad = np.radians(gamma_mesh)
        positive_radial = np.where(radial_closed >= 0.0, radial_closed, 0.0)

        # Standard C-gamma spherical mapping. Gamma=0 lies on the optical axis;
        # C rotates azimuthally around it.
        x = positive_radial * np.sin(gamma_rad) * np.cos(c_rad)
        y = positive_radial * np.sin(gamma_rad) * np.sin(c_rad)
        z = positive_radial * np.cos(gamma_rad)

        self.distribution_figure.clear()
        self.distribution_figure.patch.set_facecolor("#101820")
        axis = self.distribution_figure.add_subplot(111, projection="3d")
        axis.set_facecolor("#111B23")
        axis.plot_surface(x, y, z, linewidth=0, antialiased=True, cmap="viridis")

        finite = np.isfinite(radial)
        if np.any(finite):
            peak_flat = int(np.nanargmax(radial))
            ci, gi = np.unravel_index(peak_flat, radial.shape)
            peak_c = math.radians(float(grid.c_values[ci]))
            peak_gamma = math.radians(float(grid.gamma_values[gi]))
            peak_r = float(radial[ci, gi])
            px = peak_r * math.sin(peak_gamma) * math.cos(peak_c)
            py = peak_r * math.sin(peak_gamma) * math.sin(peak_c)
            pz = peak_r * math.cos(peak_gamma)
            axis.scatter([px], [py], [pz], marker="*", s=120)
            axis.text(px, py, pz, " Imax", color="#E4EEF5")

        axis.set_xlabel("X = I·sinγ·cosC")
        axis.set_ylabel("Y = I·sinγ·sinC")
        axis.set_zlabel(f"Optical axis ({unit})")
        axis.set_title(
            f"3D Photometric Solid • EULUMDAT C-γ • radius = {label}",
            color="#E4EEF5",
            fontweight="bold",
            pad=12,
        )
        axis.tick_params(colors="#B9CAD6")
        axis.xaxis.label.set_color("#CFDDE6")
        axis.yaxis.label.set_color("#CFDDE6")
        axis.zaxis.label.set_color("#CFDDE6")
        try:
            axis.set_box_aspect((1, 1, 1))
        except Exception:
            pass
        axis.view_init(elev=24, azim=-55)
        self.distribution_figure.subplots_adjust(left=0.01, right=0.99, bottom=0.02, top=0.91)
        self.distribution_canvas.draw()

    GridResultsCharts.set_run = patched_set_run
    GridResultsCharts._populate_plane_values = patched_populate
    GridResultsCharts._draw_plane = patched_draw_plane
    GridResultsCharts._draw_distribution = patched_draw_distribution
