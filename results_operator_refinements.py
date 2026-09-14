"""Operator refinements for Lumigon Results.

- Keep a CSV replace/reload action visible after a run is loaded.
- Make the Results heatmap use the same orientation as the live MIOL map:
  C on X, Gamma on Y.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QPushButton

from results_grid_charts import GridResultsCharts


_INSTALLED = False


def _draw_heatmap_c_x_gamma(self: GridResultsCharts):
    grid = self.grid_data
    if grid is None:
        return

    self.heatmap_figure.clear()
    self.heatmap_figure.patch.set_facecolor("#101820")
    axis = self.heatmap_figure.add_subplot(111)
    self._style_axis(axis)

    # GridData.values is stored as [C_index, Gamma_index].  To plot C on the
    # horizontal axis and Gamma on the vertical axis, transpose the matrix.
    z = np.ma.masked_invalid(np.asarray(grid.values, dtype=float).T)
    mesh = axis.pcolormesh(
        np.asarray(grid.c_values, dtype=float),
        np.asarray(grid.gamma_values, dtype=float),
        z,
        shading="auto",
    )
    colorbar = self.heatmap_figure.colorbar(mesh, ax=axis, pad=0.02)
    colorbar.set_label(
        f"{grid.quantity_label} ({grid.unit})",
        color="#CFDDE6",
    )
    colorbar.ax.tick_params(colors="#B9CAD6")

    axis.set_xlabel("C angle (°)", color="#CFDDE6")
    axis.set_ylabel("Gamma angle (°)", color="#CFDDE6")
    axis.set_title(
        f"C × Gamma Heatmap • {grid.quantity_label}",
        color="#E4EEF5",
        fontweight="bold",
    )
    self.heatmap_figure.subplots_adjust(
        left=0.09,
        right=0.92,
        bottom=0.13,
        top=0.88,
    )
    self.heatmap_canvas.draw()


def install_results_heatmap_orientation():
    """Install Results heatmap orientation matching the live MIOL intensity map."""
    global _INSTALLED
    if _INSTALLED:
        return
    GridResultsCharts._draw_heatmap = _draw_heatmap_c_x_gamma
    _INSTALLED = True


def attach_results_reload_control(window):
    """Add an always-visible Load / Replace CSV action in the Analysis row."""
    workspace = getattr(window, "results_workspace_controller", None)
    if workspace is None:
        raise RuntimeError("Results workspace is not available.")

    existing = getattr(workspace, "load_replace_csv_button", None)
    if existing is not None:
        return existing

    # Rename the header action as well, so its replace semantics are explicit.
    header_button = getattr(workspace, "load_csv_button", None)
    if header_button is not None:
        header_button.setText("Load / Replace CSV")
        header_button.setToolTip(
            "Open another Lumigon CSV and replace the currently displayed Results run."
        )

    button = QPushButton("Load / Replace CSV")
    button.setObjectName("secondaryActionButton")
    button.setToolTip(
        "Open another Lumigon CSV and replace the currently displayed Results run."
    )
    button.clicked.connect(workspace.load_csv)

    layout = workspace.analysis_box.layout()
    if layout is not None:
        # Keep this action beside Export Plot so it remains visible after data
        # are loaded and the Results charts occupy the page.
        layout.addWidget(button)

    workspace.load_replace_csv_button = button
    return button
