"""Run-progress popup for Lumigon Version 2 Measurement."""

from __future__ import annotations

from datetime import datetime, timedelta
import time

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)


def _format_duration(seconds) -> str:
    if seconds is None:
        return "Estimating…"
    try:
        seconds = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "Estimating…"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class MeasurementProgressDialogV2(QDialog):
    """Non-blocking measurement progress popup with ETA and abort control."""

    abort_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lumigon — Measurement Progress")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(620)
        self.setMinimumHeight(330)

        self._running = False
        self._started_monotonic = None
        self._started_wall = None
        self._remaining_s = None
        self._completed = 0
        self._total = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Measurement in progress")
        title.setObjectName("measurementProgressTitle")
        root.addWidget(title)

        self.status_label = QLabel("Preparing measurement…")
        self.status_label.setObjectName("measurementProgressStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(56)
        root.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0% • 0/0 points")
        self.progress_bar.setMinimumHeight(28)
        root.addWidget(self.progress_bar)

        time_box = QGroupBox("Timing")
        grid = QGridLayout(time_box)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        self.current_time_label = QLabel("—")
        self.started_time_label = QLabel("—")
        self.elapsed_label = QLabel("00:00")
        self.remaining_label = QLabel("Estimating…")
        self.finish_label = QLabel("—")

        grid.addWidget(QLabel("Current time:"), 0, 0)
        grid.addWidget(self.current_time_label, 0, 1)
        grid.addWidget(QLabel("Started:"), 1, 0)
        grid.addWidget(self.started_time_label, 1, 1)
        grid.addWidget(QLabel("Elapsed:"), 2, 0)
        grid.addWidget(self.elapsed_label, 2, 1)
        grid.addWidget(QLabel("Estimated remaining:"), 3, 0)
        grid.addWidget(self.remaining_label, 3, 1)
        grid.addWidget(QLabel("Estimated finish:"), 4, 0)
        grid.addWidget(self.finish_label, 4, 1)
        grid.setColumnStretch(1, 1)
        root.addWidget(time_box)

        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self.abort_button = QPushButton("Abort Measurement")
        self.abort_button.setObjectName("measurementAbortButton")
        self.abort_button.setFixedWidth(180)
        self.abort_button.setToolTip(
            "Controlled abort: acquisition stops at a safe checkpoint, then "
            "Gamma and C return to 0°. Use the physical E-STOP for an emergency."
        )
        self.abort_button.clicked.connect(self.request_abort)
        buttons.addWidget(self.abort_button)

        self.close_button = QPushButton("Close")
        self.close_button.setFixedWidth(110)
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.close)
        buttons.addWidget(self.close_button)
        root.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._update_clock)

        self.setStyleSheet(
            """
            QDialog {
                background-color: #101820;
                color: #E8EEF3;
            }
            QLabel#measurementProgressTitle {
                color: #E9F3FA;
                font-size: 18pt;
                font-weight: 700;
            }
            QLabel#measurementProgressStatus {
                color: #9DD5F3;
                background-color: #142A38;
                border: 1px solid #2C617E;
                border-radius: 5px;
                padding: 9px 11px;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid #34495E;
                border-radius: 7px;
                margin-top: 10px;
                padding-top: 10px;
                font-weight: 600;
            }
            QProgressBar {
                border: 1px solid #34495E;
                border-radius: 5px;
                background-color: #14212B;
                color: #FFFFFF;
                text-align: center;
                font-weight: 700;
            }
            QProgressBar::chunk {
                background-color: #1769AA;
                border-radius: 4px;
            }
            QPushButton#measurementAbortButton {
                background-color: #C62828;
                color: #FFFFFF;
                border: 1px solid #EF5350;
                border-radius: 5px;
                padding: 7px 12px;
                font-weight: 700;
            }
            QPushButton#measurementAbortButton:hover {
                background-color: #D32F2F;
                border-color: #FF6B6B;
            }
            QPushButton#measurementAbortButton:pressed {
                background-color: #8E1B1B;
            }
            QPushButton#measurementAbortButton:disabled {
                background-color: #5A2A2A;
                color: #B9A0A0;
                border-color: #6C3B3B;
            }
            """
        )

    def begin(self, *, total_points: int, initial_status: str):
        self._running = True
        self._started_monotonic = time.monotonic()
        self._started_wall = datetime.now().astimezone()
        self._remaining_s = None
        self._completed = 0
        self._total = max(0, int(total_points))

        self.status_label.setText(str(initial_status))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"0% • 0/{self._total} points")
        self.started_time_label.setText(self._started_wall.strftime("%H:%M:%S"))
        self.elapsed_label.setText("00:00")
        self.remaining_label.setText("Estimating…")
        self.finish_label.setText("—")
        self.abort_button.setEnabled(True)
        self.close_button.setEnabled(False)

        self._timer.start()
        self._update_clock()
        self.show()
        self.raise_()
        self.activateWindow()

    def set_status(self, text: str):
        self.status_label.setText(str(text))

    def update_progress(
        self,
        *,
        completed: int,
        total: int,
        remaining_s=None,
        percent=None,
    ):
        self._completed = max(0, int(completed))
        self._total = max(0, int(total))
        self._remaining_s = remaining_s

        if percent is None:
            percent = (
                int(round(100.0 * self._completed / self._total))
                if self._total > 0
                else 0
            )
        else:
            percent = int(round(float(percent)))
        percent = max(0, min(100, percent))
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(
            f"{percent}% • {self._completed}/{self._total} points"
        )
        self._update_clock()

    def finish_success(self, text: str):
        self._running = False
        self._remaining_s = 0.0
        if self._total > 0:
            self._completed = self._total
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(
            f"100% • {self._completed}/{self._total} points"
        )
        self.status_label.setText(str(text))
        self.status_label.setStyleSheet(
            "color:#55EFC4; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:9px 11px; font-weight:700;"
        )
        self.abort_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._update_clock()
        self._timer.stop()

    def finish_aborted(self, text: str):
        self._finish_non_success(text, "#E7C76A")

    def finish_failed(self, text: str):
        self._finish_non_success(text, "#FF7675")

    def _finish_non_success(self, text: str, color: str):
        self._running = False
        self.status_label.setText(str(text))
        self.status_label.setStyleSheet(
            f"color:{color}; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:9px 11px; font-weight:700;"
        )
        self.abort_button.setEnabled(False)
        self.close_button.setEnabled(True)
        self._update_clock()
        self._timer.stop()

    def request_abort(self):
        if not self._running:
            return
        self.abort_button.setEnabled(False)
        self.status_label.setText(
            "Abort requested — stopping safely, then returning both axes to 0°…"
        )
        self.abort_requested.emit()

    def _update_clock(self):
        now = datetime.now().astimezone()
        self.current_time_label.setText(now.strftime("%H:%M:%S"))

        if self._started_monotonic is not None:
            elapsed = max(0.0, time.monotonic() - self._started_monotonic)
            self.elapsed_label.setText(_format_duration(elapsed))

        self.remaining_label.setText(_format_duration(self._remaining_s))
        if self._remaining_s is None:
            self.finish_label.setText("—")
        else:
            finish = now + timedelta(seconds=max(0.0, float(self._remaining_s)))
            self.finish_label.setText(finish.strftime("%H:%M:%S"))

    def closeEvent(self, event):
        if self._running:
            # Keep progress/abort controls visible while hardware is moving.
            event.ignore()
            self.raise_()
            return
        super().closeEvent(event)
