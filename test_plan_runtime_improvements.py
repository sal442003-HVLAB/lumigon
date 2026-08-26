"""Runtime refinements for Lumigon Test Plan execution.

This layer keeps the existing Measurement UI and signals intact while adding:
- explicit pre-positioning to the nearest scan endpoint before point 1 starts,
- fixed-axis auto-positioning,
- a profile-aware initial ETA that includes motion + acquisition + Home return,
- a true countdown ETA (not recalculated from completed points),
- robust automatic return of both axes to Session Home after a normal run,
- dedicated Pause / Stop controls in the live Test Plan workspace.
"""

import math
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QMessageBox, QPushButton

from continuous_measurement import ContinuousMeasurementWorker
from measurement_execution import MeasurementRunWorker
from motion_controller import C_AXIS, GAMMA
from test_plan_workspace import (
    CommissioningMotionWorker,
    SCAN_GRID,
    SCAN_SINGLE_C_GAMMA,
    SCAN_SINGLE_GAMMA_C,
    TestPlanWorkspace,
    FIXED_AXIS_TOLERANCE_DEG,
    INTER_SAMPLE_DELAY_MS,
    _format_duration,
)


# Timing model constants.  The important part is that every actual PR move is
# estimated from current speed plus Ramp and S-curve rather than cruise speed
# alone.  The small communication allowance covers Modbus command/readback and
# target polling; the final margin avoids ETA reaching zero before the hardware.
MOTION_COMMAND_OVERHEAD_S = 0.15
MEASUREMENT_QUERY_OVERHEAD_S = 0.025
FORMAL_MEASUREMENT_SETUP_S = 0.25
ETA_MARGIN_FACTOR = 1.10
ENDPOINT_TIE_TOLERANCE_DEG = 0.05
HOME_TOLERANCE_DEG = 0.03


class ReturnHomeWorker(QThread):
    """Return both axes to Session Home without blocking the HMI thread.

    Each axis is handled independently.  This is important during commissioning:
    if one axis is already at 0° while its Servo is OFF, that must not prevent the
    other axis from returning Home.  Likewise, a failure on one axis does not
    suppress the return attempt on the other axis.
    """

    progress = Signal(str)
    home_completed = Signal()
    failed = Signal(str)

    def __init__(self, motion, parent=None):
        super().__init__(parent)
        self.motion = motion

    def _return_axis(self, axis):
        actual = self.motion.get_current_angle(axis)
        if abs(actual) <= HOME_TOLERANCE_DEG:
            self.progress.emit(
                f"{axis.name} already at Home ({actual:+.3f}°)."
            )
            return None

        self.progress.emit(
            f"Returning {axis.name} axis to Home: {actual:+.3f}° → 0.000°…"
        )
        try:
            self.motion.return_to_zero(axis)
        except Exception as exc:
            return f"{axis.name}: {exc}"

        final = self.motion.get_current_angle(axis)
        if abs(final) > HOME_TOLERANCE_DEG:
            return (
                f"{axis.name}: Home verification failed; final position "
                f"{final:+.3f}°."
            )

        self.progress.emit(f"{axis.name} Home verified at {final:+.3f}°.")
        return None

    def run(self):
        errors = []
        try:
            # C first, Gamma last.  This preserves the previous commissioning
            # choice that Gamma is the final commanded orientation.
            for axis in (C_AXIS, GAMMA):
                error = self._return_axis(axis)
                if error:
                    errors.append(error)

            c_actual = self.motion.get_current_angle(C_AXIS)
            gamma_actual = self.motion.get_current_angle(GAMMA)

            if errors:
                self.failed.emit(
                    "\n".join(errors)
                    + f"\nFinal feedback: C {c_actual:+.3f}°, "
                    f"Gamma {gamma_actual:+.3f}°."
                )
                return

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
    """Estimate one PR move using speed + Ramp + S-curve.

    For short moves the axis cannot spend the whole move at configured cruise
    speed.  Treat Ramp + S-curve as an effective acceleration/deceleration time
    and use a triangular/trapezoidal approximation.  This is intentionally more
    realistic for 1° Step Scan moves than distance / cruise-speed alone.
    """

    distance = abs(float(delta_deg))
    if distance <= 0.01:
        return 0.0

    motor_rpm = motion.expected_speed_raw(axis) / 10.0
    if motor_rpm <= 0.0:
        return 0.0

    output_deg_per_second = motor_rpm * 6.0 / axis.gear_ratio
    if output_deg_per_second <= 0.0:
        return 0.0

    ramp_s = max(0.0, motion.expected_ramp(axis) / 1000.0)
    scurve_s = max(0.0, motion.expected_scurve(axis) / 1000.0)
    accel_time_s = ramp_s + scurve_s

    if accel_time_s <= 1e-6:
        travel_s = distance / output_deg_per_second
    else:
        # Distance needed for a full accel + full decel at configured speed.
        full_profile_distance = output_deg_per_second * accel_time_s
        if distance >= full_profile_distance:
            cruise_distance = distance - full_profile_distance
            travel_s = (
                2.0 * accel_time_s
                + cruise_distance / output_deg_per_second
            )
        else:
            # Short move: triangular profile, peak speed below configured speed.
            travel_s = 2.0 * math.sqrt(
                distance * accel_time_s / output_deg_per_second
            )

    return travel_s + MOTION_COMMAND_OVERHEAD_S


