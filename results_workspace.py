"""Results workspace for Lumigon measurement runs.

The Results tab is driven by MeasurementRun rather than by the Measurement
execution table. Saved CSV files can therefore be reopened later and analysed
with the same Polar/Cartesian tools as a newly completed run.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
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


def _caption(text):
    label = QLabel(text)
    label.setObjectName("resultsCaption")
    return label


class ResultsWorkspace(QWidget):
    def __init__(self, host_window):
        super().__init__()
        self.host_window = host_window
        self.latest_run: MeasurementRun | None = None
        self.setObjectName("resultsWorkspace")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(8)

        # --------------------------------------------------------------
        # Header
        # --------------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(8)
        title_block = QVBoxLayout()
        title_block.setSpacing(1)
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

        # --------------------------------------------------------------
        # Compact summary row.  The previous form used eight vertical rows and
        # pushed the Matplotlib canvases below the visible area on 900 px screens.
        # Keep the same information but present it in two compact cards.
        # --------------------------------------------------------------
        summary_box = QGroupBox("Measurement Run")
        summary = QGridLayout(summary_box)
        summary.setContentsMargins(10, 9, 10, 9)
        summary.setHorizontalSpacing(10)
        summary.setVerticalSpacing(4)

        self.run_id_label = QLabel("—")
        self.sample_label = QLabel("—")
        self.profile_label = QLabel("—")
        self.scan_label = QLabel("—")
        self.points_label = QLabel("—")
        self.duration_label = QLabel("—")
        self.home_label = QLabel("—")
        self.csv_label = QLabel("—")

        self.profile_label.setWordWrap(False)
        self.scan_label.setWordWrap(False)
        self.home_label.setWordWrap(False)
        self.csv_label.setWordWrap(False)
        self.csv_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        summary.addWidget(_caption("Run ID:"), 0, 0)
        summary.addWidget(self.run_id_label, 0, 1)
        summary.addWidget(_caption("Sample:"), 0, 2)
        summary.addWidget(self.sample_label, 0, 3)

        summary.addWidget(_caption("Profile:"), 1, 0)
        summary.addWidget(self.profile_label, 1, 1, 1, 3)

        summary.addWidget(_caption("Scan:"), 2, 0)
        summary.addWidget(self.scan_label, 2, 1, 1, 3)

        summary.addWidget(_caption("Points:"), 3, 0)
        summary.addWidget(self.points_label, 3, 1)
        summary.addWidget(_caption("Duration:"), 3, 2)
        summary.addWidget(self.duration_label, 3, 3)

        summary.addWidget(_caption("Home:"), 4, 0)
        summary.addWidget(self.home_label, 4, 1, 1, 3)

        summary.addWidget(_caption("CSV:"), 5, 0)
        summary.addWidget(self.csv_label, 5, 1, 1, 3)
        summary.setColumnStretch(1, 2)
        summary.setColumnStretch(3, 2)

        metrics_box = QGroupBox("Photometric Summary")
        metrics = QGridLayout(metrics_box)
        metrics.setContentsMargins(10, 9, 10, 9)
        metrics.setHorizontalSpacing(10)
        metrics.setVerticalSpacing(4)

        self.max_lux_label = QLabel("—")
        self.max_candela_label = QLabel("—")
        self.max_current_label = QLabel("—")
        self.peak_angle_label = QLabel("—")
        self.mean_candela_label = QLabel("—")
        self.fwhm_label = QLabel("—")

        metrics.addWidget(_caption("Max Lux:"), 0, 0)
        metrics.addWidget(self.max_lux_label, 0, 1)
        metrics.addWidget(_caption("Max Candela:"), 1, 0)
        metrics.addWidget(self.max_candela_label, 1, 1)
        metrics.addWidget(_caption("Max current:"), 2, 0)
        metrics.addWidget(self.max_current_label, 2, 1)
        metrics.addWidget(_caption("Peak position:"), 3, 0)
        metrics.addWidget(self.peak_angle_label, 3, 1)
        metrics.addWidget(_caption("Mean Candela:"), 4, 0)
        metrics.addWidget(self.mean_candela_label, 4, 1)
        metrics.addWidget(_caption("FWHM (50%):"), 5, 0)
        metrics.addWidget(self.fwhm_label, 5, 1)
        metrics.setColumnStretch(1, 1)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(8)
        summary_row.addWidget(summary_box, 3)
        summary_row.addWidget(metrics_box, 2)
        root.addLayout(summary_row)

        # --------------------------------------------------------------
        # Analysis controls
        # --------------------------------------------------------------
        analysis_box = QGroupBox("Analysis")
        analysis_layout = QHBoxLayout(analysis_box)
        analysis_layout.setContentsMargins(10, 7, 10, 7)
        analysis_layout.setSpacing(8)

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
        self.analysis_note.setWordWrap(False)
        analysis_layout.addWidget(self.analysis_note, 1)

        self.export_plot_button = QPushButton("Export Plot")
        self.export_plot_button.setObjectName("secondaryActionButton")
        self.export_plot_button.clicked.connect(self.export_plot)
        analysis_layout.addWidget(self.export_plot_button)
        root.addWidget(analysis_box)

        # Charts own all remaining vertical space.
        self.charts = ResultsCharts(self)
        self.charts.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.charts.setMinimumHeight(280)
        root.addWidget(self.charts, 1)
        root.setStretchFactor(self.charts, 1)

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
            QLabel#resultsCaption {
                color: #8EA6B6;
                font-weight: 600;
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
                padding-left: 6px;
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
            full_path = str(run.csv_path)
            self.csv_label.setText(run.csv_path.name)
            self.csv_label.setToolTip(full_path)
        elif run.save_error:
            self.csv_label.setText(f"Not saved: {run.save_error}")
            self.csv_label.setToolTip(run.save_error)
        else:
            self.csv_label.setText("Not saved")
            self.csv_label.setToolTip("")

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
        beam = beam_metrics(candela_series)
        self.mean_candela_label.setText(_fmt(beam.mean_value, " cd", 1))
        if beam.fwhm_deg is None:
            self.fwhm_label.setText("Not resolved")
            self.fwhm_label.setToolTip(
                "Two 50% peak crossings were not present inside the measured angular range."
            )
        else:
            self.fwhm_label.setText(f"{beam.fwhm_deg:.2f}°")
            self.fwhm_label.setToolTip("")

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
                "C × Gamma data detected — Heatmap, selectable planes and 3D distribution will use this run."
            )
        else:
            self.analysis_note.setText(
                f"{series.axis_name} sweep • {series.fixed_axis_name} = {series.fixed_angle:+.3f}° • sorted by physical angle."
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
