"""Standalone synchronized P-9710 effective-measurement panel for Lumigon.

This is the first hardware-validated P-9710 path. It is deliberately kept
separate from the older Czibula software-waveform pre-test so both methods can
be compared during commissioning.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from p9710 import P9710


DEFAULT_PORT = "COM7"
DEFAULT_PULSE_MS = 350
DEFAULT_PERIOD_S = 3.170
DEFAULT_PRETRIGGER_MS = 100
DEFAULT_WINDOW_MS = 600
DEFAULT_RANGE = 5
DEFAULT_THRESHOLD_LX = 5.0
DEFAULT_C_S = 0.2


def auto_pretrigger_ms(_pulse_ms: int) -> int:
    return 100


def auto_window_ms(pulse_ms: int) -> int:
    target = max(100, int(pulse_ms)) + 250
    return int(math.ceil(target / 50.0) * 50)


class P9710MeasureWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)

    def __init__(self, meter, settings, parent=None):
        super().__init__(parent)
        self.meter = meter
        self.settings = dict(settings)

    def run(self):
        try:
            reading = self.meter.synchronized_effective(**self.settings)
            self.measured.emit(reading)
        except Exception as exc:
            self.failed.emit(str(exc))


def attach_p9710_effective_panel(window):
    if getattr(window, "p9710_effective_box", None) is not None:
        return window.p9710_effective_box

    lux_box = getattr(window, "luxmeter_box", None)
    if lux_box is None or lux_box.parentWidget() is None or lux_box.parentWidget().layout() is None:
        raise RuntimeError("Luxmeter tab must exist before P-9710 panel is attached.")

    parent = lux_box.parentWidget()
    parent_layout = parent.layout()

    box = QGroupBox("P-9710 — Synchronized E-effective / I-effective")
    layout = QGridLayout(box)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setHorizontalSpacing(12)
    layout.setVerticalSpacing(7)

    port_combo = QComboBox()
    port_combo.setEditable(True)
    port_combo.addItem(DEFAULT_PORT)
    if getattr(window, "luxmeter_port_combo", None) is not None:
        current = window.luxmeter_port_combo.currentText().strip()
        port_combo.setCurrentText(current or DEFAULT_PORT)
    else:
        port_combo.setCurrentText(DEFAULT_PORT)

    connect_button = QPushButton("Connect P-9710")
    disconnect_button = QPushButton("Disconnect")

    pulse_spin = QSpinBox()
    pulse_spin.setRange(1, 5000)
    pulse_spin.setSuffix(" ms")
    pulse_spin.setValue(DEFAULT_PULSE_MS)

    period_spin = QDoubleSpinBox()
    period_spin.setRange(0.050, 120.0)
    period_spin.setDecimals(4)
    period_spin.setSingleStep(0.01)
    period_spin.setSuffix(" s")
    period_spin.setValue(DEFAULT_PERIOD_S)

    auto_pre = QCheckBox("Auto")
    auto_pre.setChecked(True)
    pre_spin = QSpinBox()
    pre_spin.setRange(0, 5000)
    pre_spin.setSuffix(" ms")
    pre_spin.setValue(DEFAULT_PRETRIGGER_MS)

    auto_window = QCheckBox("Auto")
    auto_window.setChecked(True)
    window_spin = QSpinBox()
    window_spin.setRange(1, 10000)
    window_spin.setSuffix(" ms")
    window_spin.setValue(DEFAULT_WINDOW_MS)

    range_spin = QSpinBox()
    range_spin.setRange(0, 7)
    range_spin.setValue(DEFAULT_RANGE)

    threshold_spin = QDoubleSpinBox()
    threshold_spin.setRange(0.001, 100000.0)
    threshold_spin.setDecimals(3)
    threshold_spin.setSuffix(" lx")
    threshold_spin.setValue(DEFAULT_THRESHOLD_LX)

    c_spin = QDoubleSpinBox()
    c_spin.setRange(0.001, 10.0)
    c_spin.setDecimals(3)
    c_spin.setSingleStep(0.05)
    c_spin.setSuffix(" s")
    c_spin.setValue(DEFAULT_C_S)

    distance_spin = QDoubleSpinBox()
    distance_spin.setRange(0.01, 1000.0)
    distance_spin.setDecimals(3)
    distance_spin.setSuffix(" m")
    distance_spin.setValue(5.0)
    if getattr(window, "measurement_distance_spin", None) is not None:
        distance_spin.setValue(max(0.01, window.measurement_distance_spin.value()))

    measure_button = QPushButton("Measure synchronized")
    measure_button.setObjectName("p9710SynchronizedMeasureButton")

    status = QLabel("Disconnected")
    status.setWordWrap(True)
    status.setStyleSheet("color:#8FA9B9;")

    e_label = QLabel("E-effective: —")
    i_label = QLabel("I-effective: —")
    trigger_label = QLabel("Trigger sample: —")
    timing_label = QLabel("Timing: —")
    utilization_label = QLabel("Range utilization (GP): —")
    utilization_label.setStyleSheet("font-weight:700; color:#8FA9B9;")
    selected_range_label = QLabel(f"Selected range: R{DEFAULT_RANGE}")
    selected_range_label.setStyleSheet("color:#8FA9B9;")

    note = QLabel(
        "One-step synchronization: detect one real flash with MV, predict only the next flash, "
        "then start P-9710 MI before it. Range utilization is read from the instrument GP diagnostic."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#7892A3;")

    layout.addWidget(QLabel("Port:"), 0, 0)
    layout.addWidget(port_combo, 0, 1)
    layout.addWidget(connect_button, 0, 2)
    layout.addWidget(disconnect_button, 0, 3)
    layout.addWidget(status, 0, 4, 1, 2)

    layout.addWidget(QLabel("Pulse duration:"), 1, 0)
    layout.addWidget(pulse_spin, 1, 1)
    layout.addWidget(QLabel("Pulse period:"), 1, 2)
    layout.addWidget(period_spin, 1, 3)
    layout.addWidget(QLabel("Distance:"), 1, 4)
    layout.addWidget(distance_spin, 1, 5)

    layout.addWidget(QLabel("Pre-trigger:"), 2, 0)
    layout.addWidget(pre_spin, 2, 1)
    layout.addWidget(auto_pre, 2, 2)
    layout.addWidget(QLabel("MI window:"), 2, 3)
    layout.addWidget(window_spin, 2, 4)
    layout.addWidget(auto_window, 2, 5)

    layout.addWidget(QLabel("Range:"), 3, 0)
    layout.addWidget(range_spin, 3, 1)
    layout.addWidget(QLabel("Trigger threshold:"), 3, 2)
    layout.addWidget(threshold_spin, 3, 3)
    layout.addWidget(QLabel("Schmidt-Clausen C:"), 3, 4)
    layout.addWidget(c_spin, 3, 5)

    layout.addWidget(measure_button, 4, 0, 1, 2)
    layout.addWidget(e_label, 4, 2)
    layout.addWidget(i_label, 4, 3)
    layout.addWidget(trigger_label, 4, 4)
    layout.addWidget(timing_label, 4, 5)

    layout.addWidget(selected_range_label, 5, 0, 1, 2)
    layout.addWidget(utilization_label, 5, 2, 1, 2)
    layout.addWidget(note, 6, 0, 1, 6)

    meter_holder = {"meter": None}

    def apply_auto_values():
        if auto_pre.isChecked():
            pre_spin.setValue(auto_pretrigger_ms(pulse_spin.value()))
        if auto_window.isChecked():
            window_spin.setValue(auto_window_ms(pulse_spin.value()))
        pre_spin.setEnabled(not auto_pre.isChecked())
        window_spin.setEnabled(not auto_window.isChecked())

    def update_range_caption():
        selected_range_label.setText(f"Selected range: R{range_spin.value()}")

    def set_busy(busy: bool):
        for control in (
            port_combo, connect_button, disconnect_button, pulse_spin, period_spin,
            auto_pre, pre_spin, auto_window, window_spin, range_spin,
            threshold_spin, c_spin, distance_spin, measure_button,
        ):
            control.setEnabled(not busy)
        apply_auto_values()
        if busy:
            measure_button.setEnabled(False)

    def connect_meter():
        port = port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(window, "P-9710", "Select a COM port first.")
            return
        old = meter_holder["meter"]
        if old is not None:
            old.disconnect()
        meter = P9710(port)
        try:
            version = meter.connect()
        except Exception as exc:
            meter.disconnect()
            QMessageBox.critical(window, "P-9710 Connection Error", str(exc))
            return
        meter_holder["meter"] = meter
        unit = meter.unit or "—"
        status.setText(f"Connected — {version} — unit {unit}")
        status.setStyleSheet("color:#55EFC4; font-weight:600;")
        measure_button.setEnabled(True)

    def disconnect_meter():
        meter = meter_holder["meter"]
        if meter is not None:
            meter.disconnect()
        meter_holder["meter"] = None
        status.setText("Disconnected")
        status.setStyleSheet("color:#8FA9B9;")
        utilization_label.setText("Range utilization (GP): —")
        utilization_label.setStyleSheet("font-weight:700; color:#8FA9B9;")

    def start_measurement():
        meter = meter_holder["meter"]
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "P-9710", "Connect the P-9710 first.")
            return

        apply_auto_values()
        settings = {
            "period_s": period_spin.value(),
            "pretrigger_ms": pre_spin.value(),
            "window_ms": window_spin.value(),
            "threshold_lx": threshold_spin.value(),
            "range_id": range_spin.value(),
            "c_s": c_spin.value(),
        }

        status.setText("Waiting for reference flash, then measuring next flash…")
        status.setStyleSheet("color:#40B9D0; font-weight:600;")
        utilization_label.setText(f"Range utilization (GP): measuring on R{range_spin.value()}…")
        utilization_label.setStyleSheet("font-weight:700; color:#40B9D0;")
        set_busy(True)

        worker = P9710MeasureWorker(meter, settings, parent=window)
        window.p9710_effective_worker = worker

        def completed(reading):
            distance_m = distance_spin.value()
            i_effective_cd = reading.e_effective_lx * distance_m * distance_m
            e_label.setText(f"E-effective: {reading.e_effective_lx:.4f} lx")
            i_label.setText(f"I-effective: {i_effective_cd:.2f} cd")
            trigger_label.setText(f"Trigger sample: {reading.trigger_sample_lx:.3f} lx")
            timing_label.setText(f"Pre {reading.pretrigger_ms} ms | Window {reading.window_ms} ms")
            selected_range_label.setText(f"Selected range: R{reading.range_id}")

            if reading.range_utilization_pct is None:
                utilization_label.setText("Range utilization (GP): unavailable")
                utilization_label.setStyleSheet("font-weight:700; color:#E7C76A;")
            else:
                utilization_label.setText(
                    f"Range utilization (GP): {reading.range_utilization_pct:.1f}%  |  R{reading.range_id}"
                )
                utilization_label.setStyleSheet("font-weight:700; color:#55EFC4;")

            status.setText(f"Complete — software start error {reading.software_start_error_ms:+.2f} ms")
            status.setStyleSheet("color:#55EFC4;")

            window.p9710_last_e_effective_lx = reading.e_effective_lx
            window.p9710_last_i_effective_cd = i_effective_cd
            window.p9710_last_range_utilization_pct = reading.range_utilization_pct
            window.p9710_last_reading = reading

        def failed(message):
            status.setText("Measurement failed")
            status.setStyleSheet("color:#FF7675; font-weight:600;")
            utilization_label.setText("Range utilization (GP): measurement failed")
            utilization_label.setStyleSheet("font-weight:700; color:#FF7675;")
            QMessageBox.critical(window, "P-9710 Synchronized Measurement", message)

        def finished():
            current = getattr(window, "p9710_effective_worker", None)
            if current is not None:
                current.deleteLater()
            window.p9710_effective_worker = None
            set_busy(False)
            measure_button.setEnabled(meter_holder["meter"] is not None)

        worker.measured.connect(completed)
        worker.failed.connect(failed)
        worker.finished.connect(finished)
        worker.start()

    pulse_spin.valueChanged.connect(apply_auto_values)
    auto_pre.toggled.connect(apply_auto_values)
    auto_window.toggled.connect(apply_auto_values)
    range_spin.valueChanged.connect(update_range_caption)
    connect_button.clicked.connect(connect_meter)
    disconnect_button.clicked.connect(disconnect_meter)
    measure_button.clicked.connect(start_measurement)

    apply_auto_values()
    update_range_caption()
    measure_button.setEnabled(False)

    insert_index = parent_layout.indexOf(getattr(window, "luxmeter_effective_box", lux_box))
    parent_layout.insertWidget(insert_index + 1 if insert_index >= 0 else parent_layout.count(), box)

    window.p9710_effective_box = box
    window.p9710_effective_port_combo = port_combo
    window.p9710_effective_pulse_spin = pulse_spin
    window.p9710_effective_period_spin = period_spin
    window.p9710_effective_pretrigger_spin = pre_spin
    window.p9710_effective_window_spin = window_spin
    window.p9710_effective_auto_pre = auto_pre
    window.p9710_effective_auto_window = auto_window
    window.p9710_effective_worker = None
    window.p9710_last_e_effective_lx = None
    window.p9710_last_i_effective_cd = None
    window.p9710_last_range_utilization_pct = None
    window.p9710_last_reading = None

    return box
