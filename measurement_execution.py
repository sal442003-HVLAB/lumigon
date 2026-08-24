"""Measurement execution workers for Lumigon commissioning.

Automatic execution is deliberately limited to one sweep axis per run.  The
non-sweep axis must already be at the requested fixed angle and remains OFF,
which preserves the current commissioning servo-selection interlock.
"""

import threading
import time

from PySide6.QtCore import QThread, Signal

from motion_controller import C_AXIS, GAMMA


SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
SCAN_GRID = 2
FIXED_AXIS_TOLERANCE_DEG = 0.05


class SinglePointMeasurementWorker(QThread):
    """Move one sweep axis, settle, acquire Lux and calculate candela."""

    progress = Signal(str)
    result_ready = Signal(float, float, float, float)
    aborted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        motion,
        meter,
        scan_mode: int,
        target_c_deg: float,
        target_gamma_deg: float,
        settle_time_s: float,
        samples: int,
        integration_ms: int,
        apply_measurement_settings: bool,
        distance_m: float,
        parent=None,
    ):
        super().__init__(parent)
        self.motion = motion
        self.meter = meter
        self.scan_mode = int(scan_mode)
        self.target_c_deg = float(target_c_deg)
        self.target_gamma_deg = float(target_gamma_deg)
        self.settle_time_s = max(0.0, float(settle_time_s))
        self.samples = max(1, int(samples))
        self.integration_ms = int(integration_ms)
        self.apply_measurement_settings = bool(apply_measurement_settings)
        self.distance_m = float(distance_m)

    def _wait_interruptible(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return False
            remaining = deadline - time.monotonic()
            self.msleep(max(1, min(50, int(remaining * 1000.0))))
        return not self.isInterruptionRequested()

    def _axes_for_mode(self):
        if self.scan_mode == SCAN_SINGLE_C_GAMMA:
            return C_AXIS, self.target_c_deg, GAMMA, self.target_gamma_deg
        if self.scan_mode == SCAN_SINGLE_GAMMA_C:
            return GAMMA, self.target_gamma_deg, C_AXIS, self.target_c_deg
        raise RuntimeError(
            "C × Gamma Grid automatic execution is not enabled during this commissioning stage."
        )

    def run(self):
        try:
            fixed_axis, fixed_target, sweep_axis, sweep_target = self._axes_for_mode()

            if self.distance_m <= 0.0:
                raise RuntimeError("Measurement distance must be greater than zero.")

            fixed_actual = self.motion.get_current_angle(fixed_axis)
            fixed_error = fixed_actual - fixed_target
            if abs(fixed_error) > FIXED_AXIS_TOLERANCE_DEG:
                raise RuntimeError(
                    f"{fixed_axis.name} is the fixed axis for this scan and must "
                    f"already be at {fixed_target:+.3f}°. Current position is "
                    f"{fixed_actual:+.3f}° (error {fixed_error:+.3f}°)."
                )

            if self.isInterruptionRequested():
                self.aborted.emit("Measurement aborted before motion.")
                return

            if self.apply_measurement_settings:
                if self.meter.integration_time_ms != self.integration_ms:
                    self.progress.emit(
                        f"Applying luxmeter integration: {self.integration_ms} ms"
                    )
                    self.meter.set_integration_time(self.integration_ms)

            self.meter.set_software_trigger()

            self.progress.emit(
                f"Moving {sweep_axis.name} to {sweep_target:+.3f}°"
            )
            self.motion.move_absolute(sweep_axis, sweep_target)

            if self.isInterruptionRequested():
                self.aborted.emit(
                    "Abort requested. Motion completed safely; Lux acquisition was skipped."
                )
                return

            self.progress.emit(f"Settling for {self.settle_time_s:.1f} s")
            if not self._wait_interruptible(self.settle_time_s):
                self.aborted.emit("Measurement aborted during settling.")
                return

            self.progress.emit(f"Acquiring {self.samples} Lux samples")
            reading = self.meter.read_lux(samples=self.samples)

            if self.isInterruptionRequested():
                self.aborted.emit(
                    "Abort requested during acquisition; the completed reading was discarded."
                )
                return

            candela = reading.lux * (self.distance_m ** 2)
            current_na = reading.mean_current_a * 1e9

            self.result_ready.emit(
                current_na,
                reading.lux,
                reading.stdev_lux,
                candela,
            )

        except Exception as exc:
            self.failed.emit(str(exc))


class MeasurementRunWorker(QThread):
    """Execute all ready points of one validated single-axis scan."""

    progress = Signal(str)
    point_started = Signal(int, int, int, float, float)
    point_result = Signal(int, float, float, float, float)
    run_completed = Signal()
    aborted = Signal(str)
    failed = Signal(str)
    pause_state = Signal(bool)

    def __init__(
        self,
        *,
        motion,
        meter,
        scan_mode: int,
        points,
        settle_time_s: float,
        samples: int,
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
        self.settle_time_s = max(0.0, float(settle_time_s))
        self.samples = max(1, int(samples))
        self.integration_ms = int(integration_ms)
        self.apply_measurement_settings = bool(apply_measurement_settings)
        self.distance_m = float(distance_m)
        self._pause_event = threading.Event()

    def request_pause(self, paused: bool):
        paused = bool(paused)
        if paused:
            self._pause_event.set()
        else:
            self._pause_event.clear()
        self.pause_state.emit(paused)

    def _wait_while_paused(self) -> bool:
        while self._pause_event.is_set():
            if self.isInterruptionRequested():
                return False
            self.msleep(50)
        return not self.isInterruptionRequested()

    def _wait_interruptible(self, seconds: float) -> bool:
        remaining = max(0.0, float(seconds))
        last = time.monotonic()

        while remaining > 0.0:
            if self.isInterruptionRequested():
                return False

            if self._pause_event.is_set():
                if not self._wait_while_paused():
                    return False
                last = time.monotonic()
                continue

            now = time.monotonic()
            remaining -= max(0.0, now - last)
            last = now
            if remaining > 0.0:
                self.msleep(max(1, min(50, int(remaining * 1000.0))))

        return not self.isInterruptionRequested()

    def _axes_for_mode(self, c_target, gamma_target):
        if self.scan_mode == SCAN_SINGLE_C_GAMMA:
            return C_AXIS, c_target, GAMMA, gamma_target
        if self.scan_mode == SCAN_SINGLE_GAMMA_C:
            return GAMMA, gamma_target, C_AXIS, c_target
        raise RuntimeError(
            "C × Gamma Grid automatic execution is not enabled during this commissioning stage."
        )

    def _verify_fixed_axis(self, fixed_axis, fixed_target):
        fixed_actual = self.motion.get_current_angle(fixed_axis)
        fixed_error = fixed_actual - fixed_target
        if abs(fixed_error) > FIXED_AXIS_TOLERANCE_DEG:
            raise RuntimeError(
                f"{fixed_axis.name} is the fixed axis and must remain at "
                f"{fixed_target:+.3f}°. Current position is {fixed_actual:+.3f}° "
                f"(error {fixed_error:+.3f}°)."
            )

    def run(self):
        try:
            if not self.points:
                raise RuntimeError("No Ready measurement points were supplied.")
            if self.distance_m <= 0.0:
                raise RuntimeError("Measurement distance must be greater than zero.")
            if self.scan_mode == SCAN_GRID:
                raise RuntimeError(
                    "C × Gamma Grid automatic execution is not enabled yet."
                )

            if self.apply_measurement_settings:
                if self.meter.integration_time_ms != self.integration_ms:
                    self.progress.emit(
                        f"Applying luxmeter integration: {self.integration_ms} ms"
                    )
                    self.meter.set_integration_time(self.integration_ms)

            self.meter.set_software_trigger()
            total = len(self.points)

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

                # Check the fixed axis before every point. This catches any
                # unintended mechanical drift/coupling before another move starts.
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
