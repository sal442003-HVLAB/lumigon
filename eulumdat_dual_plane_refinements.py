"""Dual standard C-plane comparison for full EULUMDAT/LDT result grids.

For conventional luminaire photometry, the most useful default polar view is a
comparison of the two principal vertical planes:

* C0 / C180
* C90 / C270

This presentation-only runtime layer is installed after the general grid and
EULUMDAT refinements. It does not modify stored MeasurementRun data and leaves
native limited-angle Lumigon grids unchanged.
"""

from __future__ import annotations

import numpy as np

from results_charts import SingleAxisSeries
from results_grid_charts import GridResultsCharts
from grid_results_visual_refinements import _display_series
from eulumdat_results_refinements import _is_eulumdat_run, _nearest_index


DUAL_STANDARD_DATA = "C_DUAL_STANDARD"
DUAL_STANDARD_TEXT = "Dual standard planes (C0/C180 + C90/C270)"

C0_C180_COLOR = "#FF5A5F"
C90_C270_COLOR = "#4D8DFF"


def _pair_series_for_base(widget, base_c: float):
    grid = getattr(widget, "grid_data", None)
    if grid is None:
        return None

    opposite_c = (float(base_c) + 180.0) % 360.0
    bi = _nearest_index(grid.c_values, float(base_c) % 360.0)
    oi = _nearest_index(grid.c_values, opposite_c)

    actual_base = float(grid.c_values[bi])
    actual_opposite = float(grid.c_values[oi])
    base_values = grid.values[bi, :]
    opposite_values = grid.values[oi, :]

    samples = {}
    # Opposite plane is mapped to negative signed Gamma; selected/base plane to
    # positive signed Gamma, forming one complete vertical photometric plane.
    for gamma, value in zip(grid.gamma_values, opposite_values):
        if np.isfinite(value):
            samples.setdefault(round(-float(gamma), 6), []).append(float(value))
    for gamma, value in zip(grid.gamma_values, base_values):
        if np.isfinite(value):
            samples.setdefault(round(float(gamma), 6), []).append(float(value))

    if not samples:
        return None

    angles = sorted(samples)
    values = [sum(samples[a]) / len(samples[a]) for a in angles]
    return SingleAxisSeries(
        axis_name="Gamma",
        fixed_axis_name="C-pair",
        fixed_angle=actual_base,
        angles=[float(a) for a in angles],
        values=values,
        quantity_label=grid.quantity_label,
        unit=grid.unit,
    ), actual_base, actual_opposite