def _measurement_run_prepositioned(self):
    """MeasurementRunWorker.run with an explicit pre-positioning phase."""

    try:
        if not self.points:
            raise RuntimeError("No Ready measurement points were supplied.")
        if self.distance_m <= 0.0:
            raise RuntimeError("Measurement distance must be greater than zero.")
        if self.scan_mode == SCAN_GRID:
            raise RuntimeError("C × Gamma Grid automatic execution is not enabled yet.")

        if self.apply_measurement_settings:
            if self.meter.integration_time_ms != self.integration_ms:
                self.progress.emit(
                    f"Applying luxmeter integration: {self.integration_ms} ms"
                )
                self.meter.set_integration_time(self.integration_ms)

        self.meter.set_software_trigger()
        total = len(self.points)

        # Position both axes first.  No point is declared Started and no Lux is
        # acquired until the sweep axis has actually reached the chosen endpoint.
        _, first_c, first_gamma = self.points[0]
        fixed_axis, fixed_target, sweep_axis, sweep_start = self._axes_for_mode(
            first_c,
            first_gamma,
        )
        self.progress.emit("Preparing scan start position…")
        self._verify_fixed_axis(fixed_axis, fixed_target)

        if self.isInterruptionRequested():
            self.aborted.emit("Measurement aborted before scan-start positioning.")
            return

        current = self.motion.get_current_angle(sweep_axis)
        if abs(current - sweep_start) > 0.01:
            self.progress.emit(
                f"Positioning {sweep_axis.name} at scan start: "
                f"{current:+.3f}° → {sweep_start:+.3f}°"
            )
            self.motion.move_absolute(sweep_axis, sweep_start)

        if self.isInterruptionRequested():
            self.aborted.emit(
                "Abort requested. Scan-start positioning completed safely; "
                "no acquisition was started."
            )
            return

        for sequence, (row, c_target, gamma_target) in enumerate(
            self.points,
            start=1,
        ):
            if self.isInterruptionRequested():
                self.aborted.emit("Measurement run aborted before the next point.")
                return
            if not self._wait_while_paused():
                self.aborted.emit("Measurement run aborted while paused.")
                return

            fixed_axis, fixed_target, sweep_axis, sweep_target = self._axes_for_mode(
                c_target,
                gamma_target,
            )
            self._verify_fixed_axis(fixed_axis, fixed_target)

            # Point 1 is emitted only after scan-start positioning is complete.
            self.point_started.emit(
                row,
                sequence,
                total,
                c_target,
                gamma_target,
            )

            if sequence > 1:
                self.progress.emit(
                    f"Point {sequence}/{total}: moving {sweep_axis.name} "
                    f"to {sweep_target:+.3f}°"
                )
                self.motion.move_absolute(sweep_axis, sweep_target)
            else:
                self.progress.emit(
                    f"Point 1/{total}: scan start reached at "
                    f"{sweep_target:+.3f}°"
                )

            if self.isInterruptionRequested():
                self.aborted.emit(
                    "Abort requested. The active servo move completed safely; "
                    "no further acquisition was started."
                )
                return

            if not self._wait_while_paused():
                self.aborted.emit("Measurement run aborted after motion.")
                return

            self.progress.emit(
                f"Point {sequence}/{total}: settling for {self.settle_time_s:.1f} s"
            )
            if not self._wait_interruptible(self.settle_time_s):
                self.aborted.emit("Measurement run aborted during settling.")
                return

            self.progress.emit(
                f"Point {sequence}/{total}: acquiring {self.samples} Lux samples"
            )
            reading = self.meter.read_lux(samples=self.samples)

            if self.isInterruptionRequested():
                self.aborted.emit(
                    "Abort requested during acquisition; the completed reading "
                    "was discarded and no further point will run."
                )
                return

            candela = reading.lux * (self.distance_m ** 2)
            current_na = reading.mean_current_a * 1e9
            self.point_result.emit(
                row,
                current_na,
                reading.lux,
                reading.stdev_lux,
                candela,
            )

        self.run_completed.emit()

    except Exception as exc:
        self.failed.emit(str(exc))


