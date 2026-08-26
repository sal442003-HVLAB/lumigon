"""Runtime integration of C × Gamma visualizations into the Results workspace.

The existing ResultsWorkspace and ResultsCharts remain the single-axis path.
This layer adds a separate GridResultsCharts widget and switches between the
proven single-axis and grid views according to the loaded MeasurementRun.
"""

from __future__ import annotations

import math

from PySide6.QtWidgets import QFileDialog, QMessageBox, QSizePolicy

from grid_results_visual_refinements import install_grid_results_visual_refinements
from eulumdat_results_refinements import install_eulumdat_results_refinements
from eulumdat_dual_plane_refinements import install_eulumdat_dual_plane_refinements
from eulumdat_polar_orientation import install_eulumdat_polar_orientation
from eulumdat_folded_standard_plane_refinements import (
    install_eulumdat_folded_standard_plane_refinements,
)
from native_polar_template_refinements import install_native_polar_template_refinements
from measurement_run import measurement_data_directory
from results_charts import CALCULATED_LUX
from results_grid_charts import GridResultsCharts, extract_grid_data


def _mean_candela(run):
    values = []
    for point in run.points:
        value = getattr(point, "candela_cd", None)
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return None
    return sum(values) / len(values)


def attach_grid_results_runtime(window):
    """Attach Heatmap / Plane / 3D views to the existing Results workspace."""

    install_grid_results_visual_refinements()
    install_eulumdat_results_refinements()
    install_eulumdat_dual_plane_refinements()
    install_eulumdat_polar_orientation()
    install_eulumdat_folded_standard_plane_refinements()
    # Install native Lumigon presentation last. Its Grid wrapper delegates all
    # imported EULUMDAT runs back through the compatibility chain above, while
    # native single-axis and selected-grid planes use the shared Lumigon template.
    install_native_polar_template_refinements()

    workspace = getattr(window, "results_workspace_controller", None)
    if workspace is None:
        raise RuntimeError("Results workspace is not available for grid integration.")
    if getattr(workspace, "grid_charts", None) is not None:
        return workspace.grid_charts

    grid_charts = GridResultsCharts(workspace)
    grid_charts.setMinimumWidth(0)
    grid_charts.setMinimumHeight(520)
    grid_charts.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    grid_charts.set_calculation_distance(workspace.calculated_distance_spin.value())
    grid_charts.hide()
    workspace.layout().addWidget(grid_charts, 1)

    workspace.grid_charts = grid_charts
    workspace._grid_mode = False

    original_set_run = workspace.set_run

    def set_run_with_grid(run):
        original_set_run(run)

        distance_m = workspace.calculated_distance_spin.value()
        grid = extract_grid_data(run, "Candela", distance_m)
        workspace._grid_mode = grid is not None

        if workspace._grid_mode:
            workspace.charts.hide()
            grid_charts.show()
            grid_charts.set_calculation_distance(distance_m)
            grid_charts.set_run(run)
            grid_charts.set_quantity(workspace.quantity_combo.currentText())

            mean_candela = _mean_candela(run)
            workspace.mean_candela_label.setText(
                "—" if mean_candela is None else f"{mean_candela:.1f} cd"
            )
            workspace.fwhm_label.setText("Plane-dependent")
            workspace.fwhm_label.setToolTip(
                "For a C × Gamma grid, FWHM is calculated on the selected C or Gamma plane rather than across the full matrix."
            )
            _update_grid_note()
        else:
            grid_charts.hide()
            workspace.charts.show()

    workspace.set_run = set_run_with_grid

    def _update_grid_note(*_args):
        if not getattr(workspace, "_grid_mode", False):
            return
        run = workspace.latest_run
        if run is None:
            return

        quantity = workspace.quantity_combo.currentText()
        distance_m = workspace.calculated_distance_spin.value()
        grid = extract_grid_data(run, quantity, distance_m)
        if grid is None:
            return

        text = (
            f"C × Gamma grid • {len(grid.c_values)} C positions × "
            f"{len(grid.gamma_values)} Gamma positions • "
            f"{grid.measured_cells}/{grid.total_cells} measured cells • "
            "Heatmap / selectable Plane / 3D Distribution available."
        )
        if quantity == CALCULATED_LUX:
            text += f" Calculated Lux uses E = I / r² at {distance_m:g} m."
        workspace.analysis_note.setText(text)
        workspace.analysis_note.setToolTip(text)

    def on_quantity_changed(text):
        if not getattr(workspace, "_grid_mode", False):
            return
        grid_charts.set_quantity(text)
        _update_grid_note()

    def on_distance_changed(distance_m):
        grid_charts.set_calculation_distance(distance_m)
        if getattr(workspace, "_grid_mode", False):
            _update_grid_note()

    workspace.quantity_combo.currentTextChanged.connect(on_quantity_changed)
    workspace.calculated_distance_spin.valueChanged.connect(on_distance_changed)

    # The original Export Plot button is connected to the single-axis figure.
    # Route it to the currently visible analysis widget instead.
    try:
        workspace.export_plot_button.clicked.disconnect()
    except RuntimeError:
        pass

    def export_active_plot():
        run = workspace.latest_run
        if run is None:
            return

        directory = measurement_data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        quantity_name = workspace.quantity_combo.currentText().replace(" ", "_")
        if workspace.quantity_combo.currentText() == CALCULATED_LUX:
            quantity_name += f"_{workspace.calculated_distance_spin.value():g}m"

        if getattr(workspace, "_grid_mode", False):
            view_name = grid_charts.active_view_name()
            figure = grid_charts.active_figure()
        else:
            view_name = "plot"
            figure = workspace.charts.active_figure()

        default_name = f"{run.sample_id}_{quantity_name}_{view_name}.png"
        filename, _ = QFileDialog.getSaveFileName(
            workspace,
            "Export Result Plot",
            str(directory / default_name),
            "PNG image (*.png);;PDF (*.pdf);;SVG (*.svg)",
        )
        if not filename:
            return

        try:
            figure.savefig(filename, dpi=180, bbox_inches="tight")
        except Exception as exc:
            QMessageBox.critical(
                workspace,
                "Export Plot",
                f"Could not export the plot:\n\n{exc}",
            )

    workspace.export_plot_button.clicked.connect(export_active_plot)
    workspace.export_plot = export_active_plot

    return grid_charts