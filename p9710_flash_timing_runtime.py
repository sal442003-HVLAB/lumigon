"""Pulse timing diagnostic for the connected Gigahertz-Optik P-9710.

This tool is intentionally diagnostic.  It samples fast CW values with SN1
(0.1 ms integration), keeps one manual range fixed for the whole capture, and
estimates:
- flash period from consecutive rising edges;
- optical ON duration from threshold crossings;
- duty cycle;
- effective sampling interval.

The ON duration is an optical threshold-width estimate, not an oscilloscope
electrical pulse-width measurement.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from p9710 import P9710Error


DEFAULT_CAPTURE_S = 15.0
DEFAULT_RANGE = 5
RISE_FRACTION = 0.30
FALL_FRACTION = 0.20
MIN_SIGNAL_SPAN_LX = 0.05


@dataclass(frozen=True)
class PulseTimingResult:
    period_s: float
    duration_s: float
    duty_cycle_pct: float
    pulses: int
    sample_interval_ms: float
    threshold_rise_lx: float
    threshold_fall_lx: float
    baseline_lx: float
    peak_lx: float


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


def _analyse_samples(samples):
    if len(samples) < 20:
        raise RuntimeError("Too few P-9710 samples were captured.")

    values = [value for _t, value in samples]
    baseline = _percentile(values, 0.20)
    peak = _percentile(values, 0.95)
    span = peak - baseline
    if not math.isfinite(span) or span < MIN_SIGNAL_SPAN_LX:
        raise RuntimeError(
            f"Flash modulation is too small for timing analysis "
            f"(baseline {baseline:.4g} lx, peak {peak:.4g} lx)."
        )

    rise_threshold = baseline + RISE_FRACTION * span
    fall_threshold = baseline + FALL_FRACTION * span

    rising_edges = []
    pulse_widths = []
    in_pulse = False
    rise_time = None

    previous_t, previous_v = samples[0]
    for t_now, value_now in samples[1:]:
        if not in_pulse:
            if previous_v < rise_threshold <= value_now:
                rise_time = _crossing_time(
                    previous_t, previous_v, t_now, value_now, rise_threshold
                )
                rising_edges.append(rise_time)
                in_pulse = True
        else:
            if previous_v > fall_threshold >= value_now:
                fall_time = _crossing_time(
                    previous_t, previous_v, t_now, value_now, fall_threshold
                )
                if rise_time is not None and fall_time > rise_time:
                    pulse_widths.append(fall_time - rise_time)
                rise_time = None
                in_pulse = False

        previous_t, previous_v = t_now, value_now

    periods = [
        later - earlier
        for earlier, later in zip(rising_edges, rising_edges[1:])
        if later > earlier
    ]
    if len(periods) < 2:
        raise RuntimeError(
            "Fewer than three reliable flash rising edges were captured. "
            "Increase Capture time or select a usable fixed range."
        )
    if not pulse_widths:
        raise RuntimeError(
            "Rising edges were found, but no complete ON duration was captured."
        )

    intervals = [
        later[0] - earlier[0]
        for earlier, later in zip(samples, samples[1:])
        if later[0] > earlier[0]
    ]

    period_s = statistics.median(periods)
    duration_s = statistics.median(pulse_widths)
    sample_interval_s = statistics.median(intervals) if intervals else 0.0

    return PulseTimingResult(
        period_s=period_s,
        duration_s=duration_s,
        duty_cycle_pct=(duration_s / period_s) * 100.0,
        pulses=len(rising_edges),
        sample_interval_ms=sample_interval_s * 1000.0,
        threshold_rise_lx=rise_threshold,
        threshold_fall_lx=fall_threshold,
        baseline_lx=baseline,
        peak_lx=peak,
    )


class PulseTimingWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, meter, *, range_id: int, capture_s: float, parent=None):
        super().__init__(parent)
        self.meter = meter
        self.range_id = max(0, min(7, int(range_id)))
        self.capture_s = max(5.0, float(capture_s))

    def run(self):
        try:
            # Fixed range is essential: range changes would distort the waveform
            # amplitude and make threshold timing ambiguous.
            self.meter.configure_flash_detection(range_id=self.range_id)
            deadline = time.perf_counter() + self.capture_s
            samples = []
            status_count = 0

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
                        # OFF state can legitimately be below the selected range.
                        now = time.perf_counter()
                        samples.append((now, 0.0))
                        status_count += 1
                        continue
                    if status == "overload":
                        raise RuntimeError(
                            f"R{self.range_id} overloads during the flash. "
                            "Select a lower-sensitivity range (smaller R number)."
                        ) from exc
                    # A single transport miss should not invalidate a long timing
                    # capture; simply skip it and continue.
                    if "No reliable response" in str(exc) or "No response" in str(exc):
                        continue
                    raise

                t_mid = (t1 + t2) / 2.0
                if math.isfinite(value):
                    samples.append((t_mid, max(0.0, float(value))))

            if len(samples) < 20:
                raise RuntimeError("Not enough timing samples were collected.")

            result = _analyse_samples(samples)
            self.measured.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


def attach_p9710_flash_timing_runtime(window):
    if getattr(window, "p9710_flash_timing_box", None) is not None:
        return window.p9710_flash_timing_box

    p9710_box = getattr(window, "p9710_effective_box", None)
    if p9710_box is None or p9710_box.parentWidget() is None:
        raise RuntimeError("P-9710 workspace must exist before flash timing is attached.")

    parent = p9710_box.parentWidget()
    layout = parent.layout()
    if layout is None:
        raise RuntimeError("P-9710 workspace parent layout is not available.")

    box = QGroupBox("Flash Timing Diagnostic")
    grid = QGridLayout(box)
    grid.setContentsMargins(12, 10, 12, 10)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(6)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 0)
    grid.setColumnStretch(2, 0)
    grid.setColumnStretch(3, 1)

    range_spin = QSpinBox()
    range_spin.setRange(0, 7)
    range_spin.setValue(DEFAULT_RANGE)
    range_spin.setFixedWidth(110)

    capture_spin = QDoubleSpinBox()
    capture_spin.setRange(5.0, 60.0)
    capture_spin.setDecimals(1)
    capture_spin.setSingleStep(1.0)
    capture_spin.setSuffix(" s")
    capture_spin.setValue(DEFAULT_CAPTURE_S)
    capture_spin.setFixedWidth(120)

    measure_button = QPushButton("Measure period / duration")
    measure_button.setFixedWidth(220)
    status = QLabel("Ready — use while the lamp is flashing.")
    status.setWordWrap(True)
    status.setStyleSheet("color:#8FA9B9;")

    period_label = QLabel("Period\n—")
    duration_label = QLabel("Optical ON duration\n—")
    duty_label = QLabel("Duty cycle\n—")
    for metric_label in (period_label, duration_label, duty_label):
        metric_label.setMinimumWidth(160)
        metric_label.setStyleSheet(
            "background:#14212B; border:1px solid #34495E; border-radius:5px; "
            "padding:7px 10px; font-weight:700;"
        )
    detail_label = QLabel("Timing detail: —")
    detail_label.setWordWrap(True)
    note = QLabel(
        "This reads the optical waveform through repeated P-9710 MV samples. "
        "Period is based on consecutive rising edges. ON duration is a threshold-width "
        "estimate (30% rising / 20% falling hysteresis), so use an oscilloscope if an "
        "electrical pulse width is required."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#7892A3;")

    grid.addWidget(QLabel("Fixed range:"), 0, 0)
    grid.addWidget(range_spin, 0, 1)
    grid.addWidget(QLabel("Capture time:"), 0, 2)
    grid.addWidget(capture_spin, 0, 3)

    grid.addWidget(measure_button, 1, 0, 1, 2)
    grid.addWidget(status, 1, 2, 1, 2)

    grid.addWidget(period_label, 2, 0, 1, 1)
    grid.addWidget(duration_label, 2, 1, 1, 1)
    grid.addWidget(duty_label, 2, 2, 1, 1)
    grid.addWidget(detail_label, 2, 3, 1, 1)

    grid.addWidget(note, 3, 0, 1, 4)

    worker_holder = {"worker": None}

    def finish_worker():
        worker = worker_holder["worker"]
        if worker is not None:
            worker.deleteLater()
        worker_holder["worker"] = None
        window.p9710_flash_timing_worker = None
        measure_button.setEnabled(True)
        range_spin.setEnabled(True)
        capture_spin.setEnabled(True)

    def failed(message):
        status.setText("Timing measurement failed.")
        status.setStyleSheet("color:#FF7675; font-weight:700;")
        QMessageBox.critical(window, "P-9710 Flash Timing", message)

    def completed(result: PulseTimingResult):
        period_label.setText(f"Period\n{result.period_s:.5f} s")
        duration_label.setText(
            f"Optical ON duration\n{result.duration_s * 1000.0:.1f} ms"
        )
        duty_label.setText(f"Duty cycle\n{result.duty_cycle_pct:.2f}%")
        detail_label.setText(
            f"{result.pulses} rising edges • median sample interval "
            f"{result.sample_interval_ms:.1f} ms • baseline {result.baseline_lx:.3f} lx • "
            f"peak {result.peak_lx:.3f} lx"
        )
        status.setText("Timing captured successfully.")
        status.setStyleSheet("color:#55EFC4; font-weight:700;")
        window.p9710_last_measured_period_s = result.period_s
        window.p9710_last_measured_duration_s = result.duration_s
        window.p9710_last_flash_timing = result

    def start_measurement():
        holder = getattr(window, "p9710_meter_holder", None)
        meter = None if holder is None else holder.get("meter")
        if meter is None or not meter.is_connected:
            QMessageBox.warning(
                window,
                "P-9710 Flash Timing",
                "Connect the P-9710 first.",
            )
            return

        mode_worker_holder = getattr(window, "p9710_mode_worker_holder", None)
        if mode_worker_holder is not None and mode_worker_holder.get("worker") is not None:
            QMessageBox.warning(
                window,
                "P-9710 Flash Timing",
                "Another P-9710 measurement is already running.",
            )
            return
        if worker_holder["worker"] is not None:
            return

        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous()

        measure_button.setEnabled(False)
        range_spin.setEnabled(False)
        capture_spin.setEnabled(False)
        status.setText(
            f"Sampling optical waveform for {capture_spin.value():.1f} s on R{range_spin.value()}…"
        )
        status.setStyleSheet("color:#40B9D0; font-weight:700;")

        worker = PulseTimingWorker(
            meter,
            range_id=range_spin.value(),
            capture_s=capture_spin.value(),
            parent=window,
        )
        worker_holder["worker"] = worker
        window.p9710_flash_timing_worker = worker
        worker.measured.connect(completed)
        worker.failed.connect(failed)
        worker.finished.connect(finish_worker)
        worker.start()

    measure_button.clicked.connect(start_measurement)

    insert_index = layout.indexOf(p9710_box)
    layout.insertWidget(insert_index + 1 if insert_index >= 0 else layout.count(), box)

    window.p9710_flash_timing_box = box
    window.p9710_flash_timing_worker = None
    window.p9710_last_measured_period_s = None
    window.p9710_last_measured_duration_s = None
    window.p9710_last_flash_timing = None

    return box
