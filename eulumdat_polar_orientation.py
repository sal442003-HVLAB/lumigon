"""Match imported EULUMDAT polar orientation to conventional LDT editors.

This is presentation-only.  Stored C/gamma coordinates and photometric values
are not changed.  Native Lumigon limited-angle grids keep their existing local
scan convention.
"""

from __future__ import annotations

from results_grid_charts import GridResultsCharts
from eulumdat_results_refinements import _is_eulumdat_run


def install_eulumdat_polar_orientation():
    """Rotate EULUMDAT Plane polar plots by 180 degrees for display only.

    Conventional EULUMDAT/LDT polar diagrams place gamma=0 degrees on the
    downward optical axis.  Matplotlib's default Lumigon polar presentation uses
    zero at North.  Setting zero to South changes only the rendering convention;
    the underlying C/gamma data remain untouched.
    """

    if getattr(GridResultsCharts, "_lumigon_eulumdat_polar_orientation", False):
        return
    GridResultsCharts._lumigon_eulumdat_polar_orientation = True

    original_draw_plane = GridResultsCharts._draw_plane

    def patched_draw_plane(self):
        result = original_draw_plane(self)

        if not _is_eulumdat_run(self):
            return result
        if self.plane_view_combo.currentText() != "Polar":
            return result
        if not self.plane_figure.axes:
            return result

        axis = self.plane_figure.axes[0]
        # PolarAxes exposes set_theta_zero_location; ordinary Cartesian axes do
        # not. Keep the existing clockwise angle direction and move only the
        # zero reference from North to South (a 180-degree display rotation).
        if hasattr(axis, "set_theta_zero_location"):
            axis.set_theta_zero_location("S")
            axis.set_theta_direction(-1)
            self.plane_canvas.draw()

        return result

    GridResultsCharts._draw_plane = patched_draw_plane
