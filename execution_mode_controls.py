"""Execution-mode controls for the Lumigon Measurement workspace.

Step Scan remains the existing stop/settle/average workflow.  Continuous Scan
adds a smooth single-axis fly sweep that samples Lux as requested angular points
are crossed.  This module is attached after the Measurement workspace is built,
so the proven Step Scan implementation remains untouched.
"""

import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from continuous_measurement import ContinuousMeasurementWorker


SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
SCAN_GRID = 2


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


def _table_angle(item):
    if item is None:
        raise ValueError("Missing angle in Test Plan.")
    return float(item.text().replace("°", "").strip())


class ContinuousProgressDialog(QDialog):
    def __init__(self, total_points, estimate_s, parent=None):
        super().__init__(parent)
        self.total_points = max(1, int(total_points))
        self.estimate_s = max(0.0, float(estimate_s))
        self.completed = 0
        self.started_at = time.monotonic()

        self.setWindowTitle("Lumigon — Continuous Scan")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Continuous Scan in Progress")
        title.setObjectName("continuousRunTitle")
        root.addWidget(title)

        self.status = QLabel("Preparing continuous sweep…")
        self.status.setWordWrap(True)
        self.status.setObjectName("continuousRunStatus")
        root.addWidget(self.status)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        self.point_label = QLabel("—")
        self.angle_label = QLabel("—")
        self.completed_label = QLabel("0")
        self.remaining_label = QLabel(str(self.total_points))
        self.elapsed_label = QLabel("0 s")
        self.eta_label = QLabel(_format_duration(self.estimate_s))

        grid.addWidget(QLabel("Current point:"), 0, 0)
        grid.addWidget(self.point_label, 0, 1)
        grid.addWidget(QLabel("Live angle:"), 1, 0)
        grid.addWidget(self.angle_label, 1, 1)
        grid.addWidget(QLabel("Completed:"), 2, 0)
        grid.addWidget(self.completed_label, 2, 1)
        grid.addWidget(QLabel("Remaining:"), 3, 0)
        grid.addWidget(self.remaining_label, 3, 1)
        grid.addWidget(QLabel("Elapsed:"), 4, 0)
        grid.addWidget(self.elapsed_label, 4, 1)
        grid.addWidget(QLabel("Estimated remaining:"), 5, 0)
        grid.addWidget(self.eta_label, 5, 1)
        root.addLayout(grid)

        self.progress = QProgressBar()
        self.progress.setRange(0, self.total_points)
        self.progress.setValue(0)
        self.progress.setFormat("%v / %m points   •   %p%")
        root.addWidget(self.progress)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.abort_button = QPushButton("Abort")
        controls.addWidget(self.abort_button)
        root.addLayout(controls)

        self.clock = QTimer(self)
        self.clock.setInterval(500)
        self.clock.timeout.connect(self._refresh_time)
        self.clock.start()

        self.setStyleSheet(
            """
            QDialog {
                background-color: #101820;
                color: #E8EEF3;
            }
            QLabel#continuousRunTitle {
                color: #4DA3FF;
                font-size: 16pt;
                font-weight: 700;
            }
            QLabel#continuousRunStatus {
                color: #C7D7E2;
                background-color: #17232D;
                border: 1px solid #34495E;
                border-radius: 6px;
                padding: 10px;
            }
            QProgressBar {
                border: 1px solid #34495E;
                border-radius: 5px;
                background-color: #111B23;
                text-align: center;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background-color: #1769AA;
                border-radius: 4px;
            }
            """
        )

    def _refresh_time(self):
        elapsed = max(0.0, time.monotonic() - self.started_at)
        self.elapsed_label.setText(_format_duration(elapsed))
        remaining = max(0, self.total_points - self.completed)
        if self.completed > 0:
            eta = (elapsed / self.completed) * remaining
        else:
            eta = max(0.0, self.estimate_s - elapsed)
        self.eta_label.setText(_format_duration(eta))

    def set_angles(self, c_deg, gamma_deg):
        self.angle_label.setText(f"C {c_deg:+.3f}°   •   Gamma {gamma_deg:+.3f}°")

    def set_point(self, sequence):
        self.point_label.setText(f"{sequence} / {self.total_points}")

    def set_completed(self, completed):
        self.completed = max(0, min(int(completed), self.total_points))
        self.completed_label.setText(str(self.completed))
        self.remaining_label.setText(str(max(0, self.total_points - self.completed)))
        self.progress.setValue(self.completed)
        self._refresh_time()

    def finish(self, text):
        self.clock.stop()
        self.status.setText(text)
        self.abort_button.setEnabled(False)


