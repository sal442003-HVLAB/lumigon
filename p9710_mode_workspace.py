"""Mode-oriented Gigahertz-Optik P-9710 workspace for Lumigon.

Each measurement mode has its own focused page.  The first implementation
covers the laboratory-relevant modes that are supported by the verified RS232
commands: CW, CW Maximum, CW Minimum, Peak Maximum, Peak Minimum,
Peak-to-Peak and synchronized I-Effective (Schmidt-Clausen).
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
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from p9710 import P9710


DEFAULT_PORT = "COM7"
DEFAULT_RANGE = 5
DEFAULT_INTEGRATION_MS = 100.0
DEFAULT_PERIOD_S = 3.170
DEFAULT_PRETRIGGER_MS = 100
DEFAULT_WINDOW_MS = 600
DEFAULT_THRESHOLD_LX = 5.0
DEFAULT_C_S = 0.2

RANGE_UTILIZATION_MIN_PCT = 15.0
RANGE_UTILIZATION_MAX_PCT = 85.0
DETECTOR_SENSITIVITY_NA_PER_LX = 0.376
RANGE_MAX_CURRENT_NA = {
    0: 2_000_000.0,
    1: 200_000.0,
    2: 20_000.0,
    3: 2_000.0,
    4: 200.0,
    5: 20.0,
    6: 2.0,
    7: 0.2,
}

MODE_NAMES = [
    "CW",
    "CW Maximum",
    "CW Minimum",
    "Peak Maximum",
    "Peak Minimum",
    "Peak-to-Peak",
    "I-Effective (SC)",
]


def _format_lux(value: float) -> str:
    value = float(value)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mlx"
    if value >= 1_000:
        return f"{value / 1_000:.2f} klx"
    if value >= 100:
        return f"{value:.0f} lx"
    if value >= 10:
        return f"{value:.1f} lx"
    if value >= 1:
        return f"{value:.3f} lx"
    return f"{value:.4f} lx"


def _range_interval_text(range_id: int) -> str:
    range_id = int(range_id)
    upper = RANGE_MAX_CURRENT_NA[range_id] / DETECTOR_SENSITIVITY_NA_PER_LX
    if range_id < 7:
        lower = RANGE_MAX_CURRENT_NA[range_id + 1] / DETECTOR_SENSITIVITY_NA_PER_LX
        return f"R{range_id}: approx. {_format_lux(lower)} – {_format_lux(upper)}"
    return f"R{range_id}: approx. 0 – {_format_lux(upper)}"


def _style_utilization(bar: QProgressBar, value_pct: float | None):
    bar.setRange(0, 100)
    if value_pct is None:
        bar.setValue(0)
        bar.setFormat("Unavailable")
        color = "#607D8B"
    else:
        value_pct = max(0.0, min(100.0, float(value_pct)))
        bar.setValue(int(round(value_pct)))
        bar.setFormat(f"{value_pct:.1f}%")
        outside = value_pct < RANGE_UTILIZATION_MIN_PCT or value_pct > RANGE_UTILIZATION_MAX_PCT
        color = "#D9534F" if outside else "#2EAD67"

    bar.setStyleSheet(
        "QProgressBar { border:1px solid #34495E; border-radius:4px; "
        "background:#14212B; color:#FFFFFF; text-align:center; font-weight:700; }"
        f"QProgressBar::chunk {{ background:{color}; border-radius:3px; }}"
    )


class CWWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)

    def __init__(self, meter, settings, parent=None):
        super().__init__(parent)
        self.meter = meter
        self.settings = dict(settings)

    def run(self):
        try:
            self.measured.emit(self.meter.read_cw_snapshot(**self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


class EffectiveWorker(QThread):
    measured = Signal(object)
    failed = Signal(str)

    def __init__(self, meter, settings, parent=None):
        super().__init__(parent)
        self.meter = meter
        self.settings = dict(settings)

    def run(self):
        try:
            self.measured.emit(self.meter.synchronized_effective(**self.settings))
        except Exception as exc:
            self.failed.emit(str(exc))


def attach_p9710_mode_workspace(window):
    if getattr(window, "p9710_effective_box", None) is not None:
        return window.p9710_effective_box

    lux_box = getattr(window, "luxmeter_box", None)
    if lux_box is None or lux_box.parentWidget() is None or lux_box.parentWidget().layout() is None:
        raise RuntimeError("Luxmeter tab must exist before the P-9710 workspace is attached.")

    parent = lux_box.parentWidget()
    parent_layout = parent.layout()

    box = QGroupBox("Gigahertz-Optik P-9710")
    root = QVBoxLayout(box)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(10)

    # Shared connection/header controls.
    header = QGridLayout()
    port_combo = QComboBox()
    port_combo.setEditable(True)
    port_combo.addItem(DEFAULT_PORT)
    port_combo.setCurrentText(DEFAULT_PORT)

    connect_button = QPushButton("Connect P-9710")
    disconnect_button = QPushButton("Disconnect")
    connection_status = QLabel("Disconnected")
    connection_status.setStyleSheet("color:#8FA9B9;")

    mode_combo = QComboBox()
    mode_combo.addItems(MODE_NAMES)

    header.addWidget(QLabel("Port:"), 0, 0)
    header.addWidget(port_combo, 0, 1)
    header.addWidget(connect_button, 0, 2)
    header.addWidget(disconnect_button, 0, 3)
    header.addWidget(connection_status, 0, 4, 1, 2)
    header.addWidget(QLabel("Measurement mode:"), 1, 0)
    header.addWidget(mode_combo, 1, 1, 1, 2)
    root.addLayout(header)

    stack = QStackedWidget()
    root.addWidget(stack)

    meter_holder = {"meter": None}
    worker_holder = {"worker": None}

    def meter_or_warn():
        meter = meter_holder["meter"]
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "P-9710", "Connect the P-9710 first.")
            return None
        return meter

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
        connection_status.setText(f"Connected — {version} — unit {meter.unit or '—'}")
        connection_status.setStyleSheet("color:#55EFC4; font-weight:700;")

    def disconnect_meter():
        meter = meter_holder["meter"]
        if meter is not None:
            meter.disconnect()
        meter_holder["meter"] = None
        connection_status.setText("Disconnected")
        connection_status.setStyleSheet("color:#8FA9B9;")

    connect_button.clicked.connect(connect_meter)
    disconnect_button.clicked.connect(disconnect_meter)

    def make_cw_page(mode_name: str, value_field: str, accumulated: bool = False):
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(9)

        integration = QDoubleSpinBox()
        integration.setRange(0.1, 6000.0)
        integration.setDecimals(1)
        integration.setSingleStep(10.0)
        integration.setSuffix(" ms")
        integration.setValue(DEFAULT_INTEGRATION_MS)

        range_spin = QSpinBox()
        range_spin.setRange(0, 7)
        range_spin.setValue(DEFAULT_RANGE)
        sync_box = QCheckBox("CW synchronisation")

        range_hint = QLabel(_range_interval_text(DEFAULT_RANGE))
        range_hint.setStyleSheet("color:#8FA9B9;")
        range_spin.valueChanged.connect(lambda v: range_hint.setText(_range_interval_text(v)))

        read_button = QPushButton(f"Read {mode_name}")
        reset_button = QPushButton("Reset extrema") if accumulated else None

        result = QLabel(f"{mode_name}: —")
        result.setStyleSheet("font-size:16pt; font-weight:700; color:#E7F2F8;")
        cw_label = QLabel("CW: —")
        peak_max_label = QLabel("Peak max: —")
        peak_min_label = QLabel("Peak min: —")
        p2p_label = QLabel("Peak-to-peak: —")
        utilization_text = QLabel("Range utilization (GP): —")
        utilization_bar = QProgressBar()
        utilization_bar.setMinimumHeight(24)
        _style_utilization(utilization_bar, None)

        state = {"extreme": None}

        layout.addWidget(QLabel("Integration time:"), 0, 0)
        layout.addWidget(integration, 0, 1)
        layout.addWidget(QLabel("Range:"), 0, 2)
        layout.addWidget(range_spin, 0, 3)
        layout.addWidget(sync_box, 0, 4)
        layout.addWidget(range_hint, 1, 2, 1, 3)
        layout.addWidget(read_button, 2, 0, 1, 2)
        if reset_button is not None:
            layout.addWidget(reset_button, 2, 2)
        layout.addWidget(result, 3, 0, 1, 3)
        layout.addWidget(cw_label, 4, 0)
        layout.addWidget(peak_max_label, 4, 1)
        layout.addWidget(peak_min_label, 4, 2)
        layout.addWidget(p2p_label, 4, 3)
        layout.addWidget(utilization_text, 5, 0, 1, 5)
        layout.addWidget(utilization_bar, 6, 0, 1, 5)
        layout.setRowStretch(7, 1)

        def finish_worker():
            worker = worker_holder["worker"]
            if worker is not None:
                worker.deleteLater()
            worker_holder["worker"] = None
            read_button.setEnabled(True)
            if reset_button is not None:
                reset_button.setEnabled(True)

        def failed(message):
            QMessageBox.critical(window, f"P-9710 {mode_name}", message)

        def completed(reading):
            cw_label.setText(f"CW: {reading.cw_lx:.4f} lx")
            peak_max_label.setText(
                "Peak max: —" if reading.peak_max_lx is None else f"Peak max: {reading.peak_max_lx:.4f} lx"
            )
            peak_min_label.setText(
                "Peak min: —" if reading.peak_min_lx is None else f"Peak min: {reading.peak_min_lx:.4f} lx"
            )
            p2p_label.setText(
                "Peak-to-peak: —" if reading.peak_to_peak_lx is None else f"Peak-to-peak: {reading.peak_to_peak_lx:.4f} lx"
            )

            raw_value = getattr(reading, value_field)
            if raw_value is None:
                display_value = None
            elif accumulated:
                old = state["extreme"]
                if old is None:
                    state["extreme"] = float(raw_value)
                elif mode_name == "CW Maximum":
                    state["extreme"] = max(old, float(raw_value))
                else:
                    state["extreme"] = min(old, float(raw_value))
                display_value = state["extreme"]
            else:
                display_value = float(raw_value)

            result.setText(
                f"{mode_name}: —" if display_value is None else f"{mode_name}: {display_value:.4f} lx"
            )

            gp = reading.range_utilization_pct
            utilization_text.setText(
                f"Range utilization (GP): {'—' if gp is None else f'{gp:.1f}%'}  |  {_range_interval_text(reading.range_id)}"
            )
            _style_utilization(utilization_bar, gp)

            window.p9710_last_cw_reading = reading

        def start_read():
            meter = meter_or_warn()
            if meter is None or worker_holder["worker"] is not None:
                return
            read_button.setEnabled(False)
            if reset_button is not None:
                reset_button.setEnabled(False)
            worker = CWWorker(
                meter,
                {
                    "integration_ms": integration.value(),
                    "range_id": range_spin.value(),
                    "sync_enabled": sync_box.isChecked(),
                },
                parent=window,
            )
            worker_holder["worker"] = worker
            worker.measured.connect(completed)
            worker.failed.connect(failed)
            worker.finished.connect(finish_worker)
            worker.start()

        read_button.clicked.connect(start_read)
        if reset_button is not None:
            def reset_extreme():
                state["extreme"] = None
                result.setText(f"{mode_name}: —")
            reset_button.clicked.connect(reset_extreme)

        return page

    stack.addWidget(make_cw_page("CW", "cw_lx"))
    # P-9710 does not expose stored CW max/min over RS232 in the verified command
    # set, so Lumigon accumulates the successive CW readings on these two pages.
    stack.addWidget(make_cw_page("CW Maximum", "cw_lx", accumulated=True))
    stack.addWidget(make_cw_page("CW Minimum", "cw_lx", accumulated=True))
    stack.addWidget(make_cw_page("Peak Maximum", "peak_max_lx"))
    stack.addWidget(make_cw_page("Peak Minimum", "peak_min_lx"))
    stack.addWidget(make_cw_page("Peak-to-Peak", "peak_to_peak_lx"))

    # I-Effective (Schmidt-Clausen) page.
    effective_page = QWidget()
    egrid = QGridLayout(effective_page)
    egrid.setContentsMargins(8, 8, 8, 8)
    egrid.setHorizontalSpacing(14)
    egrid.setVerticalSpacing(9)

    period_spin = QDoubleSpinBox()
    period_spin.setRange(0.05, 120.0)
    period_spin.setDecimals(4)
    period_spin.setSuffix(" s")
    period_spin.setValue(DEFAULT_PERIOD_S)

    pre_spin = QSpinBox()
    pre_spin.setRange(0, 5000)
    pre_spin.setSuffix(" ms")
    pre_spin.setValue(DEFAULT_PRETRIGGER_MS)

    window_spin = QSpinBox()
    window_spin.setRange(1, 10000)
    window_spin.setSuffix(" ms")
    window_spin.setValue(DEFAULT_WINDOW_MS)

    range_spin = QSpinBox()
    range_spin.setRange(0, 7)
    range_spin.setValue(DEFAULT_RANGE)
    range_hint = QLabel(_range_interval_text(DEFAULT_RANGE))
    range_hint.setStyleSheet("color:#8FA9B9;")
    range_spin.valueChanged.connect(lambda v: range_hint.setText(_range_interval_text(v)))

    threshold_spin = QDoubleSpinBox()
    threshold_spin.setRange(0.001, 100000.0)
    threshold_spin.setDecimals(3)
    threshold_spin.setSuffix(" lx")
    threshold_spin.setValue(DEFAULT_THRESHOLD_LX)

    c_spin = QDoubleSpinBox()
    c_spin.setRange(0.001, 10.0)
    c_spin.setDecimals(3)
    c_spin.setSuffix(" s")
    c_spin.setValue(DEFAULT_C_S)

    distance_spin = QDoubleSpinBox()
    distance_spin.setRange(0.01, 1000.0)
    distance_spin.setDecimals(3)
    distance_spin.setSuffix(" m")
    distance_spin.setValue(10.0)

    e_button = QPushButton("Measure synchronized")
    e_result = QLabel("E-effective: —")
    i_result = QLabel("I-effective: —")
    trigger_result = QLabel("Trigger sample: —")
    e_status = QLabel("Ready")
    e_gp_text = QLabel("Range utilization (GP): —")
    e_gp_bar = QProgressBar()
    e_gp_bar.setMinimumHeight(24)
    _style_utilization(e_gp_bar, None)

    egrid.addWidget(QLabel("Pulse period:"), 0, 0)
    egrid.addWidget(period_spin, 0, 1)
    egrid.addWidget(QLabel("Pre-trigger:"), 0, 2)
    egrid.addWidget(pre_spin, 0, 3)
    egrid.addWidget(QLabel("MI window:"), 1, 0)
    egrid.addWidget(window_spin, 1, 1)
    egrid.addWidget(QLabel("Range:"), 1, 2)
    egrid.addWidget(range_spin, 1, 3)
    egrid.addWidget(range_hint, 2, 2, 1, 2)
    egrid.addWidget(QLabel("Trigger threshold:"), 3, 0)
    egrid.addWidget(threshold_spin, 3, 1)
    egrid.addWidget(QLabel("Schmidt-Clausen C:"), 3, 2)
    egrid.addWidget(c_spin, 3, 3)
    egrid.addWidget(QLabel("Distance:"), 4, 0)
    egrid.addWidget(distance_spin, 4, 1)
    egrid.addWidget(e_button, 5, 0, 1, 2)
    egrid.addWidget(e_status, 5, 2, 1, 2)
    egrid.addWidget(e_result, 6, 0)
    egrid.addWidget(i_result, 6, 1)
    egrid.addWidget(trigger_result, 6, 2, 1, 2)
    egrid.addWidget(e_gp_text, 7, 0, 1, 4)
    egrid.addWidget(e_gp_bar, 8, 0, 1, 4)
    egrid.setRowStretch(9, 1)

    def effective_finished():
        worker = worker_holder["worker"]
        if worker is not None:
            worker.deleteLater()
        worker_holder["worker"] = None
        e_button.setEnabled(True)

    def effective_failed(message):
        e_status.setText("Measurement failed")
        e_status.setStyleSheet("color:#FF7675; font-weight:700;")
        QMessageBox.critical(window, "P-9710 I-Effective (SC)", message)

    def effective_completed(reading):
        distance_m = distance_spin.value()
        i_effective = reading.e_effective_lx * distance_m * distance_m
        e_result.setText(f"E-effective: {reading.e_effective_lx:.4f} lx")
        i_result.setText(f"I-effective: {i_effective:.2f} cd")
        trigger_result.setText(f"Trigger sample: {reading.trigger_sample_lx:.3f} lx")
        e_status.setText(f"Complete — start error {reading.software_start_error_ms:+.2f} ms")
        e_status.setStyleSheet("color:#55EFC4;")
        gp = reading.range_utilization_pct
        e_gp_text.setText(
            f"Range utilization (GP): {'—' if gp is None else f'{gp:.1f}%'}  |  {_range_interval_text(reading.range_id)}"
        )
        _style_utilization(e_gp_bar, gp)
        window.p9710_last_e_effective_lx = reading.e_effective_lx
        window.p9710_last_i_effective_cd = i_effective
        window.p9710_last_reading = reading

    def start_effective():
        meter = meter_or_warn()
        if meter is None or worker_holder["worker"] is not None:
            return
        e_button.setEnabled(False)
        e_status.setText("Waiting for reference flash…")
        e_status.setStyleSheet("color:#40B9D0; font-weight:700;")
        worker = EffectiveWorker(
            meter,
            {
                "period_s": period_spin.value(),
                "pretrigger_ms": pre_spin.value(),
                "window_ms": window_spin.value(),
                "threshold_lx": threshold_spin.value(),
                "range_id": range_spin.value(),
                "c_s": c_spin.value(),
            },
            parent=window,
        )
        worker_holder["worker"] = worker
        worker.measured.connect(effective_completed)
        worker.failed.connect(effective_failed)
        worker.finished.connect(effective_finished)
        worker.start()

    e_button.clicked.connect(start_effective)
    stack.addWidget(effective_page)

    mode_combo.currentIndexChanged.connect(stack.setCurrentIndex)
    stack.setCurrentIndex(0)

    note = QLabel(
        "CW Maximum/Minimum are accumulated by Lumigon from successive CW reads. "
        "Peak Maximum/Minimum/Peak-to-Peak use the P-9710 GA/GB/GD values from the latest CW measurement."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#7892A3;")
    root.addWidget(note)

    insert_index = parent_layout.indexOf(getattr(window, "luxmeter_effective_box", lux_box))
    parent_layout.insertWidget(insert_index + 1 if insert_index >= 0 else parent_layout.count(), box)

    # Keep the existing attribute name so luxmeter_workspace_tabs can move this
    # complete workspace into the Gigahertz-Optik sub-tab.
    window.p9710_effective_box = box
    window.p9710_mode_combo = mode_combo
    window.p9710_mode_stack = stack
    window.p9710_meter_holder = meter_holder
    window.p9710_mode_worker_holder = worker_holder
    window.p9710_last_cw_reading = None
    window.p9710_last_e_effective_lx = None
    window.p9710_last_i_effective_cd = None
    window.p9710_last_reading = None

    return box
