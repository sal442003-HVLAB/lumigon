"""Continuous (fly-scan) photometric acquisition for Lumigon.

The worker performs one smooth single-axis sweep.  The sweep axis moves from the
first Ready test point to the last without stopping at intermediate points.  The
Ph-Amp runs in T0 continuous-trigger mode and Lumigon samples angle feedback and
photocurrent while the axis is moving.  When a requested angular point is crossed,
Lux/current are linearly interpolated between the two surrounding samples.

This module intentionally supports only single-axis scans.  C x Gamma grid fly
scanning needs a separate traversal strategy and is not enabled here.
"""

import time

from PySide6.QtCore import QThread, Signal

from machine_config import P0_01, P0_09, P5_07, P6_03
from motion_controller import C_AXIS, GAMMA


SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
FIXED_AXIS_TOLERANCE_DEG = 0.05


class ContinuousMeasurementWorker(QThread):
    """Run a smooth single-axis sweep and sample Lux at angular crossings."""

    progress = Signal(str)
    sweep_started = Signal(float, float)
    angle_update = Signal(float, float)
    point_result = Signal(int, int, int, float, float, float, float, float, float)
    run_completed = Signal()
    aborted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        motion,
        meter,
        scan_mode: int,
        points,
        integration_ms: int,
        apply_measurement_settings: bool,
        distance_m: float,
        parent=None,
    ):
        super().__init__(parent)
        self.motion = motion
        self.meter = meter
        self.scan_mode = int(scan_mode)
        self.points = [
            (int(row), float(c_deg), float(gamma_deg))
            for row, c_deg, gamma_deg in points
        ]
        self.integration_ms = int(integration_ms)
        self.apply_measurement_settings = bool(apply_measurement_settings)
        self.distance_m = float(distance_m)

    def _axes(self):
        if self.scan_mode == SCAN_SINGLE_C_GAMMA:
            fixed_target = self.points[0][1]
            return C_AXIS, fixed_target, GAMMA, [p[2] for p in self.points]
        if self.scan_mode == SCAN_SINGLE_GAMMA_C:
            fixed_target = self.points[0][2]
            return GAMMA, fixed_target, C_AXIS, [p[1] for p in self.points]
        raise RuntimeError("Continuous Scan supports single-axis scans only.")

    def _verify_fixed_axis(self, axis, target):
        actual = self.motion.get_current_angle(axis)
        error = actual - target
        if abs(error) > FIXED_AXIS_TOLERANCE_DEG:
            raise RuntimeError(
                f"{axis.name} is fixed at {target:+.3f}°, but current position is "
                f"{actual:+.3f}° (error {error:+.3f}°)."
            )

    def _start_nonblocking_move(self, axis, target_degree):
        limit = self.motion.axis_limit_deg(axis)
        if abs(target_degree) > limit + 1e-9:
            raise RuntimeError(
                f"{axis.name}: target {target_degree:+.4f}° exceeds ±{limit:.1f}°."
            )

        self.motion.verify_axis(axis)
        self.motion.verify_servo_selection(axis)

        current = self.motion.get_current_angle(axis)
        delta_degree = target_degree - current
        if abs(delta_degree) <= 0.01:
            feedback = self.motion.modbus.read_s32(axis.slave_id, P0_09)
            return feedback, 1.0

        feedback_before = self.motion.modbus.read_s32(axis.slave_id, P0_09)
        delta_puu = self.motion.degree_to_puu(axis, delta_degree)
        expected_feedback = feedback_before + delta_puu

        self.motion.modbus.write_s32(axis.slave_id, P6_03, delta_puu)
        readback = self.motion.modbus.read_s32(axis.slave_id, P6_03)
        if readback != delta_puu:
            raise RuntimeError(f"{axis.name}: P6-03 verification failed.")

        alarm = self.motion.modbus.read_u16(axis.slave_id, P0_01)
        if alarm != 0:
            raise RuntimeError(
                f"{axis.name}: alarm 0x{alarm:04X} appeared before PR trigger."
            )

        self.motion.modbus.write_u16(axis.slave_id, P5_07, 1)
        return expected_feedback, self.motion.motion_timeout_seconds(axis, delta_degree)

    @staticmethod
    def _interpolate(target, a0, v0, a1, v1):
        span = a1 - a0
        if abs(span) < 1e-9:
            return v1
        fraction = (target - a0) / span
        fraction = max(0.0, min(1.0, fraction))
        return v0 + fraction * (v1 - v0)

    @staticmethod
    def _crossed(direction, angle, target):
        if direction > 0:
            return angle >= target - 1e-9
        return angle <= target + 1e-9

    def run(self):
        trigger_changed = False
        try:
            if not self.points:
                raise RuntimeError("No Ready points were supplied for Continuous Scan.")
            if self.distance_m <= 0.0:
                raise RuntimeError("Measurement distance must be greater than zero.")

            fixed_axis, fixed_target, sweep_axis, targets = self._axes()
            self._verify_fixed_axis(fixed_axis, fixed_target)

            start_target = float(targets[0])
            end_target = float(targets[-1])
            direction = 1.0 if end_target >= start_target else -1.0

            # Ready points must be monotonic for one physical fly sweep.
            for previous, current in zip(targets, targets[1:]):
                if direction > 0 and current < previous - 1e-9:
                    raise RuntimeError("Continuous Scan targets are not monotonic.")
                if direction < 0 and current > previous + 1e-9:
                    raise RuntimeError("Continuous Scan targets are not monotonic.")

            self.progress.emit(
                f"Positioning {sweep_axis.name} at Continuous Scan start "
                f"{start_target:+.3f}°"
            )
            self.motion.move_absolute(sweep_axis, start_target)

            if self.isInterruptionRequested():
                self.aborted.emit("Continuous Scan aborted before the sweep started.")
                return

            if self.apply_measurement_settings:
                if self.meter.integration_time_ms != self.integration_ms:
                    self.progress.emit(
                        f"Applying luxmeter integration: {self.integration_ms} ms"
                    )
                    self.meter.set_integration_time(self.integration_ms)

            # T0 continuously integrates. M? now returns the latest valid reading,
            # which is what we need while the motor keeps moving.
            self.meter.set_internal_trigger()
            trigger_changed = True
            self.msleep(max(20, int(self.integration_ms * 1.2)))

            start_angle = self.motion.get_current_angle(sweep_axis)
            start_current_a = self.meter.read_current()
            start_lux = self.meter.current_to_lux(start_current_a)

            first_row = self.points[0][0]
            first_c = self.points[0][1]
            first_gamma = self.points[0][2]
            first_candela = start_lux * (self.distance_m ** 2)
            self.point_result.emit(
                first_row,
                1,
                len(self.points),
                first_c,
                first_gamma,
                start_current_a * 1e9,
                start_lux,
                0.0,
                first_candela,
            )

            if len(self.points) == 1:
                self.run_completed.emit()
                return

            self.progress.emit(
                f"Continuous Scan: {sweep_axis.name} {start_target:+.3f}° → "
                f"{end_target:+.3f}°"
            )
            self.sweep_started.emit(start_target, end_target)
            expected_feedback, timeout_s = self._start_nonblocking_move(
                sweep_axis,
                end_target,
            )

            deadline = time.monotonic() + timeout_s
            next_index = 1
            prev_angle = start_angle
            prev_current_a = start_current_a
            prev_lux = start_lux
            abort_requested = False

            tolerance_deg = max(
                0.01,
                sweep_axis.tolerance_puu / sweep_axis.puu_per_degree,
            )

            while time.monotonic() < deadline:
                alarm = self.motion.modbus.read_u16(sweep_axis.slave_id, P0_01)
                if alarm != 0:
                    raise RuntimeError(
                        f"{sweep_axis.name}: alarm 0x{alarm:04X} during Continuous Scan."
                    )

                feedback = self.motion.modbus.read_s32(sweep_axis.slave_id, P0_09)
                angle = self.motion.puu_to_degree(
                    sweep_axis,
                    feedback - self.motion.get_zero(sweep_axis),
                )
                self.angle_update.emit(
                    angle if sweep_axis is C_AXIS else fixed_target,
                    angle if sweep_axis is GAMMA else fixed_target,
                )

                if self.isInterruptionRequested():
                    abort_requested = True

                if not abort_requested:
                    current_a = self.meter.read_current()
                    lux = self.meter.current_to_lux(current_a)

                    while next_index < len(self.points) and self._crossed(
                        direction,
                        angle,
                        targets[next_index],
                    ):
                        target_angle = targets[next_index]
                        interp_lux = self._interpolate(
                            target_angle,
                            prev_angle,
                            prev_lux,
                            angle,
                            lux,
                        )
                        interp_current_a = self._interpolate(
                            target_angle,
                            prev_angle,
                            prev_current_a,
                            angle,
                            current_a,
                        )
                        row, c_deg, gamma_deg = self.points[next_index]
                        candela = interp_lux * (self.distance_m ** 2)
                        self.point_result.emit(
                            row,
                            next_index + 1,
                            len(self.points),
                            c_deg,
                            gamma_deg,
                            interp_current_a * 1e9,
                            interp_lux,
                            0.0,
                            candela,
                        )
                        next_index += 1

                    prev_angle = angle
                    prev_current_a = current_a
                    prev_lux = lux

                target_reached = (
                    abs(feedback - expected_feedback) <= sweep_axis.tolerance_puu
                    or abs(angle - end_target) <= tolerance_deg
                )
                if target_reached:
                    break

                self.msleep(2 if abort_requested else 1)
            else:
                raise RuntimeError(
                    f"{sweep_axis.name}: Continuous Scan motion timeout after "
                    f"{timeout_s:.1f} s."
                )

            if abort_requested:
                self.aborted.emit(
                    "Continuous Scan abort requested. The active sweep was allowed "
                    "to finish safely; remaining measurements were not acquired."
                )
                return

            # If the final feedback lands within tolerance but one target was missed
            # by numerical crossing, use one final latest reading for remaining end
            # points rather than silently dropping them.
            if next_index < len(self.points):
                final_current_a = self.meter.read_current()
                final_lux = self.meter.current_to_lux(final_current_a)
                while next_index < len(self.points):
                    row, c_deg, gamma_deg = self.points[next_index]
                    candela = final_lux * (self.distance_m ** 2)
                    self.point_result.emit(
                        row,
                        next_index + 1,
                        len(self.points),
                        c_deg,
                        gamma_deg,
                        final_current_a * 1e9,
                        final_lux,
                        0.0,
                        candela,
                    )
                    next_index += 1

            self.run_completed.emit()

        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if trigger_changed:
                try:
                    self.meter.set_software_trigger()
                except Exception:
                    # Preserve the original scan result/error. The next formal
                    # acquisition will explicitly request its trigger mode again.
                    pass
