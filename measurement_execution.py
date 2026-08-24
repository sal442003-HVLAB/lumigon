"""Single-point measurement execution for Lumigon commissioning.

This module deliberately executes only one validated point at a time.  It does
not implement an automatic multi-point scan yet.  The current commissioning
servo-selection rule is preserved: only the sweep axis is commanded, while the
fixed axis must already be at its requested angle.
"""

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

            # The fixed axis is intentionally not commanded in this stage.  This
            # preserves the current commissioning rule that the non-selected servo
            # remains OFF while the selected sweep servo moves.
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

            # Formal point acquisition uses software trigger T1: every M? starts
            # a new integration rather than returning a stale continuous sample.
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