def attach_execution_mode_controls(window):
    """Add Step/Continuous toggle without disturbing the proven Step engine."""

    page = getattr(window, "measurement_workspace", None)
    original_start = getattr(window, "measurement_start_button", None)
    if page is None or page.layout() is None or original_start is None:
        raise RuntimeError("Measurement workspace is not available.")

    root = page.layout()

    mode_box = QGroupBox("Execution Mode")
    mode_layout = QHBoxLayout(mode_box)
    mode_layout.setContentsMargins(10, 8, 10, 8)
    mode_layout.setSpacing(8)

    mode_label = QLabel("Measurement motion:")
    step_button = QPushButton("Step Scan")
    continuous_button = QPushButton("Continuous Scan")
    step_button.setCheckable(True)
    continuous_button.setCheckable(True)

    group = QButtonGroup(mode_box)
    group.setExclusive(True)
    group.addButton(step_button, 0)
    group.addButton(continuous_button, 1)
    step_button.setChecked(True)

    hint = QLabel("Stop → settle → average at every point")
    hint.setObjectName("measurementEngineNote")
    hint.setWordWrap(True)

    mode_layout.addWidget(mode_label)
    mode_layout.addWidget(step_button)
    mode_layout.addWidget(continuous_button)
    mode_layout.addWidget(hint, 1)

    # Title row and three setup cards are the first two entries. Place the mode
    # selector immediately below them and above Test Plan Preview.
    root.insertWidget(2, mode_box)

    continuous_start = QPushButton("Start Continuous Scan")
    continuous_start.setVisible(False)
    continuous_start.setEnabled(False)

    execution_parent = original_start.parentWidget()
    execution_layout = execution_parent.layout() if execution_parent is not None else None
    if execution_layout is None:
        raise RuntimeError("Measurement execution controls are not available.")

    start_index = -1
    for index in range(execution_layout.count()):
        if execution_layout.itemAt(index).widget() is original_start:
            start_index = index
            break
    if start_index < 0:
        raise RuntimeError("Could not locate the Step Scan start button.")
    execution_layout.insertWidget(start_index + 1, continuous_start)

    running = False
    active_worker = None
    active_dialog = None
    main_timer_was_active = False

    editor_names = (
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

    def set_editors_enabled(enabled):
        for name in editor_names:
            control = getattr(window, name, None)
            if control is not None:
                control.setEnabled(enabled)

        # Restore fixed-axis behavior after a run.
        if enabled:
            scan_mode = window.measurement_scan_mode_combo.currentIndex()
            if scan_mode == SCAN_SINGLE_C_GAMMA:
                window.measurement_c_end.setEnabled(False)
                window.measurement_c_step.setEnabled(False)
            elif scan_mode == SCAN_SINGLE_GAMMA_C:
                window.measurement_gamma_end.setEnabled(False)
                window.measurement_gamma_step.setEnabled(False)

    def refresh_mode_ui(*_args):
        if running:
            return
        continuous = continuous_button.isChecked()
        original_start.setVisible(not continuous)
        continuous_start.setVisible(continuous)

        settle = getattr(window, "measurement_settle_spin", None)
        samples = getattr(window, "measurement_samples_spin", None)
        if settle is not None:
            settle.setEnabled(not continuous)
        if samples is not None:
            samples.setEnabled(not continuous)

        if continuous:
            hint.setText(
                "Fly scan: one smooth sweep; T0 Lux is sampled as each target angle is crossed."
            )
        else:
            hint.setText("Stop → settle → average at every point")

    def sync_continuous_enabled():
        if running:
            continuous_start.setEnabled(False)
            return
        mode_ok = window.measurement_scan_mode_combo.currentIndex() != SCAN_GRID
        continuous_start.setEnabled(
            continuous_button.isChecked() and original_start.isEnabled() and mode_ok
        )

    sync_timer = QTimer(page)
    sync_timer.setInterval(150)
    sync_timer.timeout.connect(sync_continuous_enabled)
    sync_timer.start()

    def prerequisites():
        if not original_start.isEnabled():
            return "Build and Validate the Test Plan before starting Continuous Scan."
        if window.measurement_scan_mode_combo.currentIndex() == SCAN_GRID:
            return "Continuous Scan currently supports single-axis scans only."

        modbus = getattr(window, "modbus", None)
        if modbus is None or not modbus.is_connected:
            return "Connect the servo drives before measuring."

        motion = getattr(window, "motion", None)
        if motion is None or motion.gamma_zero_puu is None or motion.c_zero_puu is None:
            return "Capture a valid Session Zero for both axes before measuring."

        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            return "Connect the Luxmeter before measuring."

        live_worker = getattr(window, "luxmeter_live_worker", None)
        if live_worker is not None and live_worker.isRunning():
            return "Stop Luxmeter Live acquisition before starting Continuous Scan."

        return None

    def ready_points():
        table = window.measurement_plan_table
        points = []
        for row in range(table.rowCount()):
            status = table.item(row, 8)
            if status is None or status.text() != "Ready":
                continue
            c_deg = _table_angle(table.item(row, 1))
            gamma_deg = _table_angle(table.item(row, 2))
            points.append((row, c_deg, gamma_deg))
        return points

    def estimate_seconds(points):
        if len(points) <= 1:
            return max(0.1, window.measurement_integration_spin.value() / 1000.0)

        mode = window.measurement_scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            axis = window.motion.__class__.__module__  # only to keep this block side-effect free
            span = abs(points[-1][2] - points[0][2])
            motor_rpm = window.motion.expected_speed_raw(__import__("motion_controller").GAMMA) / 10.0
            gear = __import__("motion_controller").GAMMA.gear_ratio
        else:
            span = abs(points[-1][1] - points[0][1])
            motor_rpm = window.motion.expected_speed_raw(__import__("motion_controller").C_AXIS) / 10.0
            gear = __import__("motion_controller").C_AXIS.gear_ratio

        deg_per_s = motor_rpm * 6.0 / gear if motor_rpm > 0 else 0.0
        sweep_s = span / deg_per_s if deg_per_s > 0 else 0.0
        return sweep_s + max(0.2, window.measurement_integration_spin.value() / 1000.0)

    def restore_ui():
        nonlocal running, active_worker, active_dialog, main_timer_was_active
        worker = active_worker
        if worker is not None:
            worker.deleteLater()
        active_worker = None
        window.continuous_measurement_worker = None
        running = False

        if main_timer_was_active:
            timer = getattr(window, "timer", None)
            modbus = getattr(window, "modbus", None)
            if timer is not None and modbus is not None and modbus.is_connected:
                timer.start()
        main_timer_was_active = False

        set_editors_enabled(True)
        step_button.setEnabled(True)
        continuous_button.setEnabled(True)
        refresh_mode_ui()
        sync_continuous_enabled()

        if active_dialog is not None:
            QTimer.singleShot(900, active_dialog.accept)
        active_dialog = None

    def start_continuous():
        nonlocal running, active_worker, active_dialog, main_timer_was_active

        problem = prerequisites()
        if problem:
            QMessageBox.warning(window, "Continuous Scan", problem)
            return

        points = ready_points()
        if not points:
            QMessageBox.warning(window, "Continuous Scan", "No Ready points remain in the plan.")
            return

        mode = window.measurement_scan_mode_combo.currentIndex()
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
            window,
            "Confirm Continuous Scan",
            f"Start Continuous Scan of {len(points)} Ready points?\n\n"
            f"{motion_text}\n\n"
            f"Integration: {window.measurement_integration_spin.value()} ms\n"
            f"Distance: {window.measurement_distance_spin.value():.2f} m\n\n"
            "The sweep axis will NOT stop at intermediate points. Lux is sampled "
            "while moving and assigned when each target angle is crossed.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        meter = window.luxmeter
        if hasattr(window, "luxmeter_sensitivity_spin"):
            meter.sensitivity_na_per_lx = window.luxmeter_sensitivity_spin.value()

        worker = ContinuousMeasurementWorker(
            motion=window.motion,
            meter=meter,
            scan_mode=mode,
            points=points,
            integration_ms=window.measurement_integration_spin.value(),
            apply_measurement_settings=True,
            distance_m=window.measurement_distance_spin.value(),
            parent=window,
        )
        dialog = ContinuousProgressDialog(
            len(points),
            estimate_seconds(points),
            parent=window,
        )

        running = True
        active_worker = worker
        active_dialog = dialog
        window.continuous_measurement_worker = worker

        timer = getattr(window, "timer", None)
        main_timer_was_active = bool(timer is not None and timer.isActive())
        if main_timer_was_active:
            timer.stop()

        set_editors_enabled(False)
        step_button.setEnabled(False)
        continuous_button.setEnabled(False)
        continuous_start.setEnabled(False)

        state = getattr(window, "measurement_state_label", None)
        if state is not None:
            state.setText(f"CONTINUOUS  •  0/{len(points)} MEASURED")

        completed = 0
        aborted = False

        def on_progress(text):
            dialog.status.setText(text)

        def on_angles(c_deg, gamma_deg):
            dialog.set_angles(c_deg, gamma_deg)

        def on_result(row, sequence, total, c_deg, gamma_deg, current_na, lux, stdev, candela):
            nonlocal completed
            completed += 1
            table = window.measurement_plan_table
            table.setItem(row, 5, table.item(row, 5).__class__(f"{lux:.3f}"))
            table.setItem(row, 6, table.item(row, 6).__class__(f"{candela:.1f}"))
            table.setItem(row, 8, table.item(row, 8).__class__("Measured"))
            table.selectRow(row)
            dialog.set_point(sequence)
            dialog.set_completed(completed)
            dialog.set_angles(c_deg, gamma_deg)

            window.luxmeter_last_current_a = current_na * 1e-9
            window.luxmeter_last_lux = lux
            if hasattr(window, "luxmeter_current_label"):
                window.luxmeter_current_label.setText(f"Current: {current_na:.2f} nA")
            if hasattr(window, "luxmeter_lux_label"):
                window.luxmeter_lux_label.setText(f"Lux: {lux:.3f} lx")
            if hasattr(window, "luxmeter_stability_label"):
                window.luxmeter_stability_label.setText("Std. dev.: — (continuous)")

            window.measurement_results.append({
                "point": row + 1,
                "c_deg": c_deg,
                "gamma_deg": gamma_deg,
                "lux": lux,
                "candela": candela,
                "stdev_lux": stdev,
                "mean_current_na": current_na,
                "distance_m": window.measurement_distance_spin.value(),
                "samples": 1,
                "integration_ms": meter.integration_time_ms,
                "execution_mode": "continuous",
            })

            if state is not None:
                state.setText(f"CONTINUOUS  •  {completed}/{total} MEASURED")

        def request_abort():
            if active_worker is None or not active_worker.isRunning():
                return
            active_worker.requestInterruption()
            dialog.abort_button.setEnabled(False)
            dialog.status.setText(
                "Abort requested — the active sweep will finish safely; remaining "
                "measurements will be skipped."
            )

        def on_completed():
            dialog.set_completed(len(points))
            dialog.finish("Continuous Scan complete.")
            if state is not None:
                state.setText(f"COMPLETE  •  {len(points)}/{len(points)} MEASURED")
            original_start.setEnabled(False)

        def on_aborted(message):
            nonlocal aborted
            aborted = True
            dialog.finish(message)
            if state is not None:
                state.setText(f"VALIDATED  •  {completed}/{len(points)} MEASURED")

        def on_failed(message):
            dialog.finish("Continuous Scan failed.")
            QMessageBox.critical(window, "Continuous Scan Error", message)
            if state is not None:
                state.setText(f"VALIDATED  •  {completed}/{len(points)} MEASURED")

        worker.progress.connect(on_progress)
        worker.angle_update.connect(on_angles)
        worker.point_result.connect(on_result)
        worker.run_completed.connect(on_completed)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.finished.connect(restore_ui)
        dialog.abort_button.clicked.connect(request_abort)

        dialog.show()
        worker.start()

    step_button.clicked.connect(refresh_mode_ui)
    continuous_button.clicked.connect(refresh_mode_ui)
    continuous_start.clicked.connect(start_continuous)

    refresh_mode_ui()
    sync_continuous_enabled()

    window.measurement_execution_mode_group = group
    window.measurement_step_mode_button = step_button
    window.measurement_continuous_mode_button = continuous_button
    window.measurement_continuous_start_button = continuous_start
    window.measurement_execution_mode_box = mode_box