def _commissioning_run_prepositioned(self):
    """Motion-only Step Scan with the same explicit scan-start positioning."""

    try:
        if not self.points:
            raise RuntimeError("No Ready points were supplied.")

        total = len(self.points)
        _, first_c, first_gamma = self.points[0]
        fixed_axis, fixed_target, sweep_axis, sweep_start = self._axes_for_mode(
            first_c,
            first_gamma,
        )

        self.progress.emit("Preparing scan start position…")
        self._verify_fixed_axis(fixed_axis, fixed_target)
        if self.isInterruptionRequested():
            self.aborted.emit("Motion-only run aborted before scan-start positioning.")
            return

        current = self.motion.get_current_angle(sweep_axis)
        if abs(current - sweep_start) > 0.01:
            self.progress.emit(
                f"Positioning {sweep_axis.name} at scan start: "
                f"{current:+.3f}° → {sweep_start:+.3f}°"
            )
            self.motion.move_absolute(sweep_axis, sweep_start)

        if self.isInterruptionRequested():
            self.aborted.emit(
                "Abort requested. Scan-start positioning completed safely."
            )
            return

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

            if sequence > 1:
                self.progress.emit(
                    f"Point {sequence}/{total}: moving {sweep_axis.name} "
                    f"to {sweep_target:+.3f}°"
                )
                self.motion.move_absolute(sweep_axis, sweep_target)
            else:
                self.progress.emit(
                    f"Point 1/{total}: scan start reached at "
                    f"{sweep_target:+.3f}°"
                )

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


