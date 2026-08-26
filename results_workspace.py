"""Results workspace for Lumigon measurement runs.

The Results tab is deliberately driven by MeasurementRun rather than by the
Measurement table. Saved CSV files can therefore be reopened later and use the
same Polar/Cartesian analysis as a newly completed run.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from measurement_run import MeasurementRun, measurement_data_directory
from measurement_run_io import load_measurement_run_csv
from results_charts import ResultsCharts, beam_metrics, extract_single_axis_series


def _fmt(value, unit="", decimals=3):
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{unit}"


class ResultsWorkspace(QWidget):
    def __init__(self, host_window):
        super().__init__()
        self.host_window = host_window
        self.latest_run: MeasurementRun | None = None
        self.setObjectName("resultsWorkspace")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title_block = QVBoxLayout()
        title = QLabel("Results")
        title.setObjectName("resultsTitle")
        subtitle = QLabel(
            "Photometric analysis from the active Measurement Run or a previously saved Lumigon CSV."
        )
        subtitle.setObjectName("resultsSubtitle")
        subtitle.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.load_csv_button = QPushButton("Load CSV")
        self.load_csv_button.clicked.connect(self.load_csv)
        header.addWidget(self.load_csv_button, 0, Qt.AlignVCenter)

        self.open_folder_button = QPushButton("Open Data Folder")
        self.open_folder_button.setObjectName("secondaryActionButton")
        self.open_folder_button.clicked.connect(self.open_data_folder)
        header.addWidget(self.open_folder_button, 0, Qt.AlignVCenter)
        root.addLayout(header)

        self.empty_label = QLabel(
            "No photometric measurement is loaded yet.\n"
            "Complete a Measurement run or use Load CSV to reopen a saved Lumigon result."
        )
        self.empty_label.setObjectName("resultsEmptyState")
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        summary_box = QGroupBox("Measurement Run")
        summary_form = QFormLayout(summary_box)
        summary_form.setContentsMargins(12, 12, 12, 12)
        summary_form.setHorizontalSpacing(18)
        summary_form.setVerticalSpacing(6)

        self.run_id_label = QLabel("—")
        self.sample_label = QLabel("—")
        self.profile_label = QLabel("—")
        self.scan_label = QLabel("—")
        self.points_label = QLabel("—")
        self.duration_label = QLabel("—")
        self.home_label = QLabel("—")
        self.csv_label = QLabel("—")
        self.csv_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.csv_label.setWordWrap(True)

        summary_form.addRow("Run ID:", self.run_id_label)
        summary_form.addRow("Sample:", self.sample_label)
        summary_form.addRow("Profile:", self.profile_label)
        summary_form.addRow("Scan:", self.scan_label)
        summary_form.addRow("Measured points:", self.points_label)
        summary_form.addRow("Total duration:", self.duration_label)
        summary_form.addRow("Home status:", self.home_label)
        summary_form.addRow("CSV:", self.csv_label)

        metrics_box = QGroupBox("Photometric Summary")
        metrics_form = QFormLayout(metrics_box)
        metrics_form.setContentsMargins(12, 12, 12, 12)
        metrics_form.setHorizontalSpacing(18)
        metrics_form.setVerticalSpacing(6)

        self.max_lux_label = QLabel("—")
        self.max_candela_label = QLabel("—")
        self.max_current_label = QLabel("—")
        self.peak_angle_label = QLabel("—")
        self.mean_candela_label = QLabel("—")
        self.fwhm_label = QLabel("—")

        metrics_form.addRow("Maximum Lux:", self.max_lux_label)
        metrics_form.addRow("Maximum Candela:", self.max_candela_label)
        metrics_form.addRow("Maximum photocurrent:", self.max_current_label)
        metrics_form.addRow("Peak Candela position:", self.peak_angle_label)
        metrics_form.addRow("Mean Candela:", self.mean_candela_label)
        metrics_form.addRow("50% beam width (FWHM):", self.fwhm_label)

        summary_row = QHBoxLayout()
        summary_row.addWidget(summary_box, 3)
        summary_row.addWidget(metrics_box, 2)
        root.addLayout(summary_row)

        analysis_box = QGroupBox("Analysis")
        analysis_layout = QHBoxLayout(analysis_box)
        analysis_layout.setContentsMargins(12, 8, 12, 8)
        analysis_layout.setSpacing(10)

        analysis_layout.addWidget(QLabel("Display quantity:"))
        self.quantity_combo = QComboBox()
        self.quantity_combo.addItems([
            "Candela",
            "Lux",
            "Photocurrent",
        ])
        self.quantity_combo.currentTextChanged.connect(self._quantity_changed)
        analysis_layout.addWidget(self.quantity_combo)

        self.analysis_note = QLabel(
            "Candela is the default photometric quantity. Polar and Cartesian views use the same measured points."
        )
        self.analysis_note.setObjectName("resultsAnalysisNote")
        self.analysis_note.setWordWrap(True)
        analysis_layout.addWidget(self.analysis_note, 1)

        self.export_plot_button = QPushButton("Export Plot")
        self.export_plot_button.setObjectName("secondaryActionButton")
        self.export_plot_button.clicked.connect(self.export_plot)
        analysis_layout.addWidget(self.export_plot_button)
        root.addWidget(analysis_box)

        self.charts = ResultsCharts(self)
        self.charts.setMinimumHeight(360)
        root.addWidget(self.charts, 1)

        self.summary_box = summary_box
        self.metrics_box = metrics_box
        self.analysis_box = analysis_box
        self._show_run_widgets(False)

        self.setStyleSheet(
            """
            QWidget#resultsWorkspace {
                background-color: #101820;
            }
            QLabel#resultsTitle {
                color: #E9F3FA;
                font-size: 18pt;
                font-weight: 700;
            }
            QLabel#resultsSubtitle {
                color: #7F98AA;
            }
            QLabel#resultsEmptyState {
                color: #AAB7C4;
                background-color: #17232D;
                border: 1px solid #34495E;
                border-radius: 6px;
                padding: 18px;
            }
            QLabel#resultsAnalysisNote,
            QLabel#resultsChartNote {
                color: #8AA8BC;
                padding-left: 8px;
            }
            """
        )

    def _show_run_widgets(self, visible):
        self.empty_label.setVisible(not visible)
        self.summary_box.setVisible(visible)
        self.metrics_box.setVisible(visible)
        self.analysis_box.setVisible(visible)
        self.charts.setVisible(visible)

    def set_run(self, run: MeasurementRun):
        self.latest_run = run
        self._show_run_widgets(True)

        self.run_id_label.setText(run.run_id)
        self.sample_label.setText(run.sample_id)
        self.profile_label.setText(
            f"{run.application} / {run.product} / {run.profile}"
        )
        self.scan_label.setText(
            f"{run.execution_mode} • {run.scan_mode} • distance {run.distance_m:.2f} m"
        )
        self.points_label.setText(str(run.point_count))
        self.duration_label.setText(f"{run.duration_s:.1f} s")
        self.home_label.setText(run.home_status)

        if run.csv_path is not None:
            self.csv_label.setText(str(run.csv_path))
        elif run.save_error:
            self.csv_label.setText(f"Not saved: {run.save_error}")
        else:
            self.csv_label.setText("Not saved")

        self.max_lux_label.setText(_fmt(run.max_lux, " lx", 3))
        self.max_candela_label.setText(_fmt(run.max_candela, " cd", 1))
        self.max_current_label.setText(_fmt(run.max_current_na, " nA", 3))

        peak = run.peak_candela_point
        if peak is None:
            self.peak_angle_label.setText("—")
        else:
            self.peak_angle_label.setText(
                f"C {peak.c_deg:+.3f}° • Gamma {peak.gamma_deg:+.3f}°"
            )

        candela_series = extract_single_axis_series(run, "Candela")
        metrics = beam_metrics(candela_series)
        self.mean_candela_label.setText(_fmt(metrics.mean_value, " cd", 1))
        if metrics.fwhm_deg is None:
            self.fwhm_label.setText("Not resolved in measured angular range")
        else:
            self.fwhm_label.setText(f"{metrics.fwhm_deg:.2f}°")

        self.charts.set_run(run)
        self.charts.set_quantity(self.quantity_combo.currentText())
        self._update_analysis_note()

    def _quantity_changed(self, text):
        self.charts.set_quantity(text)
        self._update_analysis_note()

    def _update_analysis_note(self):
        if self.latest_run is None:
            return
        series = extract_single_axis_series(
            self.latest_run,
            self.quantity_combo.currentText(),
        )
        if series is None:
            self.analysis_note.setText(
                "C × Gamma data detected. Heatmap, selectable photometric planes and 3D distribution will use this same run model in the grid phase."
            )
        else:
            self.analysis_note.setText(
                f"{series.axis_name} is the sweep axis; {series.fixed_axis_name} = {series.fixed_angle:+.3f}°. Plot values are sorted by physical angle, independent of scan direction."
            )

    def load_csv(self):
        directory = measurement_data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Lumigon Measurement CSV",
            str(directory),
            "Lumigon CSV (*.csv);;CSV files (*.csv);;All files (*.*)",
        )
        if not filename:
            return

        try:
            run = load_measurement_run_csv(filename)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Load Measurement CSV",
                f"Could not load the selected measurement file:\n\n{exc}",
            )
            return

        runs = getattr(self.host_window, "measurement_runs", None)
        if runs is None:
            runs = []
            self.host_window.measurement_runs = runs
        runs.append(run)
        self.host_window.latest_measurement_run = run
        self.set_run(run)

    def export_plot(self):
        if self.latest_run is None:
            return

        directory = measurement_data_directory()
        directory.mkdir(parents=True, exist_ok=True)
        default_name = (
            f"{self.latest_run.sample_id}_{self.quantity_combo.currentText()}_plot.png"
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Result Plot",
            str(directory / default_name),
            "PNG image (*.png);;PDF (*.pdf);;SVG (*.svg)",
        )
        if not filename:
            return

        try:
            self.charts.active_figure().savefig(
                filename,
                dpi=180,
                bbox_inches="tight",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Export Plot",
                f"Could not export the plot:\n\n{exc}",
            )

    def open_data_folder(self):
        path = measurement_data_directory()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def build_results_workspace(window):
    workspace = ResultsWorkspace(window)
    window.results_workspace_controller = workspace
    return workspace


def attach_results_workspace(window):
    """Replace the existing Results placeholder without rebuilding the tab strip."""

    tab = getattr(window, "results_tab", None)
    if tab is None:
        raise RuntimeError("Results tab is not available.")

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
    workspace = build_results_workspace(window)
    layout.addWidget(workspace)
    window.measurement_runs = []
    window.latest_measurement_run = None
    return workspace
