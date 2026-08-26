"""Install the shared Lumigon photometric Polar template on native results.

EULUMDAT/LDT imports retain their separate compatibility presentation. Native
single-axis measurements and selected planes from native C×Gamma grids share
one fixed photometric template, regardless of the measured angular span.
"""

from __future__ import annotations

from eulumdat_results_refinements import _is_eulumdat_run
from grid_results_visual_refinements import _display_series
from lumigon_polar_template import (
    AXIS_BACKGROUND,
    BACKGROUND,
    configure_photometric_polar,
    draw_photometric_curve,
    finish_photometric_figure,
)
from results_charts import ResultsCharts
from results_grid_charts import GridResultsCharts


def install_native_polar_template_refinements():
    if getattr(ResultsCharts, "_lumigon_shared_polar_template", False):
        return
    ResultsCharts._lumigon_shared_polar_template = True
    GridResultsCharts._lumigon_shared_polar_template = True

    original_grid_draw_plane = GridResultsCharts._draw_plane

    def draw_single_axis_polar(self, series):
        self.polar_figure.clear()
        self.polar_figure.patch.set_facecolor(BACKGROUND)
        axis = self.polar_figure.add_subplot(111, projection="polar")
        axis.set_facecolor(AXIS_BACKGROUND)
        configure_photometric_polar(axis, series.values)
        draw_photometric_curve(axis, series.angles, series.values)
        finish_photometric_figure(
            self.polar_figure,
            unit=series.unit,
            title=f"Polar {series.quantity_label} • {series.axis_name} plane",
        )
        self.polar_canvas.draw()

    def draw_native_grid_plane(self):
        # Imported full photometry has its own EULUMDAT compatibility views.
        if _is_eulumdat_run(self):
            return original_grid_draw_plane(self)
        if self.plane_view_combo.currentText() != "Polar":
            return original_grid_draw_plane(self)

        source_series = self._selected_plane()
        series = _display_series(self, source_series)
        if series is None:
            self._clear_figure(self.plane_figure, self.plane_canvas, "No plane data")
            return

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor(BACKGROUND)
        axis = self.plane_figure.add_subplot(111, projection="polar")
        axis.set_facecolor(AXIS_BACKGROUND)
        configure_photometric_polar(
            axis,
            series.values,
            relative=series.unit == "% of Imax",
        )
        draw_photometric_curve(axis, series.angles, series.values)
        finish_photometric_figure(
            self.plane_figure,
            unit=series.unit,
            title=(
                f"{series.fixed_axis_name} {series.fixed_angle:+.3f}° • "
                f"{series.axis_name} polar plane"
            ),
        )
        self.plane_canvas.draw()

    ResultsCharts._draw_polar = draw_single_axis_polar
    GridResultsCharts._draw_plane = draw_native_grid_plane