def install_test_plan_runtime_improvements():
    """Install the v0.3 Test Plan refinements before the workspace is built."""

    if getattr(TestPlanWorkspace, "_runtime_improvements_installed", False):
        return
    TestPlanWorkspace._runtime_improvements_installed = True

    # Fixed-axis positioning is automatic; the operator does not have to place
    # it manually before Start Measurement.
    MeasurementRunWorker._verify_fixed_axis = _auto_position_fixed_axis
    ContinuousMeasurementWorker._verify_fixed_axis = _auto_position_fixed_axis
    CommissioningMotionWorker._verify_fixed_axis = _auto_position_fixed_axis

    # Step Scan explicitly reaches the selected endpoint before point 1 begins.
    MeasurementRunWorker.run = _measurement_run_prepositioned
    CommissioningMotionWorker.run = _commissioning_run_prepositioned

    original_init = TestPlanWorkspace.__init__
    original_ready_points = TestPlanWorkspace._ready_points
    original_begin_run = TestPlanWorkspace._begin_run
    original_set_running_controls = TestPlanWorkspace._set_running_controls
    original_restore_after_worker = TestPlanWorkspace._restore_after_worker

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

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
        first_distance = abs(current - first_target)
        last_distance = abs(current - last_target)

        # Do not let tiny encoder noise around an exact midpoint flip direction.
        # Outside the tie band, always start from the physically nearer endpoint.
        if last_distance + ENDPOINT_TIE_TOLERANCE_DEG < first_distance:
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

        # Calculate once, then only count down.  Point completion cannot make ETA
        # jump.  Pause freezes remaining time but elapsed remains wall-clock time.
        if not self.paused:
            self._eta_remaining_s = max(0.0, self._eta_remaining_s - delta)

        self.run_elapsed_label.setText(_format_duration(elapsed))
        self.run_eta_label.setText(_format_duration(self._eta_remaining_s))

    def patched_set_running_controls(self, running):
        original_set_running_controls(self, running)

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
        if self.pause_button is not None:
            self.pause_button.setEnabled(False)
        if self.abort_button is not None:
            self.abort_button.setEnabled(False)

        self.run_status_label.setText(
            "Stop requested — the active servo move is allowed to finish safely; "
            "the run will stop at the next safe checkpoint."
        )

    def _step_motion_plan(self, points):
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

        # Normal completion includes automatic Home return.
        seconds += _axis_motion_seconds(motion, C_AXIS, -points[-1][1])
        seconds += _axis_motion_seconds(motion, GAMMA, -points[-1][2])
        return seconds

    def _continuous_motion_plan(self, points):
        if not points:
            return 0.0

        motion = self.host_window.motion
        mode = self.host_window.measurement_scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            fixed_axis = C_AXIS
            fixed_target = points[0][1]
            sweep_axis = GAMMA
            start_target = points[0][2]
            end_target = points[-1][2]
            final_c = fixed_target
            final_gamma = end_target
        else:
            fixed_axis = GAMMA
            fixed_target = points[0][2]
            sweep_axis = C_AXIS
            start_target = points[0][1]
            end_target = points[-1][1]
            final_c = end_target
            final_gamma = fixed_target

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
            start_target - current_sweep,
        )
        # One physical Fly Scan move, not one move per target point.
        seconds += _axis_motion_seconds(
            motion,
            sweep_axis,
            end_target - start_target,
        )
        seconds += _axis_motion_seconds(motion, C_AXIS, -final_c)
        seconds += _axis_motion_seconds(motion, GAMMA, -final_gamma)
        return seconds

    def patched_step_estimate_seconds(self, point_count, motion_only=False):
        points = self._ready_points()
        settle = self.host_window.measurement_settle_spin.value()
        total = _step_motion_plan(self, points)
        total += point_count * settle

        if not motion_only:
            samples = self.host_window.measurement_samples_spin.value()
            integration_s = (
                self.host_window.measurement_integration_spin.value() / 1000.0
            )
            per_sample_s = integration_s + MEASUREMENT_QUERY_OVERHEAD_S
            sample_block_s = samples * per_sample_s
            if samples > 1:
                sample_block_s += (
                    samples - 1
                ) * (INTER_SAMPLE_DELAY_MS / 1000.0)
            total += point_count * sample_block_s
            total += FORMAL_MEASUREMENT_SETUP_S

        return total * ETA_MARGIN_FACTOR

    def patched_continuous_estimate_seconds(self, points):
        if not points:
            return 0.0

        total = _continuous_motion_plan(self, points)
        total += max(
            0.25,
            self.host_window.measurement_integration_spin.value() / 1000.0,
        )
        return total * ETA_MARGIN_FACTOR

    def patched_restore_after_worker(self):
        # A normal run is not operationally finished until Home return has been
        # attempted for both axes.
        if self.run_finished_normally and not self._home_return_in_progress:
            finished_worker = self.active_worker
            if finished_worker is not None:
                finished_worker.deleteLater()

            self.host_window.measurement_worker = None
            self.host_window.continuous_measurement_worker = None

            self._home_return_in_progress = True
            self.run_status_label.setText(
                "Measurements complete — returning both axes to Home "
                "(C 0.000°, Gamma 0.000°)…"
            )
            if hasattr(self, "run_pause_button"):
                self.run_pause_button.hide()
            if hasattr(self, "run_stop_button"):
                self.run_stop_button.hide()

            # _finish_run_monitor() stops the clock when the last point completes.
            # Home time is part of the initial ETA, so resume the same countdown.
            self._eta_last_tick = time.monotonic()
            self.run_clock.start()

            home_worker = ReturnHomeWorker(self.host_window.motion, parent=self)
            self.active_worker = home_worker

            def on_home_progress(text):
                self.run_status_label.setText(text)

            def on_home_completed():
                self._eta_remaining_s = 0.0
                self.run_eta_label.setText("0 s")
                self.run_clock.stop()
                self.run_status_label.setText(
                    "Test complete — C and Gamma returned to Home (0.000°)."
                )

            def on_home_failed(message):
                self._home_return_failed = message
                self.run_clock.stop()
                self.run_eta_label.setText("—")
                self.run_status_label.setText(
                    "Measurements completed, but automatic Home return was incomplete."
                )
                QMessageBox.warning(
                    self,
                    "Return Home",
                    "The test completed, but Lumigon could not return every axis "
                    "to Home:\n\n" + message,
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
