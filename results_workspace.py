"""Results workspace for Lumigon measurement runs.

Phase 1 deliberately avoids another large point table.  It presents the latest
run summary and keeps the quantity selector ready for the next plotting phase
(Polar / Cartesian / Heatmap / 3D distribution).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from measurement_run import MeasurementRun, measurement_data_directory


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
            "Saved photometric runs and analysis — Polar, Cartesian, Heatmap and 3D will use this same run data."
        )
        subtitle.setObjectName("resultsSubtitle")
        subtitle.setWordWrap(True)
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.open_folder_button = QPushButton("Open Data Folder")
        self.open_folder_button.setObjectName("secondaryActionButton")
        self.open_folder_button.clicked.connect(self.open_data_folder)
        header.addWidget(self.open_folder_button, 0, Qt.AlignVCenter)
        root.addLayout(header)

        self.empty_label = QLabel(
            "No completed photometric measurement is available yet.\n"
            "After a successful Measurement run, Lumigon will save the full run automatically and show it here."
        )
        self.empty_label.setObjectName("resultsEmptyState")
        self.empty_label.setWordWrap(True)
        root.addWidget(self.empty_label)

        summary_box = QGroupBox("Latest Measurement Run")
        summary_form = QFormLayout(summary_box)
        summary_form.setContentsMargins(12, 12, 12, 12)
        summary_form.setHorizontalSpacing(18)
        summary_form.setVerticalSpacing(8)

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
        metrics_form.setVerticalSpacing(8)

        self.max_lux_label = QLabel("—")
        self.max_candela_label = QLabel("—")
        self.max_current_label = QLabel("—")
        self.peak_angle_label = QLabel("—")

        metrics_form.addRow("Maximum Lux:", self.max_lux_label)
        metrics_form.addRow("Maximum Candela:", self.max_candela_label)
        metrics_form.addRow("Maximum photocurrent:", self.max_current_label)
        metrics_form.addRow("Peak Candela position:", self.peak_angle_label)

        row = QHBoxLayout()
        row.addWidget(summary_box, 3)
        row.addWidget(metrics_box, 2)
        root.addLayout(row)

        analysis_box = QGroupBox("Analysis")
        analysis_layout = QHBoxLayout(analysis_box)
        analysis_layout.setContentsMargins(12, 10, 12, 10)
        analysis_layout.setSpacing(10)

        analysis_layout.addWidget(QLabel("Display quantity:"))
        self.quantity_combo = QComboBox()
        self.quantity_combo.addItems([
            "Candela",
            "Lux",
            "Photocurrent",
        ])
        analysis_layout.addWidget(self.quantity_combo)

        self.analysis_note = QLabel(
            "Next phase: Polar + Cartesian for single-axis runs; Heatmap + selectable C/Gamma planes + 3D distribution for C × Gamma runs."
        )
        self.analysis_note.setObjectName("resultsAnalysisNote")
        self.analysis_note.setWordWrap(True)
        analysis_layout.addWidget(self.analysis_note, 1)
        root.addWidget(analysis_box)
        root.addStretch(1)

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
            QLabel#resultsAnalysisNote {
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

    def open_data_folder(self):
        path = measurement_data_directory()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def build_results_workspace(window):
    workspace = ResultsWorkspace(window)
    window.results_workspace_controller = workspace
    return workspace
