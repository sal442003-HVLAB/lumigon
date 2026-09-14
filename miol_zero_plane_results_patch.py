"""MIOL full-scan refinements: force C=0 plane and swap Results heatmap axes."""

from __future__ import annotations

import numpy as np

import p9710_miol_grid_runtime as miol_grid
from results_grid_charts import GridResultsCharts


_ORIGINAL_AXIS_VALUES = miol_grid._axis_values


def _axis_values_with_zero(start: float, end: float, step: float):
    """Return requested axis values and always include 0° when the span crosses zero.

    This matters for grids such as -45°..+45° with a 10° step, where the natural
    sequence is ..., -5°, +5°, ... and would otherwise skip the C=0° plane.
    The original scan direction is preserved.
    """

    values = list(_ORIGINAL_AXIS_VALUES(start, end, step))
    start = float(start)
    end = float(end)
    if min(start, end) <= 0.0 <= max(start, end):
        if not any(abs(float(value)) <= 1e-9 for value in values):
            values.append(0.0)
            values.sort(reverse=end < start)
    return values


def _build_grid_with_forced_c_zero(c_start, c_end, c_step, gamma_start, gamma_end, gamma_step):
    """Build the serpentine grid while guaranteeing a measured C=0° plane."""

    c_values = _axis_values_with_zero(c_start, c_end, c_step)
    gamma_values = _ORIGINAL_AXIS_VALUES(gamma_start, gamma_end, gamma_step)

    points = []
    for plane_index, c_deg in enumerate(c_values):
        sweep = gamma_values if plane_index % 2 == 0 else reversed(gamma_values)
        points.extend((c_deg, gamma_deg) for gamma_deg in sweep)
    return points


def _draw_heatmap_swapped(self: GridResultsCharts):
    """Draw Results heatmap with C on X and Gamma on Y."""

    grid = self.grid_data
    if grid is None:
        return

    self.heatmap_figure.clear()
    self.heatmap_figure.patch.set_facecolor("#101820")
    axis = self.heatmap_figure.add_subplot(111)
    self._style_axis(axis)

    # Grid storage is [C, Gamma]. For X=C / Y=Gamma the plotted matrix must be
    # transposed to [Gamma, C].
    z = np.ma.masked_invalid(grid.values.T)
    mesh = axis.pcolormesh(
        np.asarray(grid.c_values),
        np.asarray(grid.gamma_values),
        z,
        shading="auto",
    )
    colorbar = self.heatmap_figure.colorbar(mesh, ax=axis, pad=0.02)
    colorbar.set_label(f"{grid.quantity_label} ({grid.unit})", color="#CFDDE6")
    colorbar.ax.tick_params(colors="#B9CAD6")

    axis.set_xlabel("C angle (°)", color="#CFDDE6")
    axis.set_ylabel("Gamma angle (°)", color="#CFDDE6")
    axis.set_title(
        f"C × Gamma Heatmap • {grid.quantity_label}",
        color="#E4EEF5",
        fontweight="bold",
    )
    axis.axvline(0.0, linewidth=0.8, alpha=0.30)
    axis.axhline(0.0, linewidth=0.8, alpha=0.30)
    self.heatmap_figure.subplots_adjust(left=0.09, right=0.92, bottom=0.13, top=0.88)
    self.heatmap_canvas.draw()


def install_miol_zero_plane_results_patch():
    """Install both refinements before Measurement/Results workspaces are used."""

    miol_grid._build_grid = _build_grid_with_forced_c_zero
    GridResultsCharts._draw_heatmap = _draw_heatmap_swapped
