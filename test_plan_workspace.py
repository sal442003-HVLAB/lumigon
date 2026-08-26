"""Detached Test Plan review/run workspace for Lumigon.

The workspace reuses the active Measurement Test Plan table and the existing
measurement workers. It owns the review/run presentation so modal progress
dialogs are no longer needed when a run is launched from this window.
"""

import math
import threading
import time

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from continuous_measurement import ContinuousMeasurementWorker
from measurement_execution import MeasurementRunWorker
from motion_controller import C_AXIS, GAMMA


SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
SCAN_GRID = 2
FIXED_AXIS_TOLERANCE_DEG = 0.05
MEASUREMENT_OVERHEAD_MS = 6
INTER_SAMPLE_DELAY_MS = 50


def _readonly_item(text):
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def _table_angle(item):
    if item is None:
        raise ValueError("Missing angle in Test Plan.")
    return float(item.text().replace("°", "").strip())


def _format_duration(seconds):
    seconds = max(0.0, float(seconds))
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} h {minutes} min {secs} s"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


class CommissioningMotionWorker(QThread):
    """Step through a validated single-axis plan without Lux acquisition.

    This is intentionally a commissioning fallback. It uses the same motion
    controller and safety verification as normal Step Scan, but does not create
    photometric results when the Luxmeter is disconnected.
    """

    progress = Signal(str)
    point_started = Signal(int, int, int, float, float)
    point_done = Signal(int, int, int, float, float)
    pause_state = Signal(bool)
    run_completed = Signal()
    aborted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        motion,
        scan_mode,
        points,
        settle_time_s,
        parent=None,
    ):
        super().__init__(parent)
        self.motion = motion
        self.scan_mode = int(scan_mode)
        self.points = [
            (int(row), float(c_deg), float(gamma_deg))
            for row, c_deg, gamma_deg in points
        ]
        self.settle_time_s = max(0.0, float(settle_time_s))
        self._pause_event = threading.Event()

    def request_pause(self, paused):
        paused = bool(paused)
        if paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()
        self.pause_state.emit(paused)

    def _wait_while_paused(self):
        while self._pause_event.is_set():
            if self.isInterruptionRequested():
                return False
            self.msleep(50)
        return not self.isInterruptionRequested()

    def _wait_interruptible(self, seconds):
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return False
            if not self._wait_while_paused():
                return False
            remaining = deadline - time.monotonic()
            self.msleep(max(1, min(50, int(remaining * 1000.0))))
        return not self.isInterruptionRequested()

    def _axes_for_mode(self, c_target, gamma_target):
        if self.scan_mode == SCAN_SINGLE_C_GAMMA:
            return C_AXIS, c_target, GAMMA, gamma_target
        if self.scan_mode == SCAN_SINGLE_GAMMA_C:
            return GAMMA, gamma_target, C_AXIS, c_target
        raise RuntimeError("Motion-only commissioning supports single-axis plans only.")

    def _verify_fixed_axis(self, axis, target):
        actual = self.motion.get_current_angle(axis)
        error = actual - target
        if abs(error) > FIXED_AXIS_TOLERANCE_DEG:
            raise RuntimeError(
                f"{axis.name} is fixed at {target:+.3f}°, but current position is "
                f"{actual:+.3f}° (error {error:+.3f}°)."
            )

    def run(self):
        try:
            if not self.points:
                raise RuntimeError("No Ready points were supplied.")

            total = len(self.points)
            for sequence, (row, c_target, gamma_target) in enumerate(
                self.points,
                start=1,
            ):
                if self.isInterruptionRequested():
                    self.aborted.emit("Motion-only run aborted before the next point.")
                    return
                if not self._wait_while_paused():
                    self.aborted.emit("Motion-only run aborted while paused.")
                    return

                fixed_axis, fixed_target, sweep_axis, sweep_target = self._axes_for_mode(
                    c_target,
                    gamma_target,
                )
                self._verify_fixed_axis(fixed_axis, fixed_target)

                self.point_started.emit(
                    row,
                    sequence,
                    total,
                    c_target,
                    gamma_target,
                )
                self.progress.emit(
                    f"Point {sequence}/{total}: moving {sweep_axis.name} "
                    f"to {sweep_target:+.3f}°"
                )
                self.motion.move_absolute(sweep_axis, sweep_target)

                if self.isInterruptionRequested():
                    self.aborted.emit(
                        "Abort requested. The active servo move completed safely."
                    )
                    return

                if self.settle_time_s > 0.0:
                    self.progress.emit(
                        f"Point {sequence}/{total}: settling for "
                        f"{self.settle_time_s:.1f} s"
                    )
                    if not self._wait_interruptible(self.settle_time_s):
                        self.aborted.emit("Motion-only run aborted during settling.")
                        return

                self.point_done.emit(
                    row,
                    sequence,
                    total,
                    c_target,
                    gamma_target,
                )

            self.run_completed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class TestPlanWorkspace(QMainWindow):
    """Maximized review and live-run workspace backed by the active plan."""

    def __init__(
        self,
        host_window,
        plan_table,
        execution_box,
        build_button,
        validate_button,
    ):
        super().__init__(host_window)
        self.host_window = host_window
        self.plan_table = plan_table
        self.execution_box = execution_box
        self.build_button = build_button
        self.validate_button = validate_button

        self.active_worker = None
        self.active_mode = None
        self.motion_only = False
        self.main_timer_was_active = False
        self.run_started_at = 0.0
        self.run_total = 0
        self.run_completed = 0
        self.run_initial_estimate_s = 0.0
        self.run_finished_normally = False
        self.paused = False

        self.setWindowTitle("Lumigon — Test Plan Workspace")
        self.setWindowFlag(Qt.Window, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(1400, 820)

        central = QWidget(self)
        central.setObjectName("testPlanWorkspace")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        title = QLabel("Test Plan Workspace")
        title.setObjectName("testPlanWorkspaceTitle")
        subtitle = QLabel(
            "Full-size review and live run view — uses the active Measurement plan and engine"
        )
        subtitle.setObjectName("testPlanWorkspaceSubtitle")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.state_label = QLabel("DRAFT")
        self.state_label.setObjectName("testPlanWorkspaceState")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumWidth(230)
        header.addWidget(self.state_label, 0, Qt.AlignVCenter)

        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("secondaryActionButton")
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.close_button, 0, Qt.AlignVCenter)

        root.addLayout(header)

        context_box = QGroupBox("Plan Context")
        context_box.setObjectName("testPlanContextBox")
        context = QGridLayout(context_box)
        context.setContentsMargins(12, 10, 12, 10)
        context.setHorizontalSpacing(18)
        context.setVerticalSpacing(6)

        self.identity_label = QLabel("—")
        self.identity_label.setWordWrap(True)
        self.scan_label = QLabel("—")
        self.scan_label.setWordWrap(True)
        self.acquisition_label = QLabel("—")
        self.acquisition_label.setWordWrap(True)
        self.progress_label = QLabel("—")
        self.progress_label.setWordWrap(True)

        context.addWidget(QLabel("Test:"), 0, 0)
        context.addWidget(self.identity_label, 0, 1)
        context.addWidget(QLabel("Angular scan:"), 1, 0)
        context.addWidget(self.scan_label, 1, 1)
        context.addWidget(QLabel("Acquisition:"), 0, 2)
        context.addWidget(self.acquisition_label, 0, 3)
        context.addWidget(QLabel("Plan status:"), 1, 2)
        context.addWidget(self.progress_label, 1, 3)
        context.setColumnStretch(1, 3)
        context.setColumnStretch(3, 2)

        root.addWidget(context_box)

        self.run_box = QGroupBox("Live Measurement Run")
        self.run_box.setObjectName("testPlanRunBox")
        run_layout = QVBoxLayout(self.run_box)
        run_layout.setContentsMargins(12, 10, 12, 10)
        run_layout.setSpacing(8)

        self.run_status_label = QLabel("Ready")
        self.run_status_label.setObjectName("testPlanRunStatus")
        self.run_status_label.setWordWrap(True)
        run_layout.addWidget(self.run_status_label)

        run_grid = QGridLayout()
        run_grid.setHorizontalSpacing(18)
        run_grid.setVerticalSpacing(5)

        self.run_point_label = QLabel("—")
        self.run_target_label = QLabel("—")
        self.run_live_angle_label = QLabel("—")
        self.run_photometry_label = QLabel("—")
        self.run_completed_label = QLabel("0")
        self.run_remaining_label = QLabel("0")
        self.run_elapsed_label = QLabel("0 s")
        self.run_eta_label = QLabel("—")

        run_grid.addWidget(QLabel("Current point:"), 0, 0)
        run_grid.addWidget(self.run_point_label, 0, 1)
        run_grid.addWidget(QLabel("Target:"), 1, 0)
        run_grid.addWidget(self.run_target_label, 1, 1)
        run_grid.addWidget(QLabel("Live position:"), 2, 0)
        run_grid.addWidget(self.run_live_angle_label, 2, 1)

        run_grid.addWidget(QLabel("Photometry:"), 0, 2)
        run_grid.addWidget(self.run_photometry_label, 0, 3)
        run_grid.addWidget(QLabel("Completed:"), 1, 2)
        run_grid.addWidget(self.run_completed_label, 1, 3)
        run_grid.addWidget(QLabel("Remaining:"), 2, 2)
        run_grid.addWidget(self.run_remaining_label, 2, 3)

        run_grid.addWidget(QLabel("Elapsed:"), 0, 4)
        run_grid.addWidget(self.run_elapsed_label, 0, 5)
        run_grid.addWidget(QLabel("Estimated remaining:"), 1, 4)
        run_grid.addWidget(self.run_eta_label, 1, 5)

        run_grid.setColumnStretch(1, 2)
        run_grid.setColumnStretch(3, 2)
        run_grid.setColumnStretch(5, 1)
        run_layout.addLayout(run_grid)

        self.run_progress = QProgressBar()
        self.run_progress.setRange(0, 1)
        self.run_progress.setValue(0)
        self.run_progress.setFormat("%v / %m points   •   %p%")
        run_layout.addWidget(self.run_progress)

        self.run_box.hide()
        root.addWidget(self.run_box, 0)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        section_title = QLabel("Test Plan")
        section_title.setObjectName("measurementSectionTitle")
        toolbar.addWidget(section_title)
        toolbar.addStretch(1)

        self.rebuild_button = QPushButton("Build / Rebuild Plan")
        self.revalidate_button = QPushButton("Validate Plan")
        self.rebuild_button.clicked.connect(self.build_button.click)
        self.revalidate_button.clicked.connect(self.validate_button.click)
        toolbar.addWidget(self.rebuild_button)
        toolbar.addWidget(self.revalidate_button)
        root.addLayout(toolbar)

        self.plan_table.setParent(central)
        self.plan_table.setMinimumHeight(360)
        root.addWidget(self.plan_table, 1)

        self.execution_box.setParent(central)
        root.addWidget(self.execution_box, 0)

        self.step_start_button = getattr(
            host_window,
            "measurement_start_button",
            None,
        )
        self.continuous_start_button = getattr(
            host_window,
            "measurement_continuous_start_button",
            None,
        )
        self.pause_button = getattr(
            host_window,
            "measurement_pause_button",
            None,
        )
        self.abort_button = getattr(
            host_window,
            "measurement_abort_button",
            None,
        )
        self.step_mode_button = getattr(
            host_window,
            "measurement_step_mode_button",
            None,
        )
        self.continuous_mode_button = getattr(
            host_window,
            "measurement_continuous_mode_button",
            None,
        )

        self._take_over_execution_buttons()
        self._apply_mode_button_style()

        self.run_clock = QTimer(self)
        self.run_clock.setInterval(500)
        self.run_clock.timeout.connect(self._refresh_run_clock)

        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(200)
        self.sync_timer.timeout.connect(self.refresh_summary)
        self.sync_timer.start()

        self.setStyleSheet(
            host_window.styleSheet()
            + """
            QMainWindow {
                background-color: #101820;
            }
            QWidget#testPlanWorkspace {
                background-color: #101820;
            }
            QLabel#testPlanWorkspaceTitle {
                color: #E9F3FA;
                font-size: 19pt;
                font-weight: 700;
            }
            QLabel#testPlanWorkspaceSubtitle {
                color: #7F98AA;
                padding-bottom: 2px;
            }
            QLabel#testPlanWorkspaceState {
                border-radius: 12px;
                padding: 7px 12px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QGroupBox#testPlanContextBox QLabel {
                color: #B8CAD6;
            }
            QGroupBox#testPlanRunBox {
                border: 1px solid #2C7DBB;
            }
            QLabel#testPlanRunStatus {
                color: #D7E8F4;
                background-color: #132431;
                border: 1px solid #24465C;
                border-radius: 5px;
                padding: 7px;
            }
            QProgressBar {
                border: 1px solid #34495E;
                border-radius: 5px;
                background-color: #111B23;
                text-align: center;
                min-height: 22px;
            }
            QProgressBar::chunk {
                background-color: #1769AA;
                border-radius: 4px;
            }
            """
        )

        self.refresh_summary()

    def _take_over_execution_buttons(self):
        if self.step_start_button is not None:
            try:
                self.step_start_button.clicked.disconnect()
            except RuntimeError:
                pass
            self.step_start_button.clicked.connect(self.start_step_scan)

        if self.continuous_start_button is not None:
            try:
                self.continuous_start_button.clicked.disconnect()
            except RuntimeError:
                pass
            self.continuous_start_button.clicked.connect(self.start_continuous_scan)

        if self.pause_button is not None:
            try:
                self.pause_button.clicked.disconnect()
            except RuntimeError:
                pass
            self.pause_button.clicked.connect(self.toggle_pause)
            self.pause_button.hide()

        if self.abort_button is not None:
            try:
                self.abort_button.clicked.disconnect()
            except RuntimeError:
                pass
            self.abort_button.clicked.connect(self.request_abort)
            self.abort_button.hide()

    def _apply_mode_button_style(self):
        if self.step_mode_button is not None:
            self.step_mode_button.setObjectName("measurementModeButton")
        if self.continuous_mode_button is not None:
            self.continuous_mode_button.setObjectName("measurementModeButton")

        page = getattr(self.host_window, "measurement_workspace", None)
        if page is not None:
            page.setStyleSheet(
                page.styleSheet()
                + """
                QPushButton#measurementModeButton {
                    background-color: #14212B;
                    color: #C9D7E1;
                    border: 1px solid #34495E;
                    border-radius: 5px;
                    padding: 7px 14px;
                }
                QPushButton#measurementModeButton:checked {
                    background-color: #1769AA;
                    color: #FFFFFF;
                    border: 1px solid #2C7DBB;
                    font-weight: 600;
                }
                QPushButton#measurementModeButton:hover:!checked {
                    background-color: #1C303F;
                }
                """
            )

    def _set_source_state(self, text, object_name):
        state = getattr(self.host_window, "measurement_state_label", None)
        if state is None:
            return
        state.setText(text)
        state.setObjectName(object_name)
        state.style().unpolish(state)
        state.style().polish(state)

    def _execution_mode_text(self):
        if (
            self.continuous_mode_button is not None
            and self.continuous_mode_button.isChecked()
        ):
            return "Continuous Scan"
        return "Step Scan"

    def _scan_text(self):
        window = self.host_window
        mode = window.measurement_scan_mode_combo.currentIndex()

        c_start = window.measurement_c_start.value()
        c_end = window.measurement_c_end.value()
        c_step = window.measurement_c_step.value()
        gamma_start = window.measurement_gamma_start.value()
        gamma_end = window.measurement_gamma_end.value()
        gamma_step = window.measurement_gamma_step.value()

        if mode == SCAN_SINGLE_C_GAMMA:
            return (
                f"C {c_start:+.2f}° fixed  •  Gamma {gamma_start:+.2f}° → "
                f"{gamma_end:+.2f}°  •  step {gamma_step:g}°"
            )
        if mode == SCAN_SINGLE_GAMMA_C:
            return (
                f"Gamma {gamma_start:+.2f}° fixed  •  C {c_start:+.2f}° → "
                f"{c_end:+.2f}°  •  step {c_step:g}°"
            )

        traversal = window.measurement_scan_order_combo.currentText()
        return (
            f"C {c_start:+.2f}° → {c_end:+.2f}° / {c_step:g}°  •  "
            f"Gamma {gamma_start:+.2f}° → {gamma_end:+.2f}° / {gamma_step:g}°  •  "
            f"{traversal}"
        )

    def _status_counts(self):
        counts = {}
        for row in range(self.plan_table.rowCount()):
            item = self.plan_table.item(row, 8)
            status = item.text().strip() if item is not None else "—"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _ready_points(self):
        points = []
        for row in range(self.plan_table.rowCount()):
            status = self.plan_table.item(row, 8)
            if status is None or status.text() != "Ready":
                continue
            c_deg = _table_angle(self.plan_table.item(row, 1))
            gamma_deg = _table_angle(self.plan_table.item(row, 2))
            points.append((row, c_deg, gamma_deg))
        return points

    def _apply_state_style(self, text):
        upper = text.upper()
        if "INVALID" in upper or "FAILED" in upper:
            self.state_label.setStyleSheet(
                "color:#FFC9C9; background:#3A1F24; border:1px solid #9C3D49;"
            )
        elif "VALIDATED" in upper or "COMPLETE" in upper:
            self.state_label.setStyleSheet(
                "color:#BFE7C8; background:#173226; border:1px solid #2E7D4B;"
            )
        else:
            self.state_label.setStyleSheet(
                "color:#9DB4C4; background:#1B2934; border:1px solid #3B5365;"
            )

    def refresh_summary(self):
        window = self.host_window

        source_state = getattr(window, "measurement_state_label", None)
        state_text = source_state.text() if source_state is not None else "DRAFT"
        self.state_label.setText(state_text)
        self._apply_state_style(state_text)

        application = window.measurement_application_combo.currentText()
        product = window.measurement_product_combo.currentText()
        profile = window.measurement_profile_combo.currentText()
        sample = window.measurement_sample_id_edit.text().strip() or "Sample ID not set"
        self.identity_label.setText(
            f"{application}  /  {product}  /  {profile}  •  {sample}"
        )

        self.scan_label.setText(self._scan_text())

        distance = window.measurement_distance_spin.value()
        integration = window.measurement_integration_spin.value()
        settle = window.measurement_settle_spin.value()
        samples = window.measurement_samples_spin.value()
        execution = self._execution_mode_text()
        self.acquisition_label.setText(
            f"{execution}  •  distance {distance:.2f} m  •  integration {integration} ms  •  "
            f"settle {settle:.1f} s  •  {samples} sample(s)/point"
        )

        counts = self._status_counts()
        total = self.plan_table.rowCount()
        measured = counts.get("Measured", 0)
        ready = counts.get("Ready", 0)
        running = counts.get("Running", 0)
        pending = counts.get("Pending", 0)
        motion_ok = counts.get("Motion OK", 0)
        self.progress_label.setText(
            f"{total} points  •  {measured} measured  •  {motion_ok} motion OK  •  "
            f"{ready} ready  •  {running} running  •  {pending} pending"
        )

    def open_maximized(self):
        self.refresh_summary()
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _begin_run(self, *, mode_text, total, estimate_s, motion_only):
        self.active_mode = mode_text
        self.motion_only = bool(motion_only)
        self.run_total = max(1, int(total))
        self.run_completed = 0
        self.run_started_at = time.monotonic()
        self.run_initial_estimate_s = max(0.0, float(estimate_s))
        self.run_finished_normally = False
        self.paused = False

        self.run_box.show()
        self.run_status_label.setText(
            "Motion-only commissioning run — Luxmeter is not connected."
            if self.motion_only
            else f"{mode_text} started."
        )
        self.run_point_label.setText("—")
        self.run_target_label.setText("—")
        self.run_live_angle_label.setText("—")
        self.run_photometry_label.setText(
            "No Lux acquisition"
            if self.motion_only
            else "Waiting for first reading…"
        )
        self.run_completed_label.setText("0")
        self.run_remaining_label.setText(str(self.run_total))
        self.run_elapsed_label.setText("0 s")
        self.run_eta_label.setText(_format_duration(self.run_initial_estimate_s))
        self.run_progress.setRange(0, self.run_total)
        self.run_progress.setValue(0)

        self.run_clock.start()
        self._set_running_controls(True)

    def _refresh_run_clock(self):
        if self.run_started_at <= 0:
            return
        elapsed = max(0.0, time.monotonic() - self.run_started_at)
        remaining = max(0, self.run_total - self.run_completed)

        if self.run_completed > 0:
            eta = (elapsed / self.run_completed) * remaining
        else:
            eta = max(0.0, self.run_initial_estimate_s - elapsed)

        self.run_elapsed_label.setText(_format_duration(elapsed))
        self.run_eta_label.setText(_format_duration(eta))

    def _set_run_completed(self, completed):
        self.run_completed = max(0, min(int(completed), self.run_total))
        self.run_completed_label.setText(str(self.run_completed))
        self.run_remaining_label.setText(
            str(max(0, self.run_total - self.run_completed))
        )
        self.run_progress.setValue(self.run_completed)
        self._refresh_run_clock()

    def _set_current_point(self, sequence, total, c_deg, gamma_deg):
        self.run_point_label.setText(f"{sequence} / {total}")
        self.run_target_label.setText(
            f"C {c_deg:+.3f}°   •   Gamma {gamma_deg:+.3f}°"
        )

    def _set_live_position(self, c_deg, gamma_deg):
        self.run_live_angle_label.setText(
            f"C {c_deg:+.3f}°   •   Gamma {gamma_deg:+.3f}°"
        )

    def _set_photometry(self, current_na, lux, candela, stdev=None):
        if stdev is None:
            self.run_photometry_label.setText(
                f"{current_na:.2f} nA  •  {lux:.3f} lx  •  {candela:.1f} cd"
            )
        else:
            self.run_photometry_label.setText(
                f"{current_na:.2f} nA  •  {lux:.3f} lx  •  {candela:.1f} cd  •  "
                f"σ {stdev:.3f} lx"
            )

    def _finish_run_monitor(self, text):
        self.run_clock.stop()
        self.run_status_label.setText(text)
        self._refresh_run_clock()

    def _validated_single_axis_problem(self):
        if self.step_start_button is None or not self.step_start_button.isEnabled():
            return "Build and Validate the Test Plan before starting."
        if self.host_window.measurement_scan_mode_combo.currentIndex() == SCAN_GRID:
            return (
                "C × Gamma Grid automatic execution is not enabled yet. "
                "Use a single-axis plan for this commissioning run."
            )

        modbus = getattr(self.host_window, "modbus", None)
        if modbus is None or not modbus.is_connected:
            return "Connect the servo drives before measuring."

        motion = getattr(self.host_window, "motion", None)
        if motion is None:
            return "Motion controller is not available."
        if motion.gamma_zero_puu is None or motion.c_zero_puu is None:
            return "Capture a valid Session Zero for both axes before measuring."

        if not self._ready_points():
            return "There are no Ready points remaining in this plan."
        return None

    def _set_editors_enabled(self, enabled):
        names = (
            "measurement_application_combo",
            "measurement_product_combo",
            "measurement_profile_combo",
            "measurement_sample_id_edit",
            "measurement_distance_spin",
            "measurement_scan_mode_combo",
            "measurement_c_start",
            "measurement_c_end",
            "measurement_c_step",
            "measurement_gamma_start",
            "measurement_gamma_end",
            "measurement_gamma_step",
            "measurement_scan_order_combo",
            "measurement_settle_spin",
            "measurement_samples_spin",
            "measurement_integration_spin",
            "measurement_build_plan_button",
            "measurement_validate_plan_button",
        )
        for name in names:
            control = getattr(self.host_window, name, None)
            if control is not None:
                control.setEnabled(enabled)

        if enabled:
            mode = self.host_window.measurement_scan_mode_combo.currentIndex()
            if mode == SCAN_SINGLE_C_GAMMA:
                self.host_window.measurement_c_end.setEnabled(False)
                self.host_window.measurement_c_step.setEnabled(False)
            elif mode == SCAN_SINGLE_GAMMA_C:
                self.host_window.measurement_gamma_end.setEnabled(False)
                self.host_window.measurement_gamma_step.setEnabled(False)

    def _set_running_controls(self, running):
        self._set_editors_enabled(not running)
        self.rebuild_button.setEnabled(not running)
        self.revalidate_button.setEnabled(not running)
        self.close_button.setEnabled(not running)

        if self.step_mode_button is not None:
            self.step_mode_button.setEnabled(not running)
        if self.continuous_mode_button is not None:
            self.continuous_mode_button.setEnabled(not running)

        if self.step_start_button is not None:
            self.step_start_button.setEnabled(False if running else self.step_start_button.isEnabled())
        if self.continuous_start_button is not None and running:
            self.continuous_start_button.setEnabled(False)

        if self.pause_button is not None:
            self.pause_button.setVisible(running and self.active_mode != "Continuous Scan")
            self.pause_button.setEnabled(running and self.active_mode != "Continuous Scan")
            self.pause_button.setText("Pause")
        if self.abort_button is not None:
            self.abort_button.setVisible(running)
            self.abort_button.setEnabled(running)

    def _stop_main_timer(self):
        timer = getattr(self.host_window, "timer", None)
        self.main_timer_was_active = bool(timer is not None and timer.isActive())
        if self.main_timer_was_active:
            timer.stop()

    def _restore_after_worker(self):
        worker = self.active_worker
        if worker is not None:
            worker.deleteLater()
        self.active_worker = None
        self.host_window.measurement_worker = None
        self.host_window.continuous_measurement_worker = None

        if self.main_timer_was_active:
            timer = getattr(self.host_window, "timer", None)
            modbus = getattr(self.host_window, "modbus", None)
            if timer is not None and modbus is not None and modbus.is_connected:
                timer.start()
        self.main_timer_was_active = False

        self._set_editors_enabled(True)
        self.close_button.setEnabled(True)
        self.rebuild_button.setEnabled(True)
        self.revalidate_button.setEnabled(True)

        if self.step_mode_button is not None:
            self.step_mode_button.setEnabled(True)
        if self.continuous_mode_button is not None:
            self.continuous_mode_button.setEnabled(True)

        if self.pause_button is not None:
            self.pause_button.hide()
            self.pause_button.setEnabled(False)
            self.pause_button.setText("Pause")
        if self.abort_button is not None:
            self.abort_button.hide()
            self.abort_button.setEnabled(False)

        ready = len(self._ready_points())
        state = getattr(self.host_window, "measurement_state_label", None)
        state_text = state.text() if state is not None else ""
        validated = "VALIDATED" in state_text.upper()
        complete = "COMPLETE" in state_text.upper()

        if self.step_start_button is not None:
            self.step_start_button.setEnabled(validated and ready > 0 and not complete)

        self.paused = False
        self.active_mode = None
        self.motion_only = False
        self.refresh_summary()

    def toggle_pause(self):
        worker = self.active_worker
        if worker is None or not worker.isRunning():
            return
        if not hasattr(worker, "request_pause"):
            return
        worker.request_pause(not self.paused)

    def request_abort(self):
        worker = self.active_worker
        if worker is None or not worker.isRunning():
            return
        worker.requestInterruption()
        if hasattr(worker, "request_pause"):
            worker.request_pause(False)
        if self.pause_button is not None:
            self.pause_button.setEnabled(False)
        if self.abort_button is not None:
            self.abort_button.setEnabled(False)
        self.run_status_label.setText(
            "Abort requested — the active servo move is allowed to finish safely; "
            "the run will stop at the next safe checkpoint."
        )

    def _step_estimate_seconds(self, point_count, motion_only=False):
        settle = self.host_window.measurement_settle_spin.value()
        if motion_only:
            return point_count * settle

        samples = self.host_window.measurement_samples_spin.value()
        integration = self.host_window.measurement_integration_spin.value()
        measurement_s = (integration + MEASUREMENT_OVERHEAD_MS) / 1000.0
        inter_sample_s = INTER_SAMPLE_DELAY_MS / 1000.0
        sample_block_s = samples * measurement_s
        if samples > 1:
            sample_block_s += (samples - 1) * inter_sample_s
        return point_count * (settle + sample_block_s)

    def start_step_scan(self):
        problem = self._validated_single_axis_problem()
        if problem:
            QMessageBox.warning(self, "Measurement", problem)
            return

        points = self._ready_points()
        meter = getattr(self.host_window, "luxmeter", None)
        meter_connected = bool(meter is not None and meter.is_connected)

        live_worker = getattr(self.host_window, "luxmeter_live_worker", None)
        if meter_connected and live_worker is not None and live_worker.isRunning():
            QMessageBox.warning(
                self,
                "Measurement",
                "Stop Luxmeter Live acquisition before starting a formal measurement run.",
            )
            return

        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        first = points[0]
        last = points[-1]
        if mode == SCAN_SINGLE_C_GAMMA:
            motion_text = (
                f"C fixed at {first[1]:+.3f}°\n"
                f"Gamma Step Scan: {first[2]:+.3f}° → {last[2]:+.3f}°"
            )
        else:
            motion_text = (
                f"Gamma fixed at {first[2]:+.3f}°\n"
                f"C Step Scan: {first[1]:+.3f}° → {last[1]:+.3f}°"
            )

        commissioning_note = (
            "\n\nLuxmeter is not connected. The run will execute MOTION ONLY; "
            "Lux/Candela will not be recorded."
            if not meter_connected
            else ""
        )

        answer = QMessageBox.question(
            self,
            "Confirm Step Scan",
            f"Start Step Scan of {len(points)} Ready points?\n\n"
            f"{motion_text}\n\n"
            f"Settling: {self.host_window.measurement_settle_spin.value():.1f} s / point\n"
            f"Samples: {self.host_window.measurement_samples_spin.value()} / point\n"
            f"Distance: {self.host_window.measurement_distance_spin.value():.2f} m"
            f"{commissioning_note}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if meter_connected and hasattr(self.host_window, "luxmeter_sensitivity_spin"):
            meter.sensitivity_na_per_lx = (
                self.host_window.luxmeter_sensitivity_spin.value()
            )

        if meter_connected:
            worker = MeasurementRunWorker(
                motion=self.host_window.motion,
                meter=meter,
                scan_mode=mode,
                points=points,
                settle_time_s=self.host_window.measurement_settle_spin.value(),
                samples=self.host_window.measurement_samples_spin.value(),
                integration_ms=self.host_window.measurement_integration_spin.value(),
                apply_measurement_settings=True,
                distance_m=self.host_window.measurement_distance_spin.value(),
                parent=self,
            )
        else:
            worker = CommissioningMotionWorker(
                motion=self.host_window.motion,
                scan_mode=mode,
                points=points,
                settle_time_s=self.host_window.measurement_settle_spin.value(),
                parent=self,
            )

        self.active_worker = worker
        self.host_window.measurement_worker = worker
        self._stop_main_timer()
        self._begin_run(
            mode_text="Step Scan",
            total=len(points),
            estimate_s=self._step_estimate_seconds(
                len(points),
                motion_only=not meter_connected,
            ),
            motion_only=not meter_connected,
        )
        self._set_source_state(
            f"RUNNING  •  0/{len(points)}",
            "measurementStateDraft",
        )

        completed = 0
        point_by_row = {row: (c_deg, gamma_deg) for row, c_deg, gamma_deg in points}

        def on_progress(text):
            self.run_status_label.setText(text)

        def on_point_started(row, sequence, total, c_deg, gamma_deg):
            self.plan_table.setItem(row, 8, _readonly_item("Running"))
            self.plan_table.selectRow(row)
            first_item = self.plan_table.item(row, 0)
            if first_item is not None:
                self.plan_table.scrollToItem(first_item)
            self._set_current_point(sequence, total, c_deg, gamma_deg)
            self._set_live_position(c_deg, gamma_deg)
            self._set_source_state(
                f"RUNNING  •  POINT {sequence}/{total}",
                "measurementStateDraft",
            )

        def on_pause_state(is_paused):
            self.paused = bool(is_paused)
            if self.pause_button is not None:
                self.pause_button.setText("Resume" if self.paused else "Pause")
            if self.paused:
                self.run_status_label.setText(
                    "Measurement paused at a safe checkpoint."
                )

        def on_result(row, current_na, lux, stdev_lux, candela):
            nonlocal completed
            completed += 1
            c_deg, gamma_deg = point_by_row[row]

            self.plan_table.setItem(row, 5, _readonly_item(f"{lux:.3f}"))
            self.plan_table.setItem(row, 6, _readonly_item(f"{candela:.1f}"))
            self.plan_table.setItem(row, 8, _readonly_item("Measured"))
            self._set_photometry(current_na, lux, candela, stdev_lux)
            self._set_live_position(c_deg, gamma_deg)
            self._set_run_completed(completed)

            if hasattr(self.host_window, "luxmeter_current_label"):
                self.host_window.luxmeter_current_label.setText(
                    f"Current: {current_na:.2f} nA"
                )
            if hasattr(self.host_window, "luxmeter_lux_label"):
                self.host_window.luxmeter_lux_label.setText(f"Lux: {lux:.3f} lx")
            if hasattr(self.host_window, "luxmeter_stability_label"):
                self.host_window.luxmeter_stability_label.setText(
                    f"Std. dev.: {stdev_lux:.3f} lx"
                )

            self.host_window.luxmeter_last_current_a = current_na * 1e-9
            self.host_window.luxmeter_last_lux = lux
            self.host_window.measurement_results.append(
                {
                    "point": row + 1,
                    "c_deg": c_deg,
                    "gamma_deg": gamma_deg,
                    "lux": lux,
                    "candela": candela,
                    "stdev_lux": stdev_lux,
                    "mean_current_na": current_na,
                    "distance_m": self.host_window.measurement_distance_spin.value(),
                    "samples": self.host_window.measurement_samples_spin.value(),
                    "integration_ms": meter.integration_time_ms,
                    "execution_mode": "step",
                }
            )

        def on_motion_done(row, sequence, total, c_deg, gamma_deg):
            nonlocal completed
            completed += 1
            self.plan_table.setItem(row, 8, _readonly_item("Motion OK"))
            self._set_current_point(sequence, total, c_deg, gamma_deg)
            self._set_live_position(c_deg, gamma_deg)
            self.run_photometry_label.setText("Motion-only — no Lux acquisition")
            self._set_run_completed(completed)

        def reset_running_row():
            for row, *_ in points:
                item = self.plan_table.item(row, 8)
                if item is not None and item.text() == "Running":
                    self.plan_table.setItem(row, 8, _readonly_item("Ready"))

        def on_aborted(message):
            reset_running_row()
            self._finish_run_monitor(message)
            self._set_source_state(
                f"VALIDATED  •  {completed}/{len(points)} COMPLETE",
                "measurementStateValid",
            )

        def on_failed(message):
            reset_running_row()
            self._finish_run_monitor("Run failed.")
            self._set_source_state("FAILED", "measurementStateInvalid")
            QMessageBox.critical(self, "Measurement Run Error", message)

        def on_completed():
            self.run_finished_normally = True
            self._set_run_completed(len(points))
            if self.motion_only:
                self._finish_run_monitor(
                    "Motion-only commissioning run complete — all requested positions reached."
                )
                self._set_source_state(
                    f"MOTION CHECK COMPLETE  •  {len(points)}/{len(points)}",
                    "measurementStateValid",
                )
            else:
                self._finish_run_monitor("Step Scan complete.")
                self._set_source_state(
                    f"COMPLETE  •  {len(points)}/{len(points)} MEASURED",
                    "measurementStateValid",
                )

        worker.progress.connect(on_progress)
        worker.point_started.connect(on_point_started)
        worker.pause_state.connect(on_pause_state)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.run_completed.connect(on_completed)

        if meter_connected:
            worker.point_result.connect(on_result)
        else:
            worker.point_done.connect(on_motion_done)

        worker.finished.connect(self._restore_after_worker)
        worker.start()

    def _continuous_estimate_seconds(self, points):
        if len(points) <= 1:
            return max(
                0.1,
                self.host_window.measurement_integration_spin.value() / 1000.0,
            )

        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            span = abs(points[-1][2] - points[0][2])
            axis = GAMMA
        else:
            span = abs(points[-1][1] - points[0][1])
            axis = C_AXIS

        motor_rpm = self.host_window.motion.expected_speed_raw(axis) / 10.0
        deg_per_s = motor_rpm * 6.0 / axis.gear_ratio if motor_rpm > 0 else 0.0
        sweep_s = span / deg_per_s if deg_per_s > 0 else 0.0
        return sweep_s + max(
            0.2,
            self.host_window.measurement_integration_spin.value() / 1000.0,
        )

    def start_continuous_scan(self):
        problem = self._validated_single_axis_problem()
        if problem:
            QMessageBox.warning(self, "Continuous Scan", problem)
            return

        meter = getattr(self.host_window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            QMessageBox.warning(
                self,
                "Continuous Scan",
                "Continuous Scan requires the Luxmeter because target-point "
                "measurements are captured while the axis is moving. "
                "Use Step Scan for motion-only commissioning.",
            )
            return

        live_worker = getattr(self.host_window, "luxmeter_live_worker", None)
        if live_worker is not None and live_worker.isRunning():
            QMessageBox.warning(
                self,
                "Continuous Scan",
                "Stop Luxmeter Live acquisition before starting Continuous Scan.",
            )
            return

        points = self._ready_points()
        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        first = points[0]
        last = points[-1]

        if mode == SCAN_SINGLE_C_GAMMA:
            motion_text = (
                f"C fixed at {first[1]:+.3f}°\n"
                f"Gamma continuous sweep: {first[2]:+.3f}° → {last[2]:+.3f}°"
            )
        else:
            motion_text = (
                f"Gamma fixed at {first[2]:+.3f}°\n"
                f"C continuous sweep: {first[1]:+.3f}° → {last[1]:+.3f}°"
            )

        answer = QMessageBox.question(
            self,
            "Confirm Continuous Scan",
            f"Start Continuous Scan of {len(points)} Ready points?\n\n"
            f"{motion_text}\n\n"
            f"Integration: {self.host_window.measurement_integration_spin.value()} ms\n"
            f"Distance: {self.host_window.measurement_distance_spin.value():.2f} m\n\n"
            "The sweep axis will not stop at intermediate target angles.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if hasattr(self.host_window, "luxmeter_sensitivity_spin"):
            meter.sensitivity_na_per_lx = (
                self.host_window.luxmeter_sensitivity_spin.value()
            )

        worker = ContinuousMeasurementWorker(
            motion=self.host_window.motion,
            meter=meter,
            scan_mode=mode,
            points=points,
            integration_ms=self.host_window.measurement_integration_spin.value(),
            apply_measurement_settings=True,
            distance_m=self.host_window.measurement_distance_spin.value(),
            parent=self,
        )

        self.active_worker = worker
        self.host_window.continuous_measurement_worker = worker
        self._stop_main_timer()
        self._begin_run(
            mode_text="Continuous Scan",
            total=len(points),
            estimate_s=self._continuous_estimate_seconds(points),
            motion_only=False,
        )
        self._set_source_state(
            f"CONTINUOUS  •  0/{len(points)} MEASURED",
            "measurementStateDraft",
        )

        completed = 0

        def on_progress(text):
            self.run_status_label.setText(text)

        def on_angles(c_deg, gamma_deg):
            self._set_live_position(c_deg, gamma_deg)

        def on_result(
            row,
            sequence,
            total,
            c_deg,
            gamma_deg,
            current_na,
            lux,
            stdev,
            candela,
        ):
            nonlocal completed
            completed += 1
            self.plan_table.setItem(row, 5, _readonly_item(f"{lux:.3f}"))
            self.plan_table.setItem(row, 6, _readonly_item(f"{candela:.1f}"))
            self.plan_table.setItem(row, 8, _readonly_item("Measured"))
            self.plan_table.selectRow(row)
            first_item = self.plan_table.item(row, 0)
            if first_item is not None:
                self.plan_table.scrollToItem(first_item)

            self._set_current_point(sequence, total, c_deg, gamma_deg)
            self._set_live_position(c_deg, gamma_deg)
            self._set_photometry(current_na, lux, candela)
            self._set_run_completed(completed)

            self.host_window.luxmeter_last_current_a = current_na * 1e-9
            self.host_window.luxmeter_last_lux = lux
            if hasattr(self.host_window, "luxmeter_current_label"):
                self.host_window.luxmeter_current_label.setText(
                    f"Current: {current_na:.2f} nA"
                )
            if hasattr(self.host_window, "luxmeter_lux_label"):
                self.host_window.luxmeter_lux_label.setText(f"Lux: {lux:.3f} lx")
            if hasattr(self.host_window, "luxmeter_stability_label"):
                self.host_window.luxmeter_stability_label.setText(
                    "Std. dev.: — (continuous)"
                )

            self.host_window.measurement_results.append(
                {
                    "point": row + 1,
                    "c_deg": c_deg,
                    "gamma_deg": gamma_deg,
                    "lux": lux,
                    "candela": candela,
                    "stdev_lux": stdev,
                    "mean_current_na": current_na,
                    "distance_m": self.host_window.measurement_distance_spin.value(),
                    "samples": 1,
                    "integration_ms": meter.integration_time_ms,
                    "execution_mode": "continuous",
                }
            )
            self._set_source_state(
                f"CONTINUOUS  •  {completed}/{total} MEASURED",
                "measurementStateDraft",
            )

        def on_completed():
            self.run_finished_normally = True
            self._set_run_completed(len(points))
            self._finish_run_monitor("Continuous Scan complete.")
            self._set_source_state(
                f"COMPLETE  •  {len(points)}/{len(points)} MEASURED",
                "measurementStateValid",
            )

        def on_aborted(message):
            self._finish_run_monitor(message)
            self._set_source_state(
                f"VALIDATED  •  {completed}/{len(points)} MEASURED",
                "measurementStateValid",
            )

        def on_failed(message):
            self._finish_run_monitor("Continuous Scan failed.")
            self._set_source_state("FAILED", "measurementStateInvalid")
            QMessageBox.critical(self, "Continuous Scan Error", message)

        worker.progress.connect(on_progress)
        worker.angle_update.connect(on_angles)
        worker.point_result.connect(on_result)
        worker.run_completed.connect(on_completed)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.finished.connect(self._restore_after_worker)
        worker.start()

    def _measurement_is_running(self):
        return bool(self.active_worker is not None and self.active_worker.isRunning())

    def closeEvent(self, event):
        if self._measurement_is_running():
            QMessageBox.warning(
                self,
                "Measurement Running",
                "The Test Plan Workspace stays open while a measurement is running. "
                "Pause or abort the run before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def _detach_plan_header(root, plan_table, page):
    """Remove the old preview header and return its useful widgets."""

    table_index = root.indexOf(plan_table)
    if table_index <= 0:
        raise RuntimeError("Could not locate the Test Plan header in Measurement layout.")

    header_item = root.takeAt(table_index - 1)
    header_layout = header_item.layout()
    if header_layout is None:
        raise RuntimeError("Measurement Test Plan header layout is not available.")

    widgets = []
    while header_layout.count():
        item = header_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(page)
            widgets.append(widget)

    header_layout.deleteLater()
    return widgets


def attach_test_plan_workspace(window):
    """Replace the embedded plan table with a compact summary + Open button."""

    if getattr(window, "test_plan_workspace", None) is not None:
        return

    page = getattr(window, "measurement_workspace", None)
    plan_table = getattr(window, "measurement_plan_table", None)
    build_button = getattr(window, "measurement_build_plan_button", None)
    validate_button = getattr(window, "measurement_validate_plan_button", None)
    start_button = getattr(window, "measurement_start_button", None)

    if any(
        item is None
        for item in (page, plan_table, build_button, validate_button, start_button)
    ):
        raise RuntimeError("Measurement workspace is incomplete.")

    root = page.layout()
    if root is None:
        raise RuntimeError("Measurement workspace layout is unavailable.")

    execution_box = start_button.parentWidget()
    if execution_box is None:
        raise RuntimeError("Measurement execution controls are unavailable.")

    header_widgets = _detach_plan_header(root, plan_table, page)
    old_plan_title = next(
        (
            widget
            for widget in header_widgets
            if isinstance(widget, QLabel)
            and widget.text().strip() == "Test Plan Preview"
        ),
        None,
    )
    if old_plan_title is not None:
        old_plan_title.hide()

    plan_summary = getattr(window, "measurement_plan_summary_label", None)
    if plan_summary is None:
        raise RuntimeError("Measurement plan summary label is unavailable.")

    root.removeWidget(plan_table)
    root.removeWidget(execution_box)

    summary_box = QGroupBox("Test Plan")
    summary_box.setObjectName("measurementPlanSummaryBox")
    summary_layout = QHBoxLayout(summary_box)
    summary_layout.setContentsMargins(12, 10, 12, 10)
    summary_layout.setSpacing(10)

    text_block = QVBoxLayout()
    text_block.setSpacing(3)

    plan_summary.setParent(summary_box)
    plan_summary.setStyleSheet("color: #A9C4D5; padding: 0px;")
    text_block.addWidget(plan_summary)

    helper = QLabel(
        "Review the full point table in the maximized workspace. "
        "The same plan is used for execution and live result updates."
    )
    helper.setObjectName("measurementEngineNote")
    helper.setWordWrap(True)
    text_block.addWidget(helper)
    summary_layout.addLayout(text_block, 1)

    build_button.setParent(summary_box)
    validate_button.setParent(summary_box)
    open_button = QPushButton("Open Test Plan")
    open_button.setObjectName("openTestPlanButton")

    summary_layout.addWidget(build_button)
    summary_layout.addWidget(validate_button)
    summary_layout.addWidget(open_button)

    root.addWidget(summary_box, 0)
    root.addStretch(1)

    workspace = TestPlanWorkspace(
        host_window=window,
        plan_table=plan_table,
        execution_box=execution_box,
        build_button=build_button,
        validate_button=validate_button,
    )
    open_button.clicked.connect(workspace.open_maximized)

    window.test_plan_workspace = workspace
    window.measurement_plan_summary_box = summary_box
    window.measurement_open_test_plan_button = open_button
