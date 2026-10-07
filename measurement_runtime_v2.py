"""Automatic Version 2 goniophotometric measurement runtime.

The V2 runtime intentionally owns one simple workflow:
- move through the requested C x Gamma grid,
- acquire one valid optical flash at every point with the P-9710,
- automatically retry incomplete/invalid acquisitions,
- store the accepted value for the point,
- save every accepted point immediately to CSV.

For E-effective mode the Schmidt-Clausen form-factor equation is calculated
from the sampled CW waveform itself. No flash-period prediction is required.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox

from measurement_progress_dialog_v2 import MeasurementProgressDialogV2
from measurement_run import measurement_data_directory
from motion_controller import C_AXIS, GAMMA
from p9710 import P9710Error
from p9710_range_policy import GP_SATURATION_REFERENCE, GP_REFERENCE_BASIS, normalized_range_use


MODE_I_EFFECTIVE = "i_effective"
MODE_CW_MAXIMUM = "cw_maximum"

CW_INTEGRATION_MS = 0.1
INITIAL_RANGE_ID = 5
FLASH_CAPTURE_S = 5.5
SCHMIDT_CLAUSEN_C_S = 0.2
SETTLE_S = 0.20
MAX_POINT_ATTEMPTS = 3
MIN_MODULATION_LX = 0.0005
RANGE_TARGET_MIN_PCT = 10.0
RANGE_MAX_PCT = 90.0
MAX_RANGE_SELECTION_ATTEMPTS = 16


class _AbortRequested(RuntimeError):
    pass


class _RangeOverload(RuntimeError):
    pass


class _RangeCheckFailed(RuntimeError):
    pass


@dataclass(frozen=True)
class RangeCheckedCapture:
    samples: list
    peak_utilization_pct: float
    gp_checks: int


@dataclass(frozen=True)
class FlashSample:
    range_id: int
    baseline_lx: float
    cw_max_lx: float
    net_peak_lx: float
    e_effective_lx: float
    pulse_duration_ms: float
    integral_lx_s: float
    median_dt_ms: float
    range_peak_utilization_pct: float | None = None
    range_precheck_peak_pct: float | None = None
    range_acquisition_peak_pct: float | None = None
    range_check_count: int = 0
    range_selection_attempts: int = 0
    range_check_status: str = "unverified"


def _percentile(values, fraction: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        raise RuntimeError("No photometric samples were captured.")

    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]

    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _crossing_time(t0, v0, t1, v1, threshold):
    if t1 <= t0 or v1 == v0:
        return float(t1)

    fraction = (threshold - v0) / (v1 - v0)
    fraction = max(0.0, min(1.0, fraction))
    return float(t0) + fraction * (float(t1) - float(t0))


def _trapz(points):
    area = 0.0
    for (t0, y0), (t1, y1) in zip(points, points[1:]):
        dt = float(t1) - float(t0)
        if dt > 0.0:
            area += 0.5 * (float(y0) + float(y1)) * dt
    return area


def analyse_single_flash(samples, *, c_s: float = SCHMIDT_CLAUSEN_C_S) -> FlashSample:
    """Extract one complete optical flash and calculate Schmidt-Clausen E-effective."""

    if len(samples) < 30:
        raise RuntimeError("Too few CW samples were captured for one flash.")

    values = [float(value) for _t, value in samples]
    baseline = _percentile(values, 0.20)
    high_level = _percentile(values, 0.95)
    span = high_level - baseline

    if not math.isfinite(span) or span < MIN_MODULATION_LX:
        raise RuntimeError(
            f"No usable optical flash was detected "
            f"(baseline {baseline:.6g} lx, modulation {span:.6g} lx)."
        )

    deviations = [abs(v - baseline) for v in values if v <= high_level]
    noise = statistics.median(deviations) if deviations else 0.0
    threshold_offset = max(0.05 * span, 6.0 * noise, MIN_MODULATION_LX)
    threshold = baseline + threshold_offset

    above = [value >= threshold for value in values]
    segments = []
    index = 0

    while index < len(samples):
        if not above[index]:
            index += 1
            continue

        first = index
        while index + 1 < len(samples) and above[index + 1]:
            index += 1
        last = index
        index += 1

        # A pulse touching either capture boundary is incomplete and is ignored.
        if first == 0 or last >= len(samples) - 1:
            continue

        t_start = _crossing_time(
            samples[first - 1][0],
            samples[first - 1][1],
            samples[first][0],
            samples[first][1],
            threshold,
        )
        t_end = _crossing_time(
            samples[last][0],
            samples[last][1],
            samples[last + 1][0],
            samples[last + 1][1],
            threshold,
        )

        duration_s = t_end - t_start
        if duration_s < 0.05 or duration_s > 2.0:
            continue

        raw_values = [samples[i][1] for i in range(first, last + 1)]
        raw_peak = max(raw_values)
        net_peak = max(0.0, raw_peak - baseline)
        if net_peak <= 0.0:
            continue

        integration_points = [(t_start, max(0.0, threshold - baseline))]
        for i in range(first, last + 1):
            integration_points.append(
                (samples[i][0], max(0.0, samples[i][1] - baseline))
            )
        integration_points.append((t_end, max(0.0, threshold - baseline)))

        integral = _trapz(integration_points)
        if integral <= 0.0:
            continue

        # Schmidt-Clausen:
        # E_eff = E_peak * J / (E_peak * C + J)
        e_effective = net_peak * integral / (net_peak * float(c_s) + integral)

        intervals = [
            later[0] - earlier[0]
            for earlier, later in zip(samples, samples[1:])
            if later[0] > earlier[0]
        ]
        median_dt_ms = (
            statistics.median(intervals) * 1000.0 if intervals else 0.0
        )

        segments.append(
            FlashSample(
                range_id=-1,
                baseline_lx=baseline,
                cw_max_lx=raw_peak,
                net_peak_lx=net_peak,
                e_effective_lx=e_effective,
                pulse_duration_ms=duration_s * 1000.0,
                integral_lx_s=integral,
                median_dt_ms=median_dt_ms,
            )
        )

    if not segments:
        raise RuntimeError(
            "No complete optical pulse was found inside the CW capture window."
        )

    # The expected source is a single-flash LED. If more than one complete pulse
    # happens to fit, use the strongest complete pulse.
    return max(segments, key=lambda item: item.net_peak_lx)


def _axis_values(start: float, end: float, step: float):
    start = float(start)
    end = float(end)
    step = abs(float(step))
    if step <= 0.0:
        raise ValueError("Angular resolution must be greater than zero.")

    direction = 1.0 if end >= start else -1.0
    signed_step = step * direction
    values = []
    current = start
    epsilon = 1e-9

    if direction > 0:
        while current <= end + epsilon:
            values.append(round(current, 6))
            current += signed_step
    else:
        while current >= end - epsilon:
            values.append(round(current, 6))
            current += signed_step

    if values and abs(values[-1] - end) > epsilon:
        values.append(round(end, 6))
    return values


def build_serpentine_points(c_values, gamma_values):
    points = []
    for plane_index, c_deg in enumerate(c_values):
        sweep = gamma_values if plane_index % 2 == 0 else list(reversed(gamma_values))
        for gamma_deg in sweep:
            points.append((float(c_deg), float(gamma_deg)))
    return points


def _safe_filename(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text).strip())
    return cleaned.strip("._-") or "sample"


def _format_point_value(mode: str, value_lx: float, distance_m: float) -> str:
    if mode == MODE_CW_MAXIMUM:
        return f"{value_lx:.4f} lx CW max"
    return (
        f"E-effective {value_lx:.4f} lx • "
        f"I-effective {value_lx * distance_m * distance_m:.2f} cd"
    )


class MeasurementV2Worker(QThread):
    status = Signal(str)
    progress = Signal(object)
    point_accepted = Signal(object)
    range_updated = Signal(object)
    completed = Signal(object)
    aborted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        motion,
        meter,
        points,
        mode: str,
        distance_m: float,
        sample_id: str,
        output_path,
        parent=None,
    ):
        super().__init__(parent)
        self.motion = motion
        self.meter = meter
        self.points = [(float(c), float(g)) for c, g in points]
        self.mode = str(mode)
        self.distance_m = float(distance_m)
        self.sample_id = str(sample_id).strip() or "sample"
        self.output_path = Path(output_path)
        self.current_range_id = INITIAL_RANGE_ID

    def _check_abort(self):
        if self.isInterruptionRequested():
            raise _AbortRequested()

    def _wait_interruptible(self, seconds: float):
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            self._check_abort()
            remaining = deadline - time.monotonic()
            self.msleep(max(1, min(50, int(remaining * 1000.0))))

    def _emit_range(self, range_id, phase, peak_pct=None, state="checking"):
        self._diagnostic_range = range_id
        self._diagnostic_phase = phase
        self.range_updated.emit({
            "range_id": range_id, "phase": phase,
            "peak_pct": peak_pct, "state": state,
            "raw_gp_peak": None if peak_pct is None else peak_pct * GP_SATURATION_REFERENCE / 100.0,
            "gp_reference": GP_SATURATION_REFERENCE,
        })

    def _read_checked_gp(self, range_id, phase, previous_peak):
        self._check_abort()
        try:
            utilization = abs(float(self.meter.read_range_utilization()))
        except Exception as exc:
            status = self.meter._status_code(exc)
            if status == "overload":
                self._emit_range(range_id, phase, previous_peak, "overload")
                raise _RangeOverload("P-9710 GP reported overload.") from exc
            if status == "underload":
                # An explicit underload status in the dark phase is not a
                # missing reply. A positive bright-phase GP is still required.
                utilization = 0.0
            else:
                self._emit_range(range_id, phase, previous_peak, "unverified")
                raise _RangeCheckFailed(
                    "Range check failed: no valid GP response. Point cannot be accepted."
                ) from exc
        if not math.isfinite(utilization):
            self._emit_range(range_id, phase, previous_peak, "unverified")
            raise _RangeCheckFailed("Range check failed: GP must be finite.")
        # GP was observed to stop at 50 under known overload. Normalize only
        # the guard/display; never multiply measured lux or effective intensity.
        utilization = normalized_range_use(utilization)
        peak = max(previous_peak, utilization)
        self._emit_range(
            range_id, phase, peak,
            "over_limit" if peak > RANGE_MAX_PCT else "checking",
        )
        if peak > RANGE_MAX_PCT:
            raise _RangeOverload(
                f"Range use {peak:.1f}% exceeds the {RANGE_MAX_PCT:g}% ceiling."
            )
        return peak

    def _capture_waveform(self, range_id: int, *, precheck=False):
        phase = "Range precheck" if precheck else "Acquisition"
        self._emit_range(range_id, phase)
        try:
            self.meter.configure_cw(
                integration_ms=CW_INTEGRATION_MS,
                range_id=range_id,
                sync_enabled=False,
                verify=True,
            )
        except P9710Error as exc:
            if self.meter._status_code(exc) == "overload":
                self._emit_range(range_id, phase, None, "overload")
                raise _RangeOverload(str(exc)) from exc
            self._emit_range(range_id, phase, None, "unverified")
            raise _RangeCheckFailed(str(exc)) from exc
        self.msleep(50)

        deadline = time.perf_counter() + FLASH_CAPTURE_S
        samples = []
        peak_pct = 0.0
        highest_value = -math.inf
        lowest_value = math.inf
        gp_checks = 0

        while time.perf_counter() < deadline:
            self._check_abort()
            try:
                value, _raw, t1, t2 = self.meter.read_mv(
                    attempts=1,
                    retry_delay_s=0.0,
                )
            except P9710Error as exc:
                status = self.meter._status_code(exc)
                if status == "overload":
                    self._emit_range(range_id, phase, peak_pct, "overload")
                    raise _RangeOverload("P-9710 MV reported overload.") from exc
                if status == "underload":
                    samples.append((time.perf_counter(), 0.0))
                    continue

                text = str(exc)
                if "No response" in text or "No reliable response" in text:
                    continue
                raise

            if not math.isfinite(value):
                raise _RangeCheckFailed("Non-finite MV sample: acquisition rejected.")
            # GP describes the LAST MV, so it must be read before another MV.
            # Precheck polls every sample. During acquisition check new extrema
            # in BOTH directions, including negative offset-corrected readings.
            # Other samples are bounded by directly checked extrema. Do not
            # poll once at the end (which may be the dark phase).
            if precheck or value > highest_value or value < lowest_value:
                peak_pct = self._read_checked_gp(range_id, phase, peak_pct)
                gp_checks += 1
                highest_value = max(highest_value, value)
                lowest_value = min(lowest_value, value)
            # Timestamp the MV transaction, not the following GP transaction.
            samples.append(((t1 + t2) / 2.0, max(0.0, float(value))))

        if gp_checks == 0:
            raise _RangeCheckFailed("No numeric MV/GP pair was captured.")
        return RangeCheckedCapture(samples, peak_pct, gp_checks)

    def _capture_one_flash(self):
        range_id = int(self.current_range_id)
        last_error = None

        # Remember ranges that crossed the ceiling at THIS point. This avoids
        # oscillation between e.g. R4=9.5% and R5=95%.
        rejected_ranges = set()
        for selection_attempt in range(1, MAX_RANGE_SELECTION_ATTEMPTS + 1):
            self._check_abort()
            try:
                self.status.emit(f"Checking flash range on R{range_id}")
                precheck = self._capture_waveform(range_id, precheck=True)
                analyse_single_flash(precheck.samples)
                pct = precheck.peak_utilization_pct
                # Tenfold gain is only a candidate-selection estimate. Always
                # measure GP on the new range before using it for acquisition.
                if (pct < RANGE_TARGET_MIN_PCT and pct * 10.0 <= RANGE_MAX_PCT
                        and range_id < 7 and range_id + 1 not in rejected_ranges):
                    range_id += 1
                    self.status.emit(f"Low range use — checking more sensitive R{range_id}")
                    continue
                self.status.emit(f"Acquiring flash on fixed R{range_id}")
                capture = self._capture_waveform(range_id)
                flash = analyse_single_flash(capture.samples)
                peak_pct = max(pct, capture.peak_utilization_pct)
                if capture.peak_utilization_pct <= 0.0:
                    self._emit_range(range_id, "Acquisition", None, "unverified")
                    raise _RangeCheckFailed("GP did not resolve any range use during the flash.")
                check_status = (
                    "within_target" if peak_pct >= RANGE_TARGET_MIN_PCT
                    else "low_utilization"
                )
                flash = replace(
                    flash, range_id=range_id,
                    range_peak_utilization_pct=peak_pct,
                    range_precheck_peak_pct=pct,
                    range_acquisition_peak_pct=capture.peak_utilization_pct,
                    range_check_count=precheck.gp_checks + capture.gp_checks,
                    range_selection_attempts=selection_attempt,
                    range_check_status=check_status,
                )
                self.current_range_id = range_id
                self._emit_range(range_id, "Accepted point", peak_pct, check_status)
                return flash
            except _AbortRequested:
                raise
            except _RangeOverload as exc:
                last_error = str(exc)
                rejected_ranges.add(range_id)
                if range_id <= 0:
                    raise RuntimeError(last_error)
                range_id -= 1
                self.status.emit(
                    f"{last_error} Retrying full point capture on less sensitive R{range_id}"
                )
            # Missing GP or an incomplete flash must NOT increase gain blindly.
            # The outer point retry keeps the current checked range.
            except RuntimeError:
                self.current_range_id = range_id
                self._emit_range(range_id, "Acquisition invalid", None, "unverified")
                raise

        raise RuntimeError(last_error or "Could not acquire a valid optical flash.")

    def _measure_point(
        self,
        sequence: int,
        total: int,
        c_deg: float,
        gamma_deg: float,
    ):
        last_error = None

        for attempt in range(1, MAX_POINT_ATTEMPTS + 1):
            self._check_abort()

            if attempt > 1:
                self.status.emit(
                    f"Point {sequence}/{total} • C {c_deg:+.1f}° • "
                    f"Gamma {gamma_deg:+.1f}° — retry {attempt}/{MAX_POINT_ATTEMPTS}"
                )

            try:
                self.status.emit(
                    f"Point {sequence}/{total} • C {c_deg:+.1f}° • "
                    f"Gamma {gamma_deg:+.1f}° — measuring"
                )

                flash = self._capture_one_flash()
                value = (
                    flash.cw_max_lx
                    if self.mode == MODE_CW_MAXIMUM
                    else flash.e_effective_lx
                )

                self.status.emit(
                    f"Point {sequence}/{total} acquired — "
                    f"{_format_point_value(self.mode, value, self.distance_m)}"
                )
                return float(value), flash, attempt

            except _AbortRequested:
                raise
            except Exception as exc:
                last_error = str(exc)
                if attempt < MAX_POINT_ATTEMPTS:
                    self.status.emit(
                        f"Point {sequence}/{total} acquisition invalid — "
                        f"retrying same point"
                    )
                else:
                    raise RuntimeError(
                        f"C {c_deg:+.1f}°, Gamma {gamma_deg:+.1f}° could not "
                        f"produce a valid flash after {MAX_POINT_ATTEMPTS} attempts. "
                        f"Last error: {last_error}"
                    ) from exc

        raise RuntimeError(last_error or "Point acquisition failed.")

    def _return_axes_to_zero_after_abort(self):
        """Best-effort controlled return to Session Zero after an operator abort."""

        errors = []

        try:
            self.status.emit("Abort requested — returning Gamma to 0°")
            self.motion.move_absolute(GAMMA, 0.0)
        except Exception as exc:
            errors.append(f"Gamma: {exc}")

        try:
            self.status.emit("Abort requested — returning C to 0°")
            self.motion.move_absolute(C_AXIS, 0.0)
        except Exception as exc:
            errors.append(f"C: {exc}")

        return errors

    def _estimated_move_seconds(self, axis, delta_degree: float) -> float:
        delta_degree = abs(float(delta_degree))
        if delta_degree <= 0.01:
            return 0.0

        try:
            motor_rpm = self.motion.expected_speed_raw(axis) / 10.0
        except Exception:
            motor_rpm = 0.0

        if motor_rpm <= 0.0:
            return max(0.5, delta_degree)

        output_deg_per_second = motor_rpm * 6.0 / axis.gear_ratio
        if output_deg_per_second <= 0.0:
            return max(0.5, delta_degree)

        # Small allowance for acceleration/deceleration and command overhead.
        return delta_degree / output_deg_per_second + 0.6

    def _predicted_plan(self, start_c: float, start_gamma: float):
        point_estimates = []
        previous_c = float(start_c)
        previous_gamma = float(start_gamma)

        for c_deg, gamma_deg in self.points:
            duration = (
                self._estimated_move_seconds(C_AXIS, c_deg - previous_c)
                + self._estimated_move_seconds(GAMMA, gamma_deg - previous_gamma)
                + SETTLE_S
                + FLASH_CAPTURE_S
                + FLASH_CAPTURE_S  # independent GP range precheck
                + 0.15
            )
            point_estimates.append(duration)
            previous_c = c_deg
            previous_gamma = gamma_deg

        gamma_return_s = self._estimated_move_seconds(GAMMA, -previous_gamma)
        c_return_s = self._estimated_move_seconds(C_AXIS, -previous_c)
        return point_estimates, gamma_return_s, c_return_s

    def run(self):
        started = datetime.now().astimezone()
        csv_path = None
        results = []
        diagnostic_stream = None
        previous_trace = getattr(self.meter, "trace_callback", None)

        try:
            if not self.points:
                raise RuntimeError("No measurement points were generated.")
            if self.distance_m <= 0.0:
                raise RuntimeError("Measurement distance must be greater than zero.")
            if self.mode not in (MODE_I_EFFECTIVE, MODE_CW_MAXIMUM):
                raise RuntimeError(f"Unsupported V2 measurement mode: {self.mode}")

            csv_path = self.output_path
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_path = csv_path.with_name(csv_path.stem + "_diagnostics.csv")
            diagnostic_stream = diagnostic_path.open("w", newline="", encoding="utf-8")
            diagnostic_writer = csv.DictWriter(diagnostic_stream, fieldnames=[
                "point", "c_deg", "gamma_deg", "phase", "requested_range",
                "command", "raw_reply", "started_perf_s", "finished_perf_s",
            ])
            diagnostic_writer.writeheader()
            diagnostic_stream.flush()
            self._diagnostic_point = {}

            def trace_reply(command, raw, t1, t2):
                diagnostic_writer.writerow({
                    **self._diagnostic_point,
                    "phase": getattr(self, "_diagnostic_phase", "Preparing"),
                    "requested_range": getattr(self, "_diagnostic_range", ""),
                    "command": command, "raw_reply": raw,
                    "started_perf_s": t1, "finished_perf_s": t2,
                })
                if command != "MV":
                    diagnostic_stream.flush()

            self.meter.trace_callback = trace_reply

            fieldnames = [
                "lumigon_format",
                "schema_version",
                "sample_id",
                "sample_count",
                "run_started_at",
                "point",
                "c_deg",
                "gamma_deg",
                "mode",
                "distance_m",
                "sample_1",
                "sample_2",
                "sample_3",
                "accepted_e_effective_lx",
                "accepted_i_effective_cd",
                "accepted_cw_maximum_lx",
                "max_deviation_pct",
                "tolerance_pct",
                "range_ids",
                "range_peak_utilization_pct",
                "range_precheck_peak_pct",
                "range_acquisition_peak_pct",
                "range_raw_gp_peak",
                "range_raw_gp_precheck",
                "range_raw_gp_acquisition",
                "range_gp_saturation_reference",
                "range_gp_reference_basis",
                "range_check_status",
                "range_check_method",
                "range_check_count",
                "range_selection_attempts",
                "mean_baseline_lx",
                "mean_net_peak_lx",
                "mean_pulse_duration_ms",
                "mean_sample_interval_ms",
                "integral_lx_s",
                "acquisition_attempt",
                "validation_attempt",
            ]

            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                stream.flush()

                total = len(self.points)
                start_c = self.motion.get_current_angle(C_AXIS)
                start_gamma = self.motion.get_current_angle(GAMMA)
                point_estimates, gamma_return_s, c_return_s = self._predicted_plan(
                    start_c,
                    start_gamma,
                )
                predicted_total_s = (
                    sum(point_estimates) + gamma_return_s + c_return_s
                )
                run_clock = time.monotonic()
                predicted_completed_s = 0.0
                timing_scale = 1.0

                self.progress.emit(
                    {
                        "completed": 0,
                        "total": total,
                        "percent": 0,
                        "remaining_s": predicted_total_s,
                    }
                )

                for sequence, (c_deg, gamma_deg) in enumerate(self.points, start=1):
                    self._check_abort()
                    self._diagnostic_point = {
                        "point": sequence, "c_deg": c_deg, "gamma_deg": gamma_deg,
                    }
                    self._emit_range(self.current_range_id, "Preparing next point")

                    current_c = self.motion.get_current_angle(C_AXIS)
                    if abs(current_c - c_deg) > 0.01:
                        self.status.emit(
                            f"Point {sequence}/{total} — moving C to {c_deg:+.1f}°"
                        )
                        self.motion.move_absolute(C_AXIS, c_deg)

                    self._check_abort()

                    current_gamma = self.motion.get_current_angle(GAMMA)
                    if abs(current_gamma - gamma_deg) > 0.01:
                        self.status.emit(
                            f"Point {sequence}/{total} • C {c_deg:+.1f}° "
                            f"— moving Gamma to {gamma_deg:+.1f}°"
                        )
                        self.motion.move_absolute(GAMMA, gamma_deg)

                    self._wait_interruptible(SETTLE_S)

                    value, flash, acquisition_attempt = self._measure_point(
                        sequence,
                        total,
                        c_deg,
                        gamma_deg,
                    )

                    accepted_e_lx = (
                        value if self.mode == MODE_I_EFFECTIVE else None
                    )
                    accepted_i_cd = (
                        value * self.distance_m * self.distance_m
                        if accepted_e_lx is not None
                        else None
                    )
                    accepted_cw_lx = (
                        value if self.mode == MODE_CW_MAXIMUM else None
                    )

                    result = {
                        "lumigon_format": "Lumigon Measurement V2",
                        "schema_version": "2.3",
                        "sample_id": self.sample_id,
                        "sample_count": 1,
                        "run_started_at": started.isoformat(),
                        "point": sequence,
                        "c_deg": c_deg,
                        "gamma_deg": gamma_deg,
                        "mode": self.mode,
                        "distance_m": self.distance_m,
                        "sample_1": value,
                        "sample_2": "",
                        "sample_3": "",
                        "accepted_e_effective_lx": accepted_e_lx,
                        "accepted_i_effective_cd": accepted_i_cd,
                        "accepted_cw_maximum_lx": accepted_cw_lx,
                        "max_deviation_pct": "",
                        "tolerance_pct": "",
                        "range_ids": str(flash.range_id),
                        "range_peak_utilization_pct": flash.range_peak_utilization_pct,
                        "range_precheck_peak_pct": flash.range_precheck_peak_pct,
                        "range_acquisition_peak_pct": flash.range_acquisition_peak_pct,
                        "range_raw_gp_peak": flash.range_peak_utilization_pct * GP_SATURATION_REFERENCE / 100.0,
                        "range_raw_gp_precheck": flash.range_precheck_peak_pct * GP_SATURATION_REFERENCE / 100.0,
                        "range_raw_gp_acquisition": flash.range_acquisition_peak_pct * GP_SATURATION_REFERENCE / 100.0,
                        "range_gp_saturation_reference": GP_SATURATION_REFERENCE,
                        "range_gp_reference_basis": GP_REFERENCE_BASIS,
                        "range_check_status": flash.range_check_status,
                        "range_check_method": "GP precheck + acquisition extrema",
                        "range_check_count": flash.range_check_count,
                        "range_selection_attempts": flash.range_selection_attempts,
                        "mean_baseline_lx": flash.baseline_lx,
                        "mean_net_peak_lx": flash.net_peak_lx,
                        "mean_pulse_duration_ms": flash.pulse_duration_ms,
                        "mean_sample_interval_ms": flash.median_dt_ms,
                        "integral_lx_s": flash.integral_lx_s,
                        "acquisition_attempt": acquisition_attempt,
                        # Retained for backward-compatible V2 CSV parsing.
                        "validation_attempt": acquisition_attempt,
                    }

                    writer.writerow(result)
                    stream.flush()
                    results.append(result)
                    self.point_accepted.emit(dict(result))

                    if self.mode == MODE_I_EFFECTIVE:
                        accepted_text = (
                            f"E-effective {accepted_e_lx:.4f} lx • "
                            f"I-effective {accepted_i_cd:.2f} cd"
                        )
                    else:
                        accepted_text = f"CW maximum {accepted_cw_lx:.4f} lx"

                    self.status.emit(
                        f"Point {sequence}/{total} accepted — {accepted_text}"
                    )

                    predicted_completed_s += point_estimates[sequence - 1]
                    elapsed_s = max(0.0, time.monotonic() - run_clock)
                    if predicted_completed_s > 0.0:
                        timing_scale = max(
                            0.25,
                            min(4.0, elapsed_s / predicted_completed_s),
                        )
                    remaining_predicted_s = (
                        sum(point_estimates[sequence:])
                        + gamma_return_s
                        + c_return_s
                    )
                    self.progress.emit(
                        {
                            "completed": sequence,
                            "total": total,
                            "percent": 95.0 * sequence / total,
                            "remaining_s": remaining_predicted_s * timing_scale,
                        }
                    )

                self._check_abort()
                self.status.emit("Measurement complete — returning Gamma to 0°")
                self.motion.move_absolute(GAMMA, 0.0)
                self.progress.emit(
                    {
                        "completed": total,
                        "total": total,
                        "percent": 97,
                        "remaining_s": c_return_s * timing_scale,
                    }
                )

                self._check_abort()
                self.status.emit("Returning C to 0°")
                self.motion.move_absolute(C_AXIS, 0.0)
                self.progress.emit(
                    {
                        "completed": total,
                        "total": total,
                        "percent": 100,
                        "remaining_s": 0.0,
                    }
                )

            self.completed.emit(
                {
                    "started_at": started.isoformat(),
                    "completed_at": datetime.now().astimezone().isoformat(),
                    "csv_path": str(csv_path),
                    "diagnostics_path": str(diagnostic_path),
                    "mode": self.mode,
                    "points": results,
                }
            )

        except _AbortRequested:
            return_errors = self._return_axes_to_zero_after_abort()
            partial_text = f" Partial CSV: {csv_path}" if csv_path else ""

            if return_errors:
                self.aborted.emit(
                    "Measurement aborted, but return-to-zero was incomplete: "
                    + " | ".join(return_errors)
                    + partial_text
                )
            else:
                self.aborted.emit(
                    "Measurement aborted — Gamma and C returned to 0°."
                    + partial_text
                )
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.meter.trace_callback = previous_trace
            if diagnostic_stream is not None:
                diagnostic_stream.close()


def attach_measurement_runtime_v2(window):
    """Connect the V2 Measurement page to MotionController and the P-9710."""

    start_button = getattr(window, "measurement_v2_start_button", None)
    status_label = getattr(window, "measurement_v2_status_label", None)

    if start_button is None or status_label is None:
        raise RuntimeError("V2 Measurement controls are not available.")

    holder = {"worker": None, "timer_was_active": False}

    editor_controls = [
        getattr(window, "measurement_v2_sample_id_edit", None),
        getattr(window, "measurement_v2_distance_spin", None),
        getattr(window, "measurement_v2_mode_combo", None),
        getattr(window, "measurement_v2_file_name_edit", None),
        getattr(window, "measurement_v2_save_folder_edit", None),
        getattr(window, "measurement_v2_browse_folder_button", None),
        getattr(window, "measurement_v2_c_start", None),
        getattr(window, "measurement_v2_c_end", None),
        getattr(window, "measurement_v2_c_step", None),
        getattr(window, "measurement_v2_gamma_start", None),
        getattr(window, "measurement_v2_gamma_end", None),
        getattr(window, "measurement_v2_gamma_step", None),
    ]

    def set_editor_enabled(enabled: bool):
        for control in editor_controls:
            if control is not None:
                control.setEnabled(bool(enabled))

    def set_tabs_enabled(enabled: bool):
        tabs = getattr(window, "main_tabs", None)
        if tabs is None:
            return
        for index in (0, 1):
            if index < tabs.count():
                tabs.setTabEnabled(index, bool(enabled))

    def precheck():
        if not getattr(window.modbus, "is_connected", False):
            return "Connect the two servo drives in Motor Control first."

        if window.gamma_zero_puu is None or window.c_zero_puu is None:
            return "Set Zero for both axes in Motor Control before starting."

        manual_worker = getattr(window, "manual_motion_worker", None)
        if manual_worker is not None and manual_worker.isRunning():
            return "A manual axis movement is still running."

        meter_holder = getattr(window, "p9710_meter_holder", None)
        meter = None if meter_holder is None else meter_holder.get("meter")
        if meter is None or not meter.is_connected:
            return "Connect the P-9710 in the Luxmeter tab first."

        p9710_worker_holder = getattr(window, "p9710_mode_worker_holder", None)
        if (
            p9710_worker_holder is not None
            and p9710_worker_holder.get("worker") is not None
        ):
            return "A P-9710 Luxmeter operation is already running."

        c_start = window.measurement_v2_c_start.value()
        c_end = window.measurement_v2_c_end.value()
        gamma_start = window.measurement_v2_gamma_start.value()
        gamma_end = window.measurement_v2_gamma_end.value()

        c_limit = window.motion.axis_limit_deg(C_AXIS)
        gamma_limit = window.motion.axis_limit_deg(GAMMA)
        if max(abs(c_start), abs(c_end)) > c_limit + 1e-9:
            return (
                f"Requested C range exceeds the current Motion Control limit "
                f"of ±{c_limit:g}°."
            )

        if max(abs(gamma_start), abs(gamma_end)) > gamma_limit + 1e-9:
            return (
                f"Requested Gamma range exceeds the current Motion Control limit "
                f"of ±{gamma_limit:g}°."
            )

        return None

    def finish_worker():
        worker = holder["worker"]
        if worker is not None:
            worker.deleteLater()
        holder["worker"] = None
        window.measurement_v2_worker = None

        set_editor_enabled(True)
        set_tabs_enabled(True)
        start_button.setText("Start Measurement")
        start_button.setEnabled(True)

        if holder["timer_was_active"] and window.modbus.is_connected:
            window.timer.start()
        holder["timer_was_active"] = False

    def on_point(result):
        item = dict(result)
        window.measurement_v2_results.append(item)
        graph = getattr(window, "measurement_v2_graph", None)
        if graph is not None:
            graph.add_point(item)

    def on_range(payload):
        display = getattr(window, "measurement_v2_range_display", None)
        if display is not None:
            display.update_range(payload)
        dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if dialog is not None:
            dialog.range_display.update_range(payload)

    def on_progress(payload):
        dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if dialog is None:
            return
        dialog.update_progress(
            completed=payload.get("completed", 0),
            total=payload.get("total", 0),
            percent=payload.get("percent"),
            remaining_s=payload.get("remaining_s"),
        )

    def request_worker_abort():
        running = holder["worker"]
        if running is None or not running.isRunning():
            return
        running.requestInterruption()
        start_button.setEnabled(False)
        status_label.setText(
            "Abort requested — completing the current safe operation, then returning both axes to 0°…"
        )

    def on_completed(payload):
        window.measurement_v2_last_run = payload
        points = len(payload.get("points") or [])
        path = payload.get("csv_path") or ""
        status_label.setText(
            f"Complete — {points} points measured and saved • {path}"
        )
        status_label.setStyleSheet(
            "color:#55EFC4; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:6px 10px; font-weight:700;"
        )
        dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if dialog is not None:
            dialog.finish_success(
                f"Complete — {points} points measured and saved."
            )

        visualization = getattr(window, "visualization_workspace_controller", None)
        if visualization is not None and path:
            visualization.load_path(path, show_errors=True)

    def on_aborted(message):
        status_label.setText(message)
        status_label.setStyleSheet(
            "color:#E7C76A; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:6px 10px; font-weight:700;"
        )
        dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if dialog is not None:
            dialog.finish_aborted(message)

    def on_failed(message):
        status_label.setText("Measurement stopped — error")
        status_label.setStyleSheet(
            "color:#FF7675; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:6px 10px; font-weight:700;"
        )
        dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if dialog is not None:
            dialog.finish_failed(f"Measurement stopped — {message}")
        QMessageBox.critical(window, "V2 Measurement Error", message)

    def start_or_abort():
        running = holder["worker"]
        if running is not None:
            if running.isRunning():
                dialog = getattr(window, "measurement_v2_progress_dialog", None)
                if dialog is not None:
                    dialog.request_abort()
                else:
                    request_worker_abort()
            return

        problem = precheck()
        if problem:
            QMessageBox.warning(window, "V2 Measurement", problem)
            return

        try:
            c_values = _axis_values(
                window.measurement_v2_c_start.value(),
                window.measurement_v2_c_end.value(),
                window.measurement_v2_c_step.value(),
            )
            gamma_values = _axis_values(
                window.measurement_v2_gamma_start.value(),
                window.measurement_v2_gamma_end.value(),
                window.measurement_v2_gamma_step.value(),
            )
        except Exception as exc:
            QMessageBox.warning(window, "V2 Measurement", str(exc))
            return

        points = build_serpentine_points(c_values, gamma_values)
        if not points:
            QMessageBox.warning(
                window,
                "V2 Measurement",
                "The selected angular ranges produced no measurement points.",
            )
            return

        mode = str(window.measurement_v2_mode_combo.currentData())
        distance_m = float(window.measurement_v2_distance_spin.value())
        sample_id = window.measurement_v2_sample_id_edit.text().strip() or "sample"

        save_folder_text = window.measurement_v2_save_folder_edit.text().strip()
        save_dir = Path(save_folder_text or measurement_data_directory()).expanduser()
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.warning(
                window,
                "V2 Measurement",
                f"Could not create or access the selected save folder:\n\n{exc}",
            )
            return

        requested_name = window.measurement_v2_file_name_edit.text().strip()
        if requested_name:
            filename = Path(requested_name).name
            if not filename.lower().endswith(".csv"):
                filename += ".csv"
        else:
            stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
            mode_tag = (
                "I_effective"
                if mode == MODE_I_EFFECTIVE
                else "CW_maximum"
            )
            filename = f"{_safe_filename(sample_id)}_{mode_tag}_{stamp}.csv"

        output_path = save_dir / filename

        if output_path.exists():
            overwrite = QMessageBox.question(
                window,
                "Overwrite Measurement File?",
                f"The selected file already exists:\n\n{output_path}\n\nOverwrite it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if overwrite != QMessageBox.Yes:
                return

        answer = QMessageBox.question(
            window,
            "Start Automatic Measurement",
            f"Start {len(points)} points?\n\n"
            f"C: {c_values[0]:+.1f}° to {c_values[-1]:+.1f}°\n"
            f"Gamma: {gamma_values[0]:+.1f}° to {gamma_values[-1]:+.1f}°\n"
            f"Mode: {window.measurement_v2_mode_combo.currentText()}\n"
            f"Distance: {distance_m:.2f} m\n"
            f"File: {output_path}\n\n"
            "Each point uses one valid captured flash. Invalid or incomplete "
            "acquisitions are retried automatically. "
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous()

        meter = window.p9710_meter_holder["meter"]

        holder["timer_was_active"] = bool(window.timer.isActive())
        if holder["timer_was_active"]:
            window.timer.stop()

        set_editor_enabled(False)
        set_tabs_enabled(False)
        start_button.setText("Abort Measurement")
        start_button.setEnabled(True)
        status_label.setStyleSheet(
            "color:#9DD5F3; background-color:#142A38; "
            "border:1px solid #2C617E; border-radius:5px; "
            "padding:6px 10px; font-weight:700;"
        )
        status_label.setText(
            f"Starting — {len(points)} points • preparing C/Gamma scan"
        )

        window.measurement_v2_results = []
        window.measurement_v2_last_run = None
        window.measurement_v2_range_display.reset()

        graph = getattr(window, "measurement_v2_graph", None)
        if graph is not None:
            graph.reset(
                mode=mode,
                distance_m=distance_m,
                gamma_min=gamma_values[0],
                gamma_max=gamma_values[-1],
            )

        worker = MeasurementV2Worker(
            motion=window.motion,
            meter=meter,
            points=points,
            mode=mode,
            distance_m=distance_m,
            sample_id=sample_id,
            output_path=output_path,
            parent=window,
        )
        holder["worker"] = worker
        window.measurement_v2_worker = worker

        previous_dialog = getattr(window, "measurement_v2_progress_dialog", None)
        if previous_dialog is not None:
            try:
                previous_dialog.close()
                previous_dialog.deleteLater()
            except Exception:
                pass

        progress_dialog = MeasurementProgressDialogV2(window)
        window.measurement_v2_progress_dialog = progress_dialog
        progress_dialog.abort_requested.connect(request_worker_abort)
        progress_dialog.begin(
            total_points=len(points),
            initial_status=(
                f"Starting — {len(points)} points • preparing C/Gamma scan"
            ),
        )

        worker.status.connect(status_label.setText)
        worker.status.connect(progress_dialog.set_status)
        worker.progress.connect(on_progress)
        worker.point_accepted.connect(on_point)
        worker.range_updated.connect(on_range)
        worker.completed.connect(on_completed)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.finished.connect(finish_worker)
        worker.start()

    start_button.clicked.connect(start_or_abort)
    start_button.setEnabled(True)

    window.measurement_v2_worker = None
    window.measurement_v2_results = []
    window.measurement_v2_last_run = None
    window.measurement_v2_progress_dialog = None
    return start_button
