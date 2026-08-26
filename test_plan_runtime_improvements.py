"""Runtime refinements for Lumigon Test Plan execution.

Keeps the existing Measurement engines intact while adding operator-facing run
controls, nearest-endpoint sweep selection, fixed-axis auto-positioning, a
single countdown ETA, and automatic return to Session Home (0°, 0°) after a
normally completed test.
"""

import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton

from continuous_measurement import ContinuousMeasurementWorker
from measurement_execution import MeasurementRunWorker
from motion_controller import C_AXIS, GAMMA
from test_plan_workspace import (
    CommissioningMotionWorker,
    SCAN_SINGLE_C_GAMMA,
    SCAN_SINGLE_GAMMA_C,
    TestPlanWorkspace,
    FIXED_AXIS_TOLERANCE_DEG,
    INTER_SAMPLE_DELAY_MS,
    MEASUREMENT_OVERHEAD_MS,
    _format_duration,
)


class ReturnHomeWorker(QThread):
    """Return both axes to Session Home without blocking the HMI thread."""

    progress = Signal(str)
    home_completed = Signal()
    failed = Signal(str)

    def __init__(self, motion, parent=None):
        super().__init__(parent)
        self.motion = motion

    def run(self):
        try:
            # Return C first and Gamma last so the final commanded orientation is
            # Gamma = 0° after any mechanical coupling during the C return.
            self.progress.emit("Test complete — returning C axis to Home (0.000°)…")
            self.motion.return_to_zero(C_AXIS)
            self.progress.emit("Returning Gamma axis to Home (0.000°)…")
            self.motion.return_to_zero(GAMMA)

            c_actual = self.motion.get_current_angle(C_AXIS)
            gamma_actual = self.motion.get_current_angle(GAMMA)
            self.progress.emit(
                f"Home reached: C {c_actual:+.3f}°  •  Gamma {gamma_actual:+.3f}°"
            )
            self.home_completed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


def _auto_position_fixed_axis(self, axis, target):
    """Move the nominally fixed axis to its requested target when necessary."""

    actual = self.motion.get_current_angle(axis)
    error = actual - target
    if abs(error) <= FIXED_AXIS_TOLERANCE_DEG:
        return

    progress = getattr(self, "progress", None)
    if progress is not None:
        progress.emit(
            f"Positioning fixed {axis.name} axis: {actual:+.3f}° → {target:+.3f}°"
        )

    self.motion.move_absolute(axis, target)
    actual = self.motion.get_current_angle(axis)
    error = actual - target
    if abs(error) > FIXED_AXIS_TOLERANCE_DEG:
        raise RuntimeError(
            f"{axis.name} fixed-axis positioning failed. Target {target:+.3f}°, "
            f"actual {actual:+.3f}° (error {error:+.3f}°)."
        )


def _axis_motion_seconds(motion, axis, delta_deg):
    motor_rpm = motion.expected_speed_raw(axis) / 10.0
    if motor_rpm <= 0.0:
        return 0.0
    output_deg_per_second = motor_rpm * 6.0 / axis.gear_ratio
    if output_deg_per_second <= 0.0:
        return 0.0
    return abs(float(delta_deg)) / output_deg_per_second