def install_eulumdat_dual_plane_refinements():
    if getattr(GridResultsCharts, "_lumigon_eulumdat_dual_planes", False):
        return
    GridResultsCharts._lumigon_eulumdat_dual_planes = True

    original_set_run = GridResultsCharts.set_run
    original_populate = GridResultsCharts._populate_plane_values
    original_draw_plane = GridResultsCharts._draw_plane

    def patched_set_run(self, run):
        original_set_run(self, run)

        dual_index = self.plane_family_combo.findData(DUAL_STANDARD_DATA)
        is_ldt = _is_eulumdat_run(self)

        if is_ldt and dual_index < 0:
            # Put the conventional comparison first for imported full C-gamma
            # photometry while preserving all other plane-analysis modes.
            self.plane_family_combo.insertItem(
                0,
                DUAL_STANDARD_TEXT,
                DUAL_STANDARD_DATA,
            )
            dual_index = self.plane_family_combo.findData(DUAL_STANDARD_DATA)
        elif not is_ldt and dual_index >= 0:
            if self.plane_family_combo.currentData() == DUAL_STANDARD_DATA:
                self.plane_family_combo.setCurrentIndex(0)
            self.plane_family_combo.removeItem(dual_index)
            dual_index = -1

        if is_ldt and dual_index >= 0:
            self.plane_family_combo.blockSignals(True)
            self.plane_family_combo.setCurrentIndex(dual_index)
            self.plane_family_combo.blockSignals(False)
            patched_populate(self)
            patched_draw_plane(self)

    def patched_populate(self):
        if self.plane_family_combo.currentData() != DUAL_STANDARD_DATA or not _is_eulumdat_run(self):
            self.plane_value_combo.setEnabled(True)
            return original_populate(self)

        self.plane_value_combo.blockSignals(True)
        self.plane_value_combo.clear()
        self.plane_value_combo.addItem(
            "C0°/C180° + C90°/C270°",
            0.0,
        )
        self.plane_value_combo.setCurrentIndex(0)
        self.plane_value_combo.setEnabled(False)
        self.plane_value_combo.blockSignals(False)

    def _draw_dual_standard(self):
        first = _pair_series_for_base(self, 0.0)
        second = _pair_series_for_base(self, 90.0)
        if first is None or second is None:
            self._clear_figure(
                self.plane_figure,
                self.plane_canvas,
                "C0/C180 and C90/C270 planes are not available",
            )
            return

        series_a = _display_series(self, first[0])
        series_b = _display_series(self, second[0])
        if series_a is None or series_b is None:
            self._clear_figure(self.plane_figure, self.plane_canvas, "No standard plane data")
            return

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor("#101820")
        polar = self.plane_view_combo.currentText() == "Polar"

        if polar:
            axis = self.plane_figure.add_subplot(111, projection="polar")
            axis.set_facecolor("#111B23")
            axis.set_theta_zero_location("N")
            axis.set_theta_direction(-1)

            theta_a = np.radians(np.asarray(series_a.angles, dtype=float))
            theta_b = np.radians(np.asarray(series_b.angles, dtype=float))
            axis.plot(
                theta_a,
                series_a.values,
                linewidth=2.2,
                color=C0_C180_COLOR,
                label="C0 / C180",
            )
            axis.plot(
                theta_b,
                series_b.values,
                linewidth=2.2,
                color=C90_C270_COLOR,
                label="C90 / C270",
            )

            # Mark each principal-plane peak without cluttering every sampled
            # EULUMDAT angle with point symbols.
            if series_a.values:
                ia = max(range(len(series_a.values)), key=series_a.values.__getitem__)
                axis.scatter(
                    [theta_a[ia]],
                    [series_a.values[ia]],
                    marker="*",
                    s=100,
                    color=C0_C180_COLOR,
                    zorder=5,
                )
            if series_b.values:
                ib = max(range(len(series_b.values)), key=series_b.values.__getitem__)
                axis.scatter(
                    [theta_b[ib]],
                    [series_b.values[ib]],
                    marker="*",
                    s=100,
                    color=C90_C270_COLOR,
                    zorder=5,
                )

            ticks = [-180, -135, -90, -45, 0, 45, 90, 135, 180]
            axis.set_thetagrids(
                ticks,
                labels=[f"{value:+d}°" if value else "0°" for value in ticks],
            )
            axis.set_thetamin(-180.0)
            axis.set_thetamax(180.0)
            axis.set_rmin(0.0)

            all_values = list(series_a.values) + list(series_b.values)
            vmax = max(all_values) if all_values else 0.0
            if vmax > 0.0:
                axis.set_rmax(105.0 if series_a.unit == "% of Imax" else vmax * 1.08)

            axis.grid(True, alpha=0.30)
            axis.tick_params(colors="#B9CAD6")
            axis.spines["polar"].set_color("#40586A")
            legend = axis.legend(
                loc="upper right",
                bbox_to_anchor=(1.18, 1.08),
                framealpha=0.18,
            )
            for text in legend.get_texts():
                text.set_color("#D9E5ED")
            axis.set_title(
                f"Standard photometric planes • {series_a.quantity_label}",
                color="#E4EEF5",
                pad=14,
                fontweight="bold",
            )
            self.plane_figure.subplots_adjust(
                left=0.04,
                right=0.92,
                bottom=0.06,
                top=0.90,
            )
        else:
            axis = self.plane_figure.add_subplot(111)
            self._style_axis(axis)
            axis.plot(
                series_a.angles,
                series_a.values,
                linewidth=2.2,
                color=C0_C180_COLOR,
                label="C0 / C180",
            )
            axis.plot(
                series_b.angles,
                series_b.values,
                linewidth=2.2,
                color=C90_C270_COLOR,
                label="C90 / C270",
            )
            axis.set_xticks([-180, -135, -90, -45, 0, 45, 90, 135, 180])
            axis.set_xlim(-180, 180)
            axis.axvline(0.0, linewidth=0.8, alpha=0.35)
            axis.set_xlabel("Signed Gamma (°)", color="#CFDDE6")
            axis.set_ylabel(
                f"{series_a.quantity_label} ({series_a.unit})",
                color="#CFDDE6",
            )
            legend = axis.legend(framealpha=0.18)
            for text in legend.get_texts():
                text.set_color("#D9E5ED")
            axis.set_title(
                "Standard photometric planes • C0/C180 and C90/C270",
                color="#E4EEF5",
                fontweight="bold",
            )
            self.plane_figure.subplots_adjust(
                left=0.10,
                right=0.97,
                bottom=0.16,
                top=0.87,
            )

        self.plane_canvas.draw()

    def patched_draw_plane(self):
        if self.plane_family_combo.currentData() == DUAL_STANDARD_DATA and _is_eulumdat_run(self):
            return _draw_dual_standard(self)
        return original_draw_plane(self)

    GridResultsCharts.set_run = patched_set_run
    GridResultsCharts._populate_plane_values = patched_populate
    GridResultsCharts._draw_plane = patched_draw_plane
