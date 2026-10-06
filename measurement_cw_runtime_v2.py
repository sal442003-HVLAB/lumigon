"""Version 2 CW acquisition check for the Measurement workspace.

The first V2 acquisition step deliberately does not move either goniometer axis.
It uses the already-connected P-9710, acquires the optical waveform in fast CW
mode (SN1) on fixed range R5, extracts five complete flashes, and checks whether
their sampled CW maxima and timing are mutually consistent.

This is a commissioning sanity check, not a formal acceptance criterion.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QMessageBox

from p9710 import P9710Error


FIXED_RANGE_ID = 5
INTEGRATION_MS = 0.1
TARGET_FLASHES = 5
CAPTURE_SECONDS = 27.0
RISE_FRACTION = 0.30
FALL_FRACTION = 0.20
MIN_SIGNAL_SPAN_LX = 0.05
CONSISTENCY_CV_LIMIT_PCT = 5.0


@dataclass(frozen=True)
class CwFiveFlashResult:
    flash_count: int
    maxima_lx: tuple[float, ...]
    mean_max_lx: float
    stdev_max_lx: float
    cv_max_pct: float
    period_s: float
    duration_ms: float
    sample_interval_ms: float
    baseline_lx: float
    optical_peak_lx: float
    consistent: bool


def _percentile(values, fraction: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0

    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]

    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _crossing_time(t0, v0, t1, v1, threshold):
    if t1 <= t0 or v1 == v0:
        return t1
    fraction = (threshold - v0) / (v1 - v0)
    fraction = max(0.0, min(1.0, fraction))
    return t0 + fraction * (t1 - t0)


def analyse_five_flashes(samples):
    if len(samples) < 50:
        raise RuntimeError("Too few CW samples were captured.")

    values = [value for _t, value in samples]
    baseline = _percentile(values, 0.20)
    optical_peak = _percentile(values, 0.95)
    span = optical_peak - baseline

    if not math.isfinite(span) or span < MIN_SIGNAL_SPAN_LX:
        raise RuntimeError(
            f"Optical modulation is too small for flash analysis "
            f"(baseline {baseline:.4g} lx, peak {optical_peak:.4g} lx)."
        )

    rise_threshold = baseline + RISE_FRACTION * span
    fall_threshold = baseline + FALL_FRACTION * span

    complete = []
    in_pulse = False
    rise_time = None
    pulse_values = []

    previous_t, previous_v = samples[0]

    for t_now, value_now in samples[1:]:
        if not in_pulse:
            if previous_v < rise_threshold <= value_now:
                rise_time = _crossing_time(
                    previous_t,
                    previous_v,
                    t_now,
                    value_now,
                    rise_threshold,
                )
                pulse_values = [value_now]
                in_pulse = True
        else:
            pulse_values.append(value_now)
            if previous_v > fall_threshold >= value_now:
                fall_time = _crossing_time(
                    previous_t,
                    previous_v,
                    t_now,
                    value_now,
                    fall_threshold,
                )
                if rise_time is not None and fall_time > rise_time and pulse_values:
                    complete.append(
                        {
                            "rise_s": rise_time,
                            "fall_s": fall_time,
                            "duration_s": fall_time - rise_time,
                            "max_lx": max(pulse_values),
                        }
                    )
                rise_time = None
                pulse_values = []
                in_pulse = False

        previous_t, previous_v = t_now, value_now

    if len(complete) < TARGET_FLASHES:
        raise RuntimeError(
            f"Only {len(complete)} complete flashes were captured; "
            f"{TARGET_FLASHES} are required. Run the check again."
        )

    flashes = complete[:TARGET_FLASHES]
    maxima = [item["max_lx"] for item in flashes]
    durations = [item["duration_s"] for item in flashes]
    rises = [item["rise_s"] for item in flashes]

    periods = [
        later - earlier
        for earlier, later in zip(rises, rises[1:])
        if later > earlier
    ]
    if not periods:
        raise RuntimeError("Could not calculate flash period from the CW capture.")

    sample_intervals = [
        later[0] - earlier[0]
        for earlier, later in zip(samples, samples[1:])
        if later[0] > earlier[0]
    ]

    mean_max = statistics.mean(maxima)
    stdev_max = statistics.pstdev(maxima) if len(maxima) > 1 else 0.0
    cv_max = (stdev_max / mean_max * 100.0) if mean_max > 0.0 else float("inf")

    return CwFiveFlashResult(
        flash_count=len(flashes),
        maxima_lx=tuple(maxima),
        mean_max_lx=mean_max,
        stdev_max_lx=stdev_max,
        cv_max_pct=cv_max,
        period_s=statistics.median(periods),
        duration_ms=statistics.median(durations) * 1000.0,
        sample_interval_ms=(
            statistics.median(sample_intervals) * 1000.0
            if sample_intervals
            else 0.0
        ),
        baseline_lx=baseline,
        optical_peak_lx=optical_peak,
        consistent=bool(math.isfinite(cv_max) and cv_max <= CONSISTENCY_CV_LIMIT_PCT),
    )


class CwFiveFlashWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)

    def __init__(self, meter, parent=None):
        super().__init__(parent)
        self.meter = meter

    def run(self):
        try:
            self.meter.configure_cw(
                integration_ms=INTEGRATION_MS,
                range_id=FIXED_RANGE_ID,
                sync_enabled=False,
            )
            time.sleep(0.10)

            deadline = time.perf_counter() + CAPTURE_SECONDS
            samples = []

            while time.perf_counter() < deadline:
                if self.isInterruptionRequested():
                    return

                try:
                    value, _raw, t1, t2 = self.meter.read_mv(
                        attempts=1,
                        retry_delay_s=0.0,
                    )
                except P9710Error as exc:
                    status = self.meter._status_code(exc)

                    if status == "underload":
                        # The OFF state may legitimately be below the fixed R5 range.
                        samples.append((time.perf_counter(), 0.0))
                        continue

                    if status == "overload":
                        raise RuntimeError(
                            "R5 overloaded during the flash. "
                            "The V2 CW check must use a less-sensitive range for this source."
                        ) from exc

                    text = str(exc)
                    if "No response" in text or "No reliable response" in text:
                        continue
                    raise

                t_mid = (t1 + t2) / 2.0
                if math.isfinite(value):
                    samples.append((t_mid, max(0.0, float(value))))

            self.measured.emit(analyse_five_flashes(samples))

        except Exception as exc:
            self.failed.emit(str(exc))


def attach_measurement_cw_runtime_v2(window):
    """Connect the minimal Measurement CW check to the existing P-9710."""

    button = getattr(window, "measurement_v2_cw_check_button", None)
    status_label = getattr(window, "measurement_v2_cw_status_label", None)
    max_label = getattr(window, "measurement_v2_cw_max_label", None)
    consistency_label = getattr(
        window,
        "measurement_v2_cw_consistency_label",
        None,
    )
    timing_label = getattr(window, "measurement_v2_cw_timing_label", None)

    if None in (button, status_label, max_label, consistency_label, timing_label):
        raise RuntimeError("V2 Measurement CW controls are not available.")

    holder = {"worker": None}

    def finish_worker():
        worker = holder["worker"]
        if worker is not None:
            worker.deleteLater()
        holder["worker"] = None
        window.measurement_v2_cw_worker = None
        button.setEnabled(True)

    def failed(message):
        status_label.setText("CW check failed")
        status_label.setStyleSheet("color:#FF7675; font-weight:700;")
        QMessageBox.critical(window, "V2 CW Acquisition Check", message)

    def completed(result: CwFiveFlashResult):
        values_text = ", ".join(f"{value:.3f}" for value in result.maxima_lx)
        max_label.setText(
            f"CW max (5 flashes): {result.mean_max_lx:.3f} lx mean  •  "
            f"values [{values_text}]"
        )

        verdict = "CONSISTENT" if result.consistent else "REVIEW"
        consistency_label.setText(
            f"Consistency: {verdict}  •  CV {result.cv_max_pct:.2f}%  •  "
            f"σ {result.stdev_max_lx:.3f} lx"
        )
        consistency_label.setStyleSheet(
            "color:#55EFC4; background:#14212B; border:1px solid #2B4050; "
            "border-radius:4px; padding:6px 9px; font-weight:700;"
            if result.consistent
            else
            "color:#E7C76A; background:#14212B; border:1px solid #2B4050; "
            "border-radius:4px; padding:6px 9px; font-weight:700;"
        )

        timing_label.setText(
            f"Timing: period {result.period_s:.4f} s  •  "
            f"ON {result.duration_ms:.1f} ms  •  "
            f"sample Δt {result.sample_interval_ms:.1f} ms"
        )

        status_label.setText(
            f"Complete — {result.flash_count} full flashes captured on R{FIXED_RANGE_ID}"
        )
        status_label.setStyleSheet("color:#55EFC4; font-weight:700;")

        window.measurement_v2_last_cw_check = result

    def start_check():
        if holder["worker"] is not None:
            return

        meter_holder = getattr(window, "p9710_meter_holder", None)
        meter = None if meter_holder is None else meter_holder.get("meter")

        if meter is None or not meter.is_connected:
            QMessageBox.warning(
                window,
                "V2 CW Acquisition Check",
                "Connect the P-9710 in the Luxmeter tab first.",
            )
            return

        mode_worker_holder = getattr(window, "p9710_mode_worker_holder", None)
        if (
            mode_worker_holder is not None
            and mode_worker_holder.get("worker") is not None
        ):
            QMessageBox.warning(
                window,
                "V2 CW Acquisition Check",
                "Another P-9710 measurement is already running.",
            )
            return

        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous()

        button.setEnabled(False)
        status_label.setText(
            f"Reading CW waveform — collecting {TARGET_FLASHES} complete flashes…"
        )
        status_label.setStyleSheet("color:#40B9D0; font-weight:700;")
        max_label.setText("CW max: measuring…")
        consistency_label.setText("Consistency: measuring…")
        timing_label.setText("Timing: measuring…")

        worker = CwFiveFlashWorker(meter, parent=window)
        holder["worker"] = worker
        window.measurement_v2_cw_worker = worker

        worker.measured.connect(completed)
        worker.failed.connect(failed)
        worker.finished.connect(finish_worker)
        worker.start()

    button.clicked.connect(start_check)

    window.measurement_v2_cw_worker = None
    window.measurement_v2_last_cw_check = None
    return button
