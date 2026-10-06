"""Customer-facing Version 2 photometric visualization workspace.

This module intentionally separates visualization from standards compliance.
Measured data are displayed exactly as stored. Contour lines and 3D surfaces
are visual interpolations between measured grid nodes and are never used here
to issue a PASS/FAIL decision.
"""

from __future__ import annotations

import math
import hashlib
import re
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from mpl_toolkits.axes_grid1 import make_axes_locatable
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from measurement_run import MeasurementRun, measurement_data_directory
from measurement_run_io import load_measurement_run_csv


ICAO_REFERENCE = "ICAO Annex 14, Volume I — 9th Edition, Amendment 18"
ICAO_REFERENCE_DATE = "27 Nov 2025"


def _finite(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _unique_sorted(values):
    # Do not merge or move measured coordinates using a display tolerance.
    return sorted(set(float(v) for v in values))


def _step_text(values):
    if len(values) < 2:
        return "single"
    diffs = np.diff(np.asarray(values, dtype=float))
    if not np.all(np.isfinite(diffs)):
        return "irregular"
    reference = float(np.median(diffs))
    if np.allclose(diffs, reference, rtol=0.0, atol=max(1e-6, abs(reference) * 1e-6)):
        return f"{reference:g}°"
    return "irregular"


class VisualizationWorkspaceV2(QWidget):
    """High-integrity visualization of a Lumigon C × Gamma measurement grid."""

    def __init__(self, host_window):
        super().__init__()
        self.host_window = host_window
        self.run: MeasurementRun | None = None
        self._source_path: Path | None = None
        self._quantity = "candela"
        self._grid = None
        self._source_sha256 = None

        self.setObjectName("visualizationWorkspaceV2")
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        # Header -------------------------------------------------------
        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title_block.setSpacing(1)

        title = QLabel("Visualization")
        title.setObjectName("visualizationTitle")
        subtitle = QLabel(
            "Measured photometric distribution • C × Gamma grid • customer-facing visualization"
        )
        subtitle.setObjectName("visualizationSubtitle")
        subtitle.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.load_button = QPushButton("Load Measurement CSV")
        self.load_button.clicked.connect(self.load_csv)
        header.addWidget(self.load_button)

        self.latest_button = QPushButton("Use Latest Measurement")
        self.latest_button.clicked.connect(self.use_latest_measurement)
        header.addWidget(self.latest_button)

        self.export_button = QPushButton("Export Active Plot")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_active_plot)
        header.addWidget(self.export_button)
        root.addLayout(header)

        # Integrity / standard status ---------------------------------
        status_row = QHBoxLayout()
        status_row.setSpacing(8)

        self.integrity_box = QGroupBox("Data integrity")
        integrity_layout = QGridLayout(self.integrity_box)
        integrity_layout.setContentsMargins(12, 10, 12, 10)
        integrity_layout.setHorizontalSpacing(12)
        integrity_layout.setVerticalSpacing(5)

        self.source_label = QLabel("No measurement loaded")
        self.source_label.setWordWrap(True)
        self.integrity_label = QLabel("—")
        self.integrity_label.setObjectName("visualizationIntegrityPending")
        self.grid_label = QLabel("—")
        self.quantity_label = QLabel("—")

        integrity_layout.addWidget(QLabel("Source:"), 0, 0)
        integrity_layout.addWidget(self.source_label, 0, 1)
        integrity_layout.addWidget(QLabel("Integrity:"), 1, 0)
        integrity_layout.addWidget(self.integrity_label, 1, 1)
        integrity_layout.addWidget(QLabel("Grid:"), 2, 0)
        integrity_layout.addWidget(self.grid_label, 2, 1)
        integrity_layout.addWidget(QLabel("Quantity:"), 3, 0)
        integrity_layout.addWidget(self.quantity_label, 3, 1)
        integrity_layout.setColumnStretch(1, 1)
        status_row.addWidget(self.integrity_box, 3)

        self.standard_box = QGroupBox("ICAO compliance reference")
        standard_layout = QGridLayout(self.standard_box)
        standard_layout.setContentsMargins(12, 10, 12, 10)
        standard_layout.setHorizontalSpacing(12)
        standard_layout.setVerticalSpacing(5)

        self.standard_reference_label = QLabel(
            f"{ICAO_REFERENCE} ({ICAO_REFERENCE_DATE})"
        )
        self.standard_reference_label.setWordWrap(True)

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("None — visualization only", None)
        self.profile_combo.setEnabled(False)

        self.compliance_label = QLabel("NOT EVALUATED")
        self.compliance_label.setObjectName("visualizationComplianceNotEvaluated")
        self.compliance_note = QLabel(
            "No PASS/FAIL is generated until the exact Annex 14 figure/profile, "
            "colour, mounting geometry and C/Gamma ↔ ICAO X/Y mapping are explicitly locked."
        )
        self.compliance_note.setWordWrap(True)

        standard_layout.addWidget(QLabel("Reference:"), 0, 0)
        standard_layout.addWidget(self.standard_reference_label, 0, 1)
        standard_layout.addWidget(QLabel("Profile:"), 1, 0)
        standard_layout.addWidget(self.profile_combo, 1, 1)
        standard_layout.addWidget(QLabel("Compliance:"), 2, 0)
        standard_layout.addWidget(self.compliance_label, 2, 1)
        standard_layout.addWidget(self.compliance_note, 3, 0, 1, 2)
        standard_layout.setColumnStretch(1, 1)
        status_row.addWidget(self.standard_box, 2)

        root.addLayout(status_row)

        # Analysis controls -------------------------------------------
        controls = QHBoxLayout()
        controls.setSpacing(8)

        controls.addWidget(QLabel("Display quantity:"))
        self.quantity_combo = QComboBox()
        self.quantity_combo.addItem("Intensity [cd]", "candela")
        self.quantity_combo.addItem("Illuminance [lx]", "lux")
        self.quantity_combo.currentIndexChanged.connect(self._quantity_changed)
        controls.addWidget(self.quantity_combo)

        self.equal_scale_check = QCheckBox("Equal angular scale")
        self.equal_scale_check.setChecked(True)
        self.equal_scale_check.toggled.connect(self._redraw_active)
        controls.addWidget(self.equal_scale_check)

        self.summary_label = QLabel("Load a completed measurement to begin.")
        self.summary_label.setObjectName("visualizationSummary")
        self.summary_label.setWordWrap(True)
        controls.addWidget(self.summary_label, 1)

        root.addLayout(controls)

        # Visual tabs --------------------------------------------------
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._redraw_active)
        root.addWidget(self.tabs, 1)

        # Isocandela
        self.isocandela_page = QWidget()
        iso_layout = QVBoxLayout(self.isocandela_page)
        iso_layout.setContentsMargins(0, 0, 0, 0)
        self.isocandela_figure = Figure(figsize=(8.4, 5.4))
        self.isocandela_canvas = FigureCanvasQTAgg(self.isocandela_figure)
        self._configure_canvas(self.isocandela_canvas)
        iso_layout.addWidget(self.isocandela_canvas, 1)
        self.tabs.addTab(self.isocandela_page, "Isocandela Map")

        # 3D
        self.surface_page = QWidget()
        surface_layout = QVBoxLayout(self.surface_page)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        self.surface_figure = Figure(figsize=(8.4, 5.4))
        self.surface_canvas = FigureCanvasQTAgg(self.surface_figure)
        self._configure_canvas(self.surface_canvas)
        surface_layout.addWidget(self.surface_canvas, 1)
        self.tabs.addTab(self.surface_page, "3D Surface")

        # C-plane
        self.cplane_page = QWidget()
        cplane_root = QVBoxLayout(self.cplane_page)
        cplane_root.setContentsMargins(0, 0, 0, 0)
        cplane_controls = QHBoxLayout()
        cplane_controls.addWidget(QLabel("C plane:"))
        self.cplane_combo = QComboBox()
        self.cplane_combo.currentIndexChanged.connect(self._draw_cplane)
        cplane_controls.addWidget(self.cplane_combo)
        cplane_controls.addStretch(1)
        cplane_root.addLayout(cplane_controls)

        self.cplane_figure = Figure(figsize=(8.4, 5.0))
        self.cplane_canvas = FigureCanvasQTAgg(self.cplane_figure)
        self._configure_canvas(self.cplane_canvas)
        cplane_root.addWidget(self.cplane_canvas, 1)
        self.tabs.addTab(self.cplane_page, "C-plane")

        self.gplane_page = QWidget()
        gplane_root = QVBoxLayout(self.gplane_page)
        gplane_root.setContentsMargins(0, 0, 0, 0)
        gplane_controls = QHBoxLayout()
        gplane_controls.addWidget(QLabel("Fixed Gamma:"))
        self.gplane_combo = QComboBox()
        self.gplane_combo.currentIndexChanged.connect(self._draw_gplane)
        gplane_controls.addWidget(self.gplane_combo)
        gplane_controls.addStretch(1)
        gplane_root.addLayout(gplane_controls)
        self.gplane_figure = Figure(figsize=(8.4, 5.0))
        self.gplane_canvas = FigureCanvasQTAgg(self.gplane_figure)
        self._configure_canvas(self.gplane_canvas)
        gplane_root.addWidget(self.gplane_canvas, 1)
        self.tabs.addTab(self.gplane_page, "Fixed Gamma")

        self._clear_all("No measurement loaded")

        self.setStyleSheet(
            """
            QWidget#visualizationWorkspaceV2 {
                background-color: #101820;
            }
            QLabel#visualizationTitle {
                color: #E9F3FA;
                font-size: 20pt;
                font-weight: 700;
            }
            QLabel#visualizationSubtitle {
                color: #8299A9;
            }
            QLabel#visualizationSummary {
                color: #9FC4D8;
                background-color: #14212B;
                border: 1px solid #2B4050;
                border-radius: 5px;
                padding: 7px 10px;
            }
            QLabel#visualizationIntegrityValid {
                color: #55EFC4;
                font-weight: 700;
            }
            QLabel#visualizationIntegrityPending {
                color: #E7C76A;
                font-weight: 700;
            }
            QLabel#visualizationComplianceNotEvaluated {
                color: #E7C76A;
                font-weight: 800;
            }
            """
        )

    @staticmethod
    def _configure_canvas(canvas):
        canvas.setMinimumSize(0, 0)
        canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        canvas.setStyleSheet("background-color:#101820;")

    @staticmethod
    def _style_axis(axis):
        axis.set_facecolor("#111B23")
        axis.tick_params(colors="#B9CAD6")
        axis.grid(True, alpha=0.25)
        for spine in axis.spines.values():
            spine.set_color("#40586A")

    def _quantity_value(self, point):
        if self._quantity == "candela":
            return _finite(point.candela_cd)
        return _finite(point.lux)

    def _quantity_descriptor(self):
        effective = self.run is not None and (
            self.run.product == "Lumigon V2" and self.run.profile == "E-effective → I-effective"
        )
        if self._quantity == "candela":
            return ("I-effective" if effective else "Luminous intensity"), "cd"
        if self.run is not None and "CW maximum" in (self.run.profile or ""):
            return "CW maximum", "lx"
        return ("E-effective" if effective else "Illuminance"), "lx"

    def _build_grid(self, run=None, quantity=None):
        run = run or self.run
        quantity = quantity or self._quantity
        if run is None:
            return None

        usable = []
        coordinates = set()
        for point in run.points:
            c_deg, gamma_deg = _finite(point.c_deg), _finite(point.gamma_deg)
            if c_deg is None or gamma_deg is None:
                raise ValueError("C/Gamma coordinates must be finite numbers.")
            coordinate = (c_deg, gamma_deg)
            if coordinate in coordinates:
                raise ValueError(f"Duplicate visualization coordinate at C={c_deg:g}°, Gamma={gamma_deg:g}°.")
            coordinates.add(coordinate)
            value = _finite(point.candela_cd if quantity == "candela" else point.lux)
            # Keep axes even when an entire measured plane lacks this quantity.
            usable.append((c_deg, gamma_deg, np.nan if value is None else value))

        if not usable:
            return None

        c_values = _unique_sorted(item[0] for item in usable)
        gamma_values = _unique_sorted(item[1] for item in usable)
        c_index = {value: idx for idx, value in enumerate(c_values)}
        g_index = {value: idx for idx, value in enumerate(gamma_values)}
        matrix = np.full((len(c_values), len(gamma_values)), np.nan, dtype=float)

        for c_deg, gamma_deg, value in usable:
            ci = c_index[c_deg]
            gi = g_index[gamma_deg]
            if np.isfinite(matrix[ci, gi]):
                raise ValueError(
                    f"Duplicate visualization coordinate at C={c_deg:g}°, "
                    f"Gamma={gamma_deg:g}°."
                )
            matrix[ci, gi] = value

        return c_values, gamma_values, matrix

    def load_path(self, path, *, show_errors=True):
        try:
            run = load_measurement_run_csv(path)
            self.set_run(run, source_path=Path(path))
            return True
        except Exception as exc:
            if show_errors:
                QMessageBox.critical(
                    self,
                    "Load Visualization Data",
                    f"The measurement file failed integrity/format validation:\n\n{exc}",
                )
            return False

    def load_csv(self):
        directory = measurement_data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Lumigon Measurement CSV",
            str(directory),
            "Lumigon CSV (*.csv);;CSV files (*.csv);;All files (*.*)",
        )
        if filename:
            self.load_path(filename, show_errors=True)

    def use_latest_measurement(self):
        payload = getattr(self.host_window, "measurement_v2_last_run", None)
        if not payload:
            QMessageBox.information(
                self,
                "Visualization",
                "No completed Version 2 measurement is available in this session yet.",
            )
            return

        path = payload.get("csv_path")
        if not path:
            QMessageBox.warning(
                self,
                "Visualization",
                "The latest measurement has no saved CSV path.",
            )
            return
        self.load_path(path, show_errors=True)

    def set_run(self, run: MeasurementRun, *, source_path=None):
        has_candela = any(_finite(point.candela_cd) is not None for point in run.points)
        quantity = "candela" if has_candela else "lux"
        # Validate before replacing the current plot/export state.
        grid = self._build_grid(run, quantity)
        if grid is None or not np.any(np.isfinite(grid[2])):
            raise ValueError("No finite photometric measurement values are available.")
        source = Path(source_path) if source_path else run.csv_path
        digest = hashlib.sha256(source.read_bytes()).hexdigest() if source and source.is_file() else None
        self.run = run
        self._source_path = source
        self._source_sha256 = digest

        # Prefer candela when available, otherwise illuminance.
        target_index = self.quantity_combo.findData("candela" if has_candela else "lux")
        if target_index >= 0:
            self.quantity_combo.blockSignals(True)
            self.quantity_combo.setCurrentIndex(target_index)
            self.quantity_combo.blockSignals(False)
        self._quantity = self.quantity_combo.currentData() or "candela"

        self._grid = grid

        for i, key in enumerate(("candela", "lux")):
            previous_quantity = self._quantity
            self._quantity = key
            label, unit = self._quantity_descriptor()
            self.quantity_combo.setItemText(i, f"{label} [{unit}]")
            self._quantity = previous_quantity

        self._populate_cplanes()
        self._update_metadata()
        self._draw_all()
        self.export_button.setEnabled(self._grid is not None)

    def _update_metadata(self):
        run = self.run
        grid = self._grid
        if run is None or grid is None:
            return

        c_values, gamma_values, matrix = grid
        measured = int(np.count_nonzero(np.isfinite(matrix)))
        total = int(matrix.size)
        complete = measured == total

        source = (
            self._source_path.name
            if self._source_path is not None
            else "Current measurement session"
        )
        self.source_label.setText(source)
        self.source_label.setToolTip(
            str(self._source_path) if self._source_path is not None else source
        )

        self.integrity_label.setObjectName("visualizationIntegrityValid")
        strict_v2 = "validated Lumigon V2 CSV" in (run.home_status or "")
        self.integrity_label.setText(
            "V2 FORMAT / ARITHMETIC CHECK PASSED ✓"
            if strict_v2
            else ("LOADED ✓" if self._source_path is not None else "SESSION DATA")
        )
        self.integrity_label.style().unpolish(self.integrity_label)
        self.integrity_label.style().polish(self.integrity_label)

        self.grid_label.setText(
            f"{len(c_values)} C × {len(gamma_values)} Gamma • "
            f"{measured}/{total} measured • "
            f"ΔC {_step_text(c_values)} • ΔGamma {_step_text(gamma_values)}"
        )

        quantity, unit = self._quantity_descriptor()
        self.quantity_label.setText(f"{quantity} [{unit}]")

        values = matrix[np.isfinite(matrix)]
        if values.size:
            max_index = np.nanargmax(matrix)
            ci, gi = np.unravel_index(max_index, matrix.shape)
            peak = float(matrix[ci, gi])
            peak_text = (
                f"Measured peak {peak:.6g} {unit} at C {c_values[ci]:+.2f}°, "
                f"Gamma {gamma_values[gi]:+.2f}°"
            )
        else:
            peak_text = "No finite photometric values"

        interpolation_text = (
            "All observed grid intersections have values (scan completion unverified)"
            if complete
            else "Partial grid — missing cells are never invented"
        )
        self.summary_label.setText(
            f"{run.sample_id} • {peak_text} • {interpolation_text}"
        )

    def _quantity_changed(self, *_args):
        self._quantity = self.quantity_combo.currentData() or "candela"
        if self.run is None:
            return
        try:
            self._grid = self._build_grid()
        except Exception as exc:
            QMessageBox.critical(self, "Visualization Data Error", str(exc))
            return
        self._update_metadata()
        self._populate_cplanes()
        self._draw_all()
        self.export_button.setEnabled(self._grid is not None and np.any(np.isfinite(self._grid[2])))

    def _populate_cplanes(self):
        self.cplane_combo.blockSignals(True)
        self.cplane_combo.clear()
        if self._grid is not None:
            c_values = self._grid[0]
            if c_values:
                zero_index = min(range(len(c_values)), key=lambda i: abs(c_values[i]))
                for value in c_values:
                    self.cplane_combo.addItem(f"C {value:+.3f}°", float(value))
                self.cplane_combo.setCurrentIndex(zero_index)
        self.cplane_combo.blockSignals(False)
        self.gplane_combo.blockSignals(True)
        self.gplane_combo.clear()
        if self._grid is not None:
            gamma_values = self._grid[1]
            for value in gamma_values:
                self.gplane_combo.addItem(f"Gamma {value:+.3f}°", float(value))
            if gamma_values:
                self.gplane_combo.setCurrentIndex(min(range(len(gamma_values)), key=lambda i: abs(gamma_values[i])))
        self.gplane_combo.blockSignals(False)

    def _clear_figure(self, figure, canvas, message):
        figure.clear()
        figure.patch.set_facecolor("#101820")
        axis = figure.add_subplot(111)
        axis.set_facecolor("#111B23")
        axis.text(
            0.5, 0.5, message,
            ha="center", va="center",
            color="#8EA6B6",
            transform=axis.transAxes,
        )
        axis.set_axis_off()
        canvas.draw_idle()

    def _clear_all(self, message):
        self._clear_figure(self.isocandela_figure, self.isocandela_canvas, message)
        self._clear_figure(self.surface_figure, self.surface_canvas, message)
        self._clear_figure(self.cplane_figure, self.cplane_canvas, message)
        self._clear_figure(self.gplane_figure, self.gplane_canvas, message)

    def _draw_all(self):
        if self._grid is None:
            self._clear_all("No plottable C × Gamma data")
            return
        self._draw_isocandela()
        self._draw_surface()
        self._draw_cplane()
        self._draw_gplane()

    def _draw_isocandela(self):
        c_values, gamma_values, matrix = self._grid
        quantity, unit = self._quantity_descriptor()

        self.isocandela_figure.clear()
        self.isocandela_figure.patch.set_facecolor("#101820")
        axis = self.isocandela_figure.add_subplot(111)
        self._style_axis(axis)

        z = np.ma.masked_invalid(matrix.T)
        mesh = axis.pcolormesh(
            np.asarray(c_values, dtype=float),
            np.asarray(gamma_values, dtype=float),
            z,
            shading="nearest",
        )
        # Keep the legend alongside the actual map when equal angular scaling
        # makes a wide scan occupy only a narrow horizontal strip.
        colorbar_axis = make_axes_locatable(axis).append_axes("right", size="3%", pad=0.12)
        colorbar = self.isocandela_figure.colorbar(mesh, cax=colorbar_axis)
        colorbar.set_label(f"{quantity} ({unit})", color="#CFDDE6")
        colorbar.ax.tick_params(colors="#B9CAD6")

        # Always expose the actual measured nodes.
        measured_c = []
        measured_g = []
        for ci, c_deg in enumerate(c_values):
            for gi, gamma_deg in enumerate(gamma_values):
                if np.isfinite(matrix[ci, gi]):
                    measured_c.append(c_deg)
                    measured_g.append(gamma_deg)
        axis.scatter(
            measured_c,
            measured_g,
            s=24,
            facecolors="none",
            edgecolors="white",
            linewidths=0.45,
            alpha=0.85,
            clip_on=False,
        )

        complete = int(np.count_nonzero(np.isfinite(matrix))) == int(matrix.size)
        if complete and len(c_values) >= 2 and len(gamma_values) >= 2:
            finite_values = matrix[np.isfinite(matrix)]
            vmin = float(np.min(finite_values))
            vmax = float(np.max(finite_values))
            if vmax > vmin:
                levels = np.linspace(vmin, vmax, 7)[1:-1]
                contours = axis.contour(
                    np.asarray(c_values, dtype=float),
                    np.asarray(gamma_values, dtype=float),
                    matrix.T,
                    levels=levels,
                    colors="#FFFFFF",
                    linewidths=0.9,
                    alpha=0.80,
                )
                axis.clabel(contours, inline=True, fontsize=7, fmt="%.4g")

        # The heatmap cells are centred on nodes. Do not display the half-cell
        # extension as measured coverage beyond the scan's outer nodes.
        if len(c_values) > 1:
            axis.set_xlim(c_values[0], c_values[-1])
        if len(gamma_values) > 1:
            axis.set_ylim(gamma_values[0], gamma_values[-1])
        if self.equal_scale_check.isChecked():
            axis.set_aspect("equal", adjustable="box")

        axis.set_xlabel("C angle (°)", color="#CFDDE6")
        axis.set_ylabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_title(
            f"Isocandela-style measured distribution • {quantity}",
            color="#E4EEF5",
            fontweight="bold",
        )
        aspect_note = "Equal 1° angular scale" if self.equal_scale_check.isChecked() else "Axes stretched to fit panel"
        self.isocandela_figure.text(
            0.03,
            0.025,
            "Circles = measured nodes; cells = nearest-node display; contours = visual interpolation\nICAO compliance NOT EVALUATED; C/Gamma are instrument angles; " + aspect_note,
            color="#90A8B8",
            fontsize=8,
            va="bottom",
            bbox={"facecolor": "#101820", "alpha": 0.9, "edgecolor": "none", "pad": 3},
        )
        self.isocandela_figure.subplots_adjust(
            left=0.09, right=0.92, bottom=0.17, top=0.86
        )
        self.isocandela_canvas.draw_idle()

    def _draw_surface(self):
        c_values, gamma_values, matrix = self._grid
        quantity, unit = self._quantity_descriptor()

        self.surface_figure.clear()
        self.surface_figure.patch.set_facecolor("#101820")
        axis = self.surface_figure.add_subplot(111, projection="3d")
        axis.set_facecolor("#101820")
        axis.tick_params(colors="#B9CAD6")
        for component in (axis.xaxis, axis.yaxis, axis.zaxis):
            component.set_pane_color((0.07, 0.11, 0.14, 1.0))

        c_mesh, g_mesh = np.meshgrid(
            np.asarray(c_values, dtype=float),
            np.asarray(gamma_values, dtype=float),
            indexing="ij",
        )
        complete = int(np.count_nonzero(np.isfinite(matrix))) == int(matrix.size)

        if complete and len(c_values) >= 2 and len(gamma_values) >= 2:
            axis.plot_surface(
                c_mesh,
                g_mesh,
                matrix,
                linewidth=0.25,
                antialiased=True,
                alpha=0.90,
            )
        mask = np.isfinite(matrix)
        axis.scatter(c_mesh[mask], g_mesh[mask], matrix[mask], s=16, color="#E6F0F7")

        axis.set_xlabel("C angle (°)", color="#CFDDE6")
        axis.set_ylabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_zlabel(f"{quantity} ({unit})", color="#CFDDE6")
        axis.set_title(
            f"Measured C × Gamma distribution • {quantity}",
            color="#E4EEF5",
            fontweight="bold",
        )
        self.surface_figure.text(
            0.03,
            0.025,
            "Dots = measured nodes; surface = visual interpolation\nICAO compliance NOT EVALUATED; C/Gamma are instrument angles",
            color="#90A8B8",
            fontsize=8,
        )
        self.surface_figure.subplots_adjust(
            left=0.00, right=0.90, bottom=0.17, top=0.86
        )
        self.surface_canvas.draw_idle()

    def _draw_cplane(self, *_args):
        if self._grid is None or self.cplane_combo.count() == 0:
            self._clear_figure(
                self.cplane_figure,
                self.cplane_canvas,
                "No C-plane data",
            )
            return

        c_values, gamma_values, matrix = self._grid
        selected = self.cplane_combo.currentData()
        if selected is None:
            return
        ci = min(range(len(c_values)), key=lambda i: abs(c_values[i] - float(selected)))
        values = matrix[ci, :]

        quantity, unit = self._quantity_descriptor()
        self.cplane_figure.clear()
        self.cplane_figure.patch.set_facecolor("#101820")
        axis = self.cplane_figure.add_subplot(111)
        self._style_axis(axis)

        axis.plot(
            np.asarray(gamma_values, dtype=float),
            values,
            marker="o",
            linewidth=2.0,
            markersize=4.5,
        )
        axis.axvline(0.0, linewidth=0.8, alpha=0.35)
        axis.set_xlabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_ylabel(f"{quantity} ({unit})", color="#CFDDE6")
        axis.set_title(
            f"C-plane {c_values[ci]:+.3f}° • measured nodes",
            color="#E4EEF5",
            fontweight="bold",
        )
        axis.text(
            0.01,
            0.01,
            "Markers = measured nodes; connecting lines = visual interpolation\nICAO compliance NOT EVALUATED",
            transform=axis.transAxes,
            color="#90A8B8",
            fontsize=8,
            va="bottom",
        )
        self.cplane_figure.subplots_adjust(
            left=0.10, right=0.97, bottom=0.15, top=0.87
        )
        self.cplane_canvas.draw_idle()

    def _draw_gplane(self, *_args):
        if self._grid is None or not self.gplane_combo.count():
            self._clear_figure(self.gplane_figure, self.gplane_canvas, "No fixed Gamma data")
            return
        c_values, gamma_values, matrix = self._grid
        selected = self.gplane_combo.currentData()
        gi = gamma_values.index(float(selected))
        quantity, unit = self._quantity_descriptor()
        self.gplane_figure.clear()
        self.gplane_figure.patch.set_facecolor("#101820")
        axis = self.gplane_figure.add_subplot(111)
        self._style_axis(axis)
        axis.plot(c_values, matrix[:, gi], marker="o", linewidth=2, markersize=4.5)
        axis.set_xlabel("C angle (°)", color="#CFDDE6")
        axis.set_ylabel(f"{quantity} ({unit})", color="#CFDDE6")
        axis.set_title(f"Fixed Gamma {gamma_values[gi]:+.3f}° • measured nodes", color="#E4EEF5", fontweight="bold")
        axis.text(0.01, 0.01, "Markers = measured nodes; connecting lines = visual interpolation\nICAO compliance NOT EVALUATED", transform=axis.transAxes, color="#90A8B8", fontsize=8, va="bottom")
        self.gplane_figure.subplots_adjust(left=0.10, right=0.97, bottom=0.15, top=0.87)
        self.gplane_canvas.draw_idle()

    def _redraw_active(self, *_args):
        if self._grid is None:
            return
        index = self.tabs.currentIndex()
        if index == 1:
            self._draw_surface()
        elif index == 2:
            self._draw_cplane()
        elif index == 3:
            self._draw_gplane()
        else:
            self._draw_isocandela()

    def active_figure(self):
        index = self.tabs.currentIndex()
        if index == 1:
            return self.surface_figure
        if index == 2:
            return self.cplane_figure
        if index == 3:
            return self.gplane_figure
        return self.isocandela_figure

    def save_active_plot(self, filename):
        """Export with sample/source context on every independently shared plot."""
        if self.run is None or self._grid is None or not np.any(np.isfinite(self._grid[2])):
            raise ValueError("No finite measurement data to export.")
        if self._source_sha256 and self._source_path:
            current = hashlib.sha256(self._source_path.read_bytes()).hexdigest()
            if current != self._source_sha256:
                raise ValueError("Source CSV has changed since loading. Reload it before exporting.")
        figure = self.active_figure()
        run = self.run
        source = self._source_path.name if self._source_path else "Session data"
        header = figure.text(0.02, 0.985, f"Lumigon | Sample: {run.sample_id} | Distance: {run.distance_m:g} m\nStart: {run.started_at.isoformat(timespec='seconds')} | Source: {source}", color="#CFDDE6", fontsize=8, va="top")
        c, g, matrix = self._grid
        coverage = f"Finite nodes: {np.isfinite(matrix).sum()}/{matrix.size} | ΔC {_step_text(c)} | ΔGamma {_step_text(g)}"
        footer = figure.text(0.02, -0.01, coverage + " | Scan completion unverified\n" + (f"Source SHA-256: {self._source_sha256}" if self._source_sha256 else "Source file checksum unavailable"), color="#90A8B8", fontsize=7, va="top")
        try:
            figure.savefig(filename, dpi=220, bbox_inches="tight")
        finally:
            header.remove()
            footer.remove()

    def export_active_plot(self):
        if self.run is None or self._grid is None:
            return

        directory = (
            self._source_path.parent
            if self._source_path is not None
            else measurement_data_directory()
        )
        directory.mkdir(parents=True, exist_ok=True)

        view_name = ("isocandela", "3d", "cplane", "fixed_gamma")[self.tabs.currentIndex()]
        label, _ = self._quantity_descriptor()
        quantity_name = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
        sample_name = re.sub(r"[^A-Za-z0-9._-]+", "_", self.run.sample_id).strip("._-") or "sample"
        default = directory / f"{sample_name}_{quantity_name}_{view_name}.png"

        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Visualization",
            str(default),
            "PNG image (*.png);;PDF (*.pdf);;SVG (*.svg)",
        )
        if not filename:
            return

        try:
            self.save_active_plot(filename)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Visualization",
                f"Could not export the active visualization:\n\n{exc}",
            )


def attach_visualization_workspace_v2(window):
    """Replace the Visualization placeholder with the Version 2 workspace."""

    tab = getattr(window, "visualization_tab", None)
    if tab is None:
        raise RuntimeError("Visualization tab is not available.")

    layout = tab.layout()
    if layout is None:
        layout = QVBoxLayout(tab)

    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            child_layout.deleteLater()

    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    workspace = VisualizationWorkspaceV2(window)
    layout.addWidget(workspace)
    window.visualization_workspace_controller = workspace
    return workspace
