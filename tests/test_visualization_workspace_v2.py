import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from measurement_run_io import load_measurement_run_csv
from visualization_workspace_v2 import VisualizationWorkspaceV2
from test_measurement_run_io_v2 import _row, _write


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def workspace(app):
    widget = VisualizationWorkspaceV2(SimpleNamespace())
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def load_grid(tmp_path, rows=None):
    path = tmp_path / "grid.csv"
    if rows is None:
        rows = [_row(i + 1, c, g, 0.001 + i * 0.001)
                for i, (c, g) in enumerate(((-10, -1), (-10, 0), (-10, 1), (0, -1), (0, 0), (0, 1)))]
    _write(path, rows)
    return load_measurement_run_csv(path)


def test_measured_axes_values_and_both_sections(workspace, tmp_path):
    run = load_grid(tmp_path)
    workspace.set_run(run)
    c, g, matrix = workspace._grid
    assert c == [-10, 0] and g == [-1, 0, 1]
    np.testing.assert_allclose(matrix, [[0.025, 0.05, 0.075], [0.1, 0.125, 0.15]])
    assert workspace.isocandela_figure.axes[0].get_xlim() == (-10, 0)
    assert workspace.isocandela_figure.axes[0].get_ylim() == (-1, 1)
    np.testing.assert_allclose(workspace.cplane_figure.axes[0].lines[0].get_ydata(), matrix[1])
    np.testing.assert_allclose(workspace.gplane_figure.axes[0].lines[0].get_ydata(), matrix[:, 1])
    assert "Measured peak 0.15 cd" in workspace.summary_label.text()
    assert "completion unverified" in workspace.summary_label.text()


def test_gaps_are_preserved_in_planes_and_surface(workspace, tmp_path):
    run = load_grid(tmp_path)
    run.points.pop(4)  # C=0, Gamma=0 missing
    workspace.set_run(run)
    assert np.isnan(workspace.cplane_figure.axes[0].lines[0].get_ydata()[1])
    assert len(workspace.surface_figure.axes[0].collections) == 1  # measured scatter only
    assert "Partial grid" in workspace.summary_label.text()


def test_missing_quantity_does_not_drop_an_entire_plane(workspace, tmp_path):
    run = load_grid(tmp_path)
    for p in run.points[:3]:
        p.candela_cd = None
    workspace.set_run(run)
    assert workspace._grid[0] == [-10, 0]
    assert np.isnan(workspace._grid[2][0]).all()


def test_failed_new_run_keeps_previous_export_consistent(workspace, tmp_path):
    run = load_grid(tmp_path)
    workspace.set_run(run)
    old_grid = workspace._grid
    bad = replace(run, sample_id="BAD", points=run.points + [run.points[0]])
    with pytest.raises(ValueError, match="Duplicate"):
        workspace.set_run(bad)
    assert workspace.run is run and workspace._grid is old_grid
    assert workspace.export_button.isEnabled()


@pytest.mark.parametrize("coordinates", [[(0, 0)], [(0, -1), (0, 0)], [(-10, 0), (0, 0)]])
def test_single_point_and_one_axis_scans(workspace, tmp_path, coordinates):
    run = load_grid(tmp_path, [_row(i + 1, c, g, 20) for i, (c, g) in enumerate(coordinates)])
    workspace.set_run(run)
    for i in range(4):
        workspace.tabs.setCurrentIndex(i)
        workspace.save_active_plot(tmp_path / f"single-{i}.svg")


def test_all_exports_include_source_context_and_do_not_leave_stale_labels(workspace, tmp_path):
    run = load_grid(tmp_path)
    workspace.set_run(run)
    for i in range(4):
        workspace.tabs.setCurrentIndex(i)
        before = len(workspace.active_figure().texts)
        output = tmp_path / f"view-{i}.svg"
        workspace.save_active_plot(output)
        text = output.read_text()
        for label in ("Sample: TEST", "Distance: 5 m", "Source: grid.csv", "Start: 2026-10-06", "NOT EVALUATED", "Source SHA-256:", "completion unverified"):
            assert label in text
        assert len(workspace.active_figure().texts) == before
    run.csv_path.write_text(run.csv_path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed since loading"):
        workspace.save_active_plot(tmp_path / "stale.png")


def test_legacy_and_cw_quantities_are_not_mislabeled_as_effective(workspace, tmp_path):
    run = load_grid(tmp_path)
    run.product, run.profile = "Legacy", "General scan"
    workspace.set_run(run)
    assert workspace._quantity_descriptor() == ("Luminous intensity", "cd")
    run.profile, run.product = "CW maximum", "Lumigon V2"
    for p in run.points:
        p.candela_cd = None
    workspace.set_run(run)
    assert workspace._quantity_descriptor() == ("CW maximum", "lx")
    assert workspace.quantity_combo.currentText() == "CW maximum [lx]"