def install_test_plan_runtime_improvements():
    """Install the v0.3 Test Plan run refinements before the workspace is built."""

    if getattr(TestPlanWorkspace, "_runtime_improvements_installed", False):
        return
    TestPlanWorkspace._runtime_improvements_installed = True

    # The fixed axis should not be an operator prerequisite. If it is not already
    # at the requested fixed angle, position it automatically before acquisition.
    MeasurementRunWorker._verify_fixed_axis = _auto_position_fixed_axis
    ContinuousMeasurementWorker._verify_fixed_axis = _auto_position_fixed_axis
    CommissioningMotionWorker._verify_fixed_axis = _auto_position_fixed_axis

    original_init = TestPlanWorkspace.__init__
    original_ready_points = TestPlanWorkspace._ready_points
    original_begin_run = TestPlanWorkspace._begin_run
    original_set_running_controls = TestPlanWorkspace._set_running_controls
    original_restore_after_worker = TestPlanWorkspace._restore_after_worker

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        # Dedicated run controls live inside the Live Measurement Run panel. The
        # legacy Execution-box Pause/Abort controls remain hidden, so the operator
        # always sees Pause + Stop in the same place as live progress.
        controls = QHBoxLayout()
        controls.addStretch(1)
        self.run_pause_button = QPushButton("Pause")
        self.run_stop_button = QPushButton("Stop")
        self.run_pause_button.setToolTip("Pause at the next safe checkpoint")
        self.run_stop_button.setToolTip(
            "Stop safely; an active servo move is allowed to finish before the run ends"
        )
        self.run_pause_button.clicked.connect(self.toggle_pause)
        self.run_stop_button.clicked.connect(self.request_abort)
        controls.addWidget(self.run_pause_button)
        controls.addWidget(self.run_stop_button)
        self.run_box.layout().addLayout(controls)
        self.run_pause_button.hide()
        self.run_stop_button.hide()

        self._home_return_in_progress = False
        self._home_return_failed = None
        self._eta_remaining_s = 0.0
        self._eta_last_tick = 0.0

    def patched_ready_points(self):
        points = original_ready_points(self)
        if len(points) <= 1:
            return points

        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            axis = GAMMA
            value_index = 2
        elif mode == SCAN_SINGLE_GAMMA_C:
            axis = C_AXIS
            value_index = 1
        else:
            return points

        motion = getattr(self.host_window, "motion", None)
        modbus = getattr(self.host_window, "modbus", None)
        if (
            motion is None
            or modbus is None
            or not modbus.is_connected
            or motion.gamma_zero_puu is None
            or motion.c_zero_puu is None
        ):
            return points

        try:
            current = motion.get_current_angle(axis)
        except Exception:
            return points

        first_target = points[0][value_index]
        last_target = points[-1][value_index]

        # Preserve the defined direction on an exact tie; otherwise approach the
        # physically closest endpoint and scan from there.
        if abs(current - last_target) + 1e-9 < abs(current - first_target):
            return list(reversed(points))
        return points

    def patched_begin_run(self, *, mode_text, total, estimate_s, motion_only):
        original_begin_run(
            self,
            mode_text=mode_text,
            total=total,
            estimate_s=estimate_s,
            motion_only=motion_only,
        )
        self._eta_remaining_s = max(0.0, float(estimate_s))
        self._eta_last_tick = time.monotonic()

    def patched_refresh_run_clock(self):
        if self.run_started_at <= 0:
            return

        now = time.monotonic()
        elapsed = max(0.0, now - self.run_started_at)
        last_tick = self._eta_last_tick or now
        delta = max(0.0, now - last_tick)
        self._eta_last_tick = now

        # One estimate is calculated at run start. From then on ETA is a simple
        # countdown; point completion times do not cause the value to jump.
        if not self.paused:
            self._eta_remaining_s = max(0.0, self._eta_remaining_s - delta)

        self.run_elapsed_label.setText(_format_duration(elapsed))
        self.run_eta_label.setText(_format_duration(self._eta_remaining_s))

    def patched_set_running_controls(self, running):
        original_set_running_controls(self, running)

        # Keep the old Execution-box controls hidden. The dedicated controls in
        # the Live Measurement Run panel are the only operator run controls.
        if self.pause_button is not None:
            self.pause_button.hide()
        if self.abort_button is not None:
            self.abort_button.hide()

        if not hasattr(self, "run_pause_button"):
            return

        can_pause = bool(running and self.active_mode != "Continuous Scan")
        self.run_pause_button.setVisible(can_pause)
        self.run_pause_button.setEnabled(can_pause)
        self.run_pause_button.setText("Resume" if self.paused else "Pause")

        self.run_stop_button.setVisible(bool(running))
        self.run_stop_button.setEnabled(bool(running))

    def patched_toggle_pause(self):
        worker = self.active_worker
        if worker is None or not worker.isRunning() or not hasattr(worker, "request_pause"):
            return
        worker.request_pause(not self.paused)

    def patched_request_abort(self):
        worker = self.active_worker
        if worker is None or not worker.isRunning():
            return
        worker.requestInterruption()
        if hasattr(worker, "request_pause"):
            worker.request_pause(False)

        if hasattr(self, "run_pause_button"):
            self.run_pause_button.setEnabled(False)
        if hasattr(self, "run_stop_button"):
            self.run_stop_button.setEnabled(False)

        # Keep legacy controls disabled too, even though they are hidden.
        if self.pause_button is not None:
            self.pause_button.setEnabled(False)
        if self.abort_button is not None:
            self.abort_button.setEnabled(False)

        self.run_status_label.setText(
            "Stop requested — the active servo move is allowed to finish safely; "
            "the run will stop at the next safe checkpoint."
        )

    def _motion_plan(self, points):
        if not points:
            return 0.0

        motion = self.host_window.motion
        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            fixed_axis = C_AXIS
            fixed_target = points[0][1]
            sweep_axis = GAMMA
            targets = [p[2] for p in points]
        else:
            fixed_axis = GAMMA
            fixed_target = points[0][2]
            sweep_axis = C_AXIS
            targets = [p[1] for p in points]

        try:
            current_fixed = motion.get_current_angle(fixed_axis)
            current_sweep = motion.get_current_angle(sweep_axis)
        except Exception:
            return 0.0

        seconds = _axis_motion_seconds(
            motion,
            fixed_axis,
            fixed_target - current_fixed,
        )
        seconds += _axis_motion_seconds(
            motion,
            sweep_axis,
            targets[0] - current_sweep,
        )
        for previous, current in zip(targets, targets[1:]):
            seconds += _axis_motion_seconds(motion, sweep_axis, current - previous)

        # Include the automatic post-test return to Session Home.
        seconds += _axis_motion_seconds(motion, sweep_axis, -targets[-1])
        seconds += _axis_motion_seconds(motion, fixed_axis, -fixed_target)
        return seconds

    def patched_step_estimate_seconds(self, point_count, motion_only=False):
        points = self._ready_points()
        settle = self.host_window.measurement_settle_spin.value()
        total = point_count * settle

        if not motion_only:
            samples = self.host_window.measurement_samples_spin.value()
            integration = self.host_window.measurement_integration_spin.value()
            measurement_s = (integration + MEASUREMENT_OVERHEAD_MS) / 1000.0
            sample_block_s = samples * measurement_s
            if samples > 1:
                sample_block_s += (samples - 1) * (INTER_SAMPLE_DELAY_MS / 1000.0)
            total += point_count * sample_block_s

        total += _motion_plan(self, points)
        return total

    def patched_continuous_estimate_seconds(self, points):
        if not points:
            return 0.0

        # _motion_plan includes endpoint approach, sweep travel and Home return.
        total = _motion_plan(self, points)
        total += max(
            0.2,
            self.host_window.measurement_integration_spin.value() / 1000.0,
        )
        return total

    def patched_restore_after_worker(self):
        # A normally completed test is not considered finished until both axes
        # are back at Session Home. Do this in a worker so the HMI stays responsive.
        if self.run_finished_normally and not self._home_return_in_progress:
            finished_worker = self.active_worker
            if finished_worker is not None:
                finished_worker.deleteLater()

            self.host_window.measurement_worker = None
            self.host_window.continuous_measurement_worker = None

            self._home_return_in_progress = True
            self.run_status_label.setText(
                "Test complete — returning both axes to Home (C 0.000°, Gamma 0.000°)…"
            )
            if hasattr(self, "run_pause_button"):
                self.run_pause_button.hide()
            if hasattr(self, "run_stop_button"):
                self.run_stop_button.hide()

            home_worker = ReturnHomeWorker(self.host_window.motion, parent=self)
            self.active_worker = home_worker

            def on_home_progress(text):
                self.run_status_label.setText(text)

            def on_home_completed():
                self.run_status_label.setText(
                    "Test complete — C and Gamma returned to Home (0.000°)."
                )

            def on_home_failed(message):
                self._home_return_failed = message
                self.run_status_label.setText(
                    "Test measurements completed, but automatic Home return failed."
                )
                QMessageBox.warning(
                    self,
                    "Return Home",
                    "The test completed, but Lumigon could not return both axes to Home:\n\n"
                    + message,
                )

            home_worker.progress.connect(on_home_progress)
            home_worker.home_completed.connect(on_home_completed)
            home_worker.failed.connect(on_home_failed)
            home_worker.finished.connect(self._restore_after_worker)
            home_worker.start()
            return

        if self._home_return_in_progress:
            self._home_return_in_progress = False

        original_restore_after_worker(self)

        if hasattr(self, "run_pause_button"):
            self.run_pause_button.hide()
            self.run_pause_button.setEnabled(False)
        if hasattr(self, "run_stop_button"):
            self.run_stop_button.hide()
            self.run_stop_button.setEnabled(False)

    TestPlanWorkspace.__init__ = patched_init
    TestPlanWorkspace._ready_points = patched_ready_points
    TestPlanWorkspace._begin_run = patched_begin_run
    TestPlanWorkspace._refresh_run_clock = patched_refresh_run_clock
    TestPlanWorkspace._set_running_controls = patched_set_running_controls
    TestPlanWorkspace.toggle_pause = patched_toggle_pause
    TestPlanWorkspace.request_abort = patched_request_abort
    TestPlanWorkspace._step_estimate_seconds = patched_step_estimate_seconds
    TestPlanWorkspace._continuous_estimate_seconds = patched_continuous_estimate_seconds
    TestPlanWorkspace._restore_after_worker = patched_restore_after_worker
