"""Manual effective-intensity pre-test for the Czibula & Grundmann Ph-Amp MB7.

This tool is intentionally separate from formal Measurement execution.  It lets
an operator capture one flashing waveform at a stationary goniometer position,
calculate a software Blondel-Rey effective illuminance/intensity, and inspect the
actual serial sampling cadence before relying on the method in an aviation run.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from luxmeter_controls import LUXMETER_CG
from miol_profile_runtime import _capture_effective_lux


DEFAULT_CAPTURE_S = 10.0


class EffectiveCaptureWorker(QThread):
    completed = Signal(object, object)
    failed = Signal(str)

    def __init__(self, meter, parent=None):
        super().__init__(parent)
        self.meter = meter

    def run(self):
        try:
            reading = _capture_effective_lux(self.meter)
            diagnostics = dict(getattr(self.meter, "last_miol_capture", {}) or {})
            self.completed.emit(reading, diagnostics)
        except Exception as exc:
            self.failed.emit(str(exc))


def attach_effective_intensity_test(window):
    """Add a standalone I-effective capture panel under the Luxmeter controls."""

    if getattr(window, "luxmeter_effective_box", None) is not None:
        return window.luxmeter_effective_box

    lux_box = getattr(window, "luxmeter_box", None)
    if lux_box is None:
        raise RuntimeError("Luxmeter controls must be attached first.")

    parent = lux_box.parentWidget()
    if parent is None or parent.layout() is None:
        raise RuntimeError("Luxmeter parent layout is not available.")
    parent_layout = parent.layout()

    box = QGroupBox("Effective Intensity Pre-Test — Software Blondel-Rey")
    layout = QGridLayout(box)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setHorizontalSpacing(14)
    layout.setVerticalSpacing(7)

    capture_spin = QDoubleSpinBox()
    capture_spin.setRange(1.0, 60.0)
    capture_spin.setDecimals(1)
    capture_spin.setSingleStep(1.0)
    capture_spin.setSuffix(" s")
    capture_spin.setValue(DEFAULT_CAPTURE_S)
    capture_spin.setToolTip(
        "Capture window must include the complete flash and an off/baseline interval."
    )

    distance_spin = QDoubleSpinBox()
    distance_spin.setRange(0.01, 100.0)
    distance_spin.setDecimals(3)
    distance_spin.setSingleStep(0.1)
    distance_spin.setSuffix(" m")
    measurement_distance = getattr(window, "measurement_distance_spin", None)
    if measurement_distance is not None:
        distance_spin.setValue(max(0.01, measurement_distance.value()))
    else:
        distance_spin.setValue(10.0)

    capture_button = QPushButton("Capture I-effective")
    capture_button.setObjectName("effectiveCaptureButton")
    capture_button.setToolTip(
        "Stop Live acquisition, then capture a temporal waveform and calculate "
        "software Blondel-Rey effective intensity."
    )

    status_label = QLabel("Ready — connect Czibula & Grundmann and stop Live first.")
    status_label.setWordWrap(True)
    status_label.setStyleSheet("color: #8FA9B9;")

    effective_lux_label = QLabel("E-effective: —")
    effective_cd_label = QLabel("I-effective: —")
    peak_label = QLabel("Net peak: —")
    baseline_label = QLabel("Baseline: —")
    interval_label = QLabel("Effective interval: —")
    samples_label = QLabel("Samples: —")
    cadence_label = QLabel("Median Δt: —")
    quality_label = QLabel("Temporal sampling: —")
    quality_label.setStyleSheet("font-weight: 700; color: #8FA9B9;")

    note = QLabel(
        "Pre-test only. The value is calculated in Lumigon from Ph-Amp temporal "
        "samples; compare it with the P-9710 before treating this path as a formal method."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color: #7892A3;")

    layout.addWidget(QLabel("Capture window:"), 0, 0)
    layout.addWidget(capture_spin, 0, 1)
    layout.addWidget(QLabel("Distance:"), 0, 2)
    layout.addWidget(distance_spin, 0, 3)
    layout.addWidget(capture_button, 0, 4, 1, 2)

    layout.addWidget(status_label, 1, 0, 1, 6)
    layout.addWidget(effective_lux_label, 2, 0, 1, 2)
    layout.addWidget(effective_cd_label, 2, 2, 1, 2)
    layout.addWidget(peak_label, 2, 4, 1, 2)
    layout.addWidget(baseline_label, 3, 0, 1, 2)
    layout.addWidget(interval_label, 3, 2, 1, 2)
    layout.addWidget(samples_label, 3, 4)
    layout.addWidget(cadence_label, 3, 5)
    layout.addWidget(quality_label, 4, 0, 1, 2)
    layout.addWidget(note, 4, 2, 1, 4)

    # Insert immediately after the main Luxmeter group.
    insert_index = parent_layout.indexOf(lux_box)
    parent_layout.insertWidget(insert_index + 1 if insert_index >= 0 else 0, box)

    def set_busy(busy):
        capture_button.setEnabled(not busy)
        capture_spin.setEnabled(not busy)
        distance_spin.setEnabled(not busy)
        for name in (
            "luxmeter_read_button",
            "luxmeter_start_live_button",
            "luxmeter_disconnect_button",
            "luxmeter_instrument_combo",
        ):
            control = getattr(window, name, None)
            if control is not None:
                control.setEnabled(not busy)

    def sampling_quality(diagnostics):
        dt_ms = diagnostics.get("median_sample_interval_ms")
        interval_s = diagnostics.get("effective_interval_s")
        if not dt_ms or not interval_s or dt_ms <= 0.0 or interval_s <= 0.0:
            return "UNKNOWN", None
        samples_across_interval = (interval_s * 1000.0) / dt_ms
        if samples_across_interval >= 10.0:
            return "GOOD", samples_across_interval
        if samples_across_interval >= 5.0:
            return "MARGINAL", samples_across_interval
        return "LOW", samples_across_interval

    def start_capture():
        selected = getattr(window, "luxmeter_selected_instrument", "")
        if selected != LUXMETER_CG:
            QMessageBox.information(
                window,
                "Effective Intensity Pre-Test",
                "This software waveform capture is currently available only for "
                "Czibula & Grundmann — Ph-Amp MB7.",
            )
            return

        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "Effective Intensity Pre-Test", "Connect the Ph-Amp first.")
            return

        live_worker = getattr(window, "luxmeter_live_worker", None)
        if live_worker is not None and live_worker.isRunning():
            QMessageBox.warning(
                window,
                "Effective Intensity Pre-Test",
                "Stop Live acquisition before capturing I-effective.",
            )
            return

        existing = getattr(window, "luxmeter_effective_worker", None)
        if existing is not None and existing.isRunning():
            return

        meter.sensitivity_na_per_lx = window.luxmeter_sensitivity_spin.value()
        type(meter)._lumigon_miol_capture_duration_s = capture_spin.value()

        status_label.setText(
            f"Capturing {capture_spin.value():.1f} s waveform at 10 ms integration…"
        )
        status_label.setStyleSheet("color: #40B9D0; font-weight: 600;")
        set_busy(True)

        worker = EffectiveCaptureWorker(meter, parent=window)
        window.luxmeter_effective_worker = worker

        def on_completed(reading, diagnostics):
            distance_m = distance_spin.value()
            effective_cd = float(reading.lux) * distance_m * distance_m
            peak = diagnostics.get("peak_lux_net")
            baseline = diagnostics.get("baseline_lux")
            interval_s = diagnostics.get("effective_interval_s")
            samples = diagnostics.get("samples")
            dt_ms = diagnostics.get("median_sample_interval_ms")
            capture_s = diagnostics.get("capture_duration_s")

            effective_lux_label.setText(f"E-effective: {reading.lux:.4f} lx")
            effective_cd_label.setText(f"I-effective: {effective_cd:.2f} cd @ {distance_m:.3f} m")
            peak_label.setText(
                f"Net peak: {peak:.4f} lx" if peak is not None else "Net peak: —"
            )
            baseline_label.setText(
                f"Baseline: {baseline:.4f} lx" if baseline is not None else "Baseline: —"
            )
            interval_label.setText(
                f"Effective interval: {interval_s:.3f} s"
                if interval_s is not None
                else "Effective interval: —"
            )
            samples_label.setText(f"Samples: {samples}" if samples is not None else "Samples: —")
            cadence_label.setText(
                f"Median Δt: {dt_ms:.1f} ms" if dt_ms is not None else "Median Δt: —"
            )

            quality, samples_across = sampling_quality(diagnostics)
            if quality == "GOOD":
                quality_label.setStyleSheet("font-weight:700; color:#55EFC4;")
            elif quality == "MARGINAL":
                quality_label.setStyleSheet("font-weight:700; color:#E7C76A;")
            elif quality == "LOW":
                quality_label.setStyleSheet("font-weight:700; color:#FF7675;")
            else:
                quality_label.setStyleSheet("font-weight:700; color:#8FA9B9;")

            if samples_across is None:
                quality_label.setText(f"Temporal sampling: {quality}")
            else:
                quality_label.setText(
                    f"Temporal sampling: {quality} (~{samples_across:.1f} samples / effective interval)"
                )

            status_label.setText(
                f"Capture complete ({capture_s:.2f} s). Software Blondel-Rey estimate ready for comparison."
                if capture_s is not None
                else "Capture complete. Software Blondel-Rey estimate ready for comparison."
            )
            status_label.setStyleSheet("color: #55EFC4;")

            window.luxmeter_last_effective_lux = float(reading.lux)
            window.luxmeter_last_effective_cd = effective_cd
            window.luxmeter_last_effective_capture = diagnostics

        def on_failed(message):
            status_label.setText("Capture failed.")
            status_label.setStyleSheet("color: #FF7675; font-weight:600;")
            QMessageBox.critical(window, "Effective Intensity Capture Error", message)

        def on_finished():
            current = getattr(window, "luxmeter_effective_worker", None)
            if current is not None:
                current.deleteLater()
            window.luxmeter_effective_worker = None
            set_busy(False)

        worker.completed.connect(on_completed)
        worker.failed.connect(on_failed)
        worker.finished.connect(on_finished)
        worker.start()

    capture_button.clicked.connect(start_capture)

    window.luxmeter_effective_box = box
    window.luxmeter_effective_capture_spin = capture_spin
    window.luxmeter_effective_distance_spin = distance_spin
    window.luxmeter_effective_capture_button = capture_button
    window.luxmeter_effective_status_label = status_label
    window.luxmeter_effective_worker = None
    window.luxmeter_last_effective_lux = None
    window.luxmeter_last_effective_cd = None
    window.luxmeter_last_effective_capture = None

    return box
