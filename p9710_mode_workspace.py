"""Mode-oriented Gigahertz-Optik P-9710 workspace for Lumigon.

Each measurement mode has its own focused page.  The first implementation
covers the laboratory-relevant modes that are supported by the verified RS232
commands: CW, CW Maximum, CW Minimum, Peak Maximum, Peak Minimum,
Peak-to-Peak and synchronized I-Effective (Schmidt-Clausen).
"""

from __future__ import annotations


from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
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
from p9710_range_policy import GP_SATURATION_REFERENCE, normalized_range_use
from luxmeter_ui import CollapsibleSection, form_section, result_section, two_columns


DEFAULT_PORT = "COM7"
DEFAULT_RANGE = 5
DEFAULT_INTEGRATION_MS = 100.0
DEFAULT_PERIOD_S = 3.170
DEFAULT_PRETRIGGER_MS = 100
DEFAULT_WINDOW_MS = 600
DEFAULT_THRESHOLD_LX = 5.0
DEFAULT_C_S = 0.2

RANGE_UTILIZATION_MIN_PCT = 10.0
RANGE_UTILIZATION_MAX_PCT = 90.0
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
        value_pct = float(value_pct)
        bar.setValue(int(round(max(0.0, min(100.0, value_pct)))))
        if value_pct > RANGE_UTILIZATION_MAX_PCT:
            state, color = "Above limit", "#D9534F"
        elif value_pct < RANGE_UTILIZATION_MIN_PCT:
            state, color = "Low utilization", "#D9A441"
        else:
            state, color = "Within observed target", "#1769AA"
        bar.setFormat(f"{value_pct:.1f}% • {state}")

    bar.setStyleSheet(
        "QProgressBar { border:1px solid #34495E; border-radius:4px; "
        "background:#14212B; color:#FFFFFF; text-align:center; font-weight:700; }"
        f"QProgressBar::chunk {{ background:{color}; border-radius:3px; }}"
    )


def _update_range_use(label, bar, raw_gp, range_id):
    """Display the empirical guard percentage while retaining the raw reading."""
    try:
        percent = None if raw_gp is None else normalized_range_use(raw_gp)
    except (ValueError, TypeError):
        percent = None
    if percent is None:
        label.setText(f"Range use: unavailable • R{range_id}")
    else:
        label.setText(f"Range use: {percent:.1f}% of limit • R{range_id} • raw GP {raw_gp:g}")
    label.setToolTip(
        f"Observed saturation reference: raw GP {GP_SATURATION_REFERENCE:g}. "
        "Range use = 100 × |GP| / reference. Target 10–90%. "
        "This is the laboratory's empirical guard, not a lux correction."
    )
    _style_utilization(bar, percent)


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
    port_combo.setFixedWidth(220)

    connect_button = QPushButton("Connect P-9710")
    connect_button.setFixedWidth(180)
    disconnect_button = QPushButton("Disconnect")
    disconnect_button.setFixedWidth(150)
    connection_status = QLabel("Disconnected")
    connection_status.setStyleSheet("color:#8FA9B9;")

    mode_combo = QComboBox()
    mode_combo.addItems(MODE_NAMES)
    mode_combo.setFixedWidth(320)

    header.addWidget(QLabel("Port:"), 0, 0)
    header.addWidget(port_combo, 0, 1)
    header.addWidget(connect_button, 0, 2)
    header.addWidget(disconnect_button, 0, 3)
    header.addWidget(connection_status, 0, 4, 1, 2)
    header.addWidget(QLabel("Measurement mode:"), 1, 0)
    header.addWidget(mode_combo, 1, 1, 1, 2)
    header.setColumnStretch(0, 0)
    header.setColumnStretch(1, 0)
    header.setColumnStretch(2, 0)
    header.setColumnStretch(3, 0)
    header.setColumnStretch(4, 1)
    connection_box = QGroupBox("Connection")
    connection_box.setLayout(header)
    header.setContentsMargins(14, 16, 14, 14)
    header.setHorizontalSpacing(12)
    header.setVerticalSpacing(12)
    connection_status.setWordWrap(True)
    root.addWidget(connection_box)

    stack = QStackedWidget()
    root.addWidget(stack)

    meter_holder = {"meter": None}
    worker_holder = {"worker": None}

    def meter_or_warn():
        meter = meter_holder["meter"]
        if meter is None or not meter.is_connected:
            stop_continuous = getattr(window, "p9710_stop_continuous", None)
            if callable(stop_continuous):
                stop_continuous(error_message="P-9710 is not connected.")
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
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        integration = QDoubleSpinBox()
        integration.setRange(0.1, 6000.0)
        integration.setDecimals(1)
        integration.setSingleStep(10.0)
        integration.setSuffix(" ms")
        integration.setValue(DEFAULT_INTEGRATION_MS)
        integration.setFixedWidth(150)

        range_spin = QSpinBox()
        range_spin.setRange(0, 7)
        range_spin.setValue(DEFAULT_RANGE)
        range_spin.setFixedWidth(100)
        sync_box = QCheckBox("CW synchronisation")

        range_hint = QLabel(_range_interval_text(DEFAULT_RANGE))
        range_hint.setStyleSheet("color:#8FA9B9;")
        range_spin.valueChanged.connect(lambda v: range_hint.setText(_range_interval_text(v)))

        read_button = QPushButton(f"Read {mode_name}")
        read_button.setMinimumWidth(180)
        reset_button = QPushButton("Reset extrema") if accumulated else None
        if reset_button is not None:
            reset_button.setFixedWidth(140)

        result = QLabel(f"{mode_name}: —")
        result.setStyleSheet("font-size:16pt; font-weight:700; color:#E7F2F8;")
        cw_label = QLabel("CW: —")
        peak_max_label = QLabel("Peak max: —")
        peak_min_label = QLabel("Peak min: —")
        p2p_label = QLabel("Peak-to-peak: —")
        utilization_text = QLabel("Range use: —")
        utilization_bar = QProgressBar()
        utilization_bar.setMinimumHeight(24)
        _style_utilization(utilization_bar, None)

        state = {"extreme": None}

        settings = form_section("Measurement settings", [
            ("Integration time:", integration), ("Range:", range_spin),
            ("", range_hint), ("", sync_box),
        ])
        settings.layout().addRow(read_button)
        if reset_button is not None:
            settings.layout().addRow(reset_button)
        page.continuous_controls_layout = QVBoxLayout()
        settings.layout().addRow(page.continuous_controls_layout)
        results = result_section("Live reading", result, cw_label, peak_max_label,
                                 peak_min_label, p2p_label, utilization_text, utilization_bar)
        layout.addWidget(two_columns(settings, results, page))

        def finish_worker():
            worker = worker_holder["worker"]
            if worker is not None:
                worker.deleteLater()
            worker_holder["worker"] = None
            read_button.setEnabled(True)
            if reset_button is not None:
                reset_button.setEnabled(True)

        def failed(message):
            stop_continuous = getattr(window, "p9710_stop_continuous", None)
            if callable(stop_continuous):
                stop_continuous(error_message=message)
            result.setText(f"{mode_name}: measurement failed")
            for label in (cw_label, peak_max_label, peak_min_label, p2p_label):
                label.setText(label.text().split(":", 1)[0] + ": —")
            utilization_text.setText("Range use: unavailable after read error")
            _style_utilization(utilization_bar, None)
            window.p9710_last_cw_reading = None
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

            _update_range_use(utilization_text, utilization_bar,
                              reading.range_utilization_pct, reading.range_id)

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
    egrid = QVBoxLayout(effective_page)
    egrid.setContentsMargins(8, 8, 8, 8)
    egrid.setSpacing(12)

    period_spin = QDoubleSpinBox()
    period_spin.setRange(0.05, 120.0)
    period_spin.setDecimals(4)
    period_spin.setSuffix(" s")
    period_spin.setValue(DEFAULT_PERIOD_S)
    period_spin.setFixedWidth(140)

    pre_spin = QSpinBox()
    pre_spin.setRange(0, 5000)
    pre_spin.setSuffix(" ms")
    pre_spin.setValue(DEFAULT_PRETRIGGER_MS)
    pre_spin.setFixedWidth(120)

    window_spin = QSpinBox()
    window_spin.setRange(100, 10000)
    window_spin.setSingleStep(10)
    window_spin.setSuffix(" ms")
    window_spin.setValue(DEFAULT_WINDOW_MS)
    window_spin.setFixedWidth(120)

    range_spin = QSpinBox()
    range_spin.setRange(0, 7)
    range_spin.setValue(DEFAULT_RANGE)
    range_spin.setFixedWidth(100)
    range_hint = QLabel(_range_interval_text(DEFAULT_RANGE))
    range_hint.setStyleSheet("color:#8FA9B9;")
    range_spin.valueChanged.connect(lambda v: range_hint.setText(_range_interval_text(v)))

    threshold_spin = QDoubleSpinBox()
    threshold_spin.setRange(0.001, 100000.0)
    threshold_spin.setDecimals(3)
    threshold_spin.setSuffix(" lx")
    threshold_spin.setValue(DEFAULT_THRESHOLD_LX)
    threshold_spin.setFixedWidth(140)

    c_spin = QDoubleSpinBox()
    c_spin.setRange(0.001, 10.0)
    c_spin.setDecimals(3)
    c_spin.setSuffix(" s")
    c_spin.setValue(DEFAULT_C_S)
    c_spin.setFixedWidth(120)

    distance_spin = QDoubleSpinBox()
    distance_spin.setRange(0.01, 1000.0)
    distance_spin.setDecimals(3)
    distance_spin.setSuffix(" m")
    distance_spin.setValue(5.0)
    distance_spin.setFixedWidth(120)

    e_button = QPushButton("Measure synchronized")
    e_button.setMinimumWidth(190)
    e_result = QLabel("E-effective: —")
    i_result = QLabel("I-effective: —")
    trigger_result = QLabel("Trigger sample: —")
    e_status = QLabel("Ready")
    e_gp_text = QLabel("Range use: —")
    e_gp_bar = QProgressBar()
    e_gp_bar.setMinimumHeight(24)
    _style_utilization(e_gp_bar, None)

    e_result.setStyleSheet("font-size:18pt; font-weight:700; color:#55EFC4;")
    i_result.setStyleSheet("font-size:18pt; font-weight:700; color:#E7F2F8;")
    settings = form_section("Flash measurement settings", [
        ("Pulse period:", period_spin), ("Range:", range_spin),
        ("", range_hint), ("Distance:", distance_spin),
    ])
    advanced = form_section("Acquisition parameters", [
        ("Pre-trigger:", pre_spin), ("MI window:", window_spin),
        ("Trigger threshold:", threshold_spin), ("Schmidt-Clausen C:", c_spin),
    ])
    settings.layout().addRow(CollapsibleSection("Advanced settings", advanced))
    settings.layout().addRow(e_button)
    results = result_section("Effective measurement", e_result, i_result, trigger_result,
                             e_status, e_gp_text, e_gp_bar)
    egrid.addWidget(two_columns(settings, results, effective_page))

    def effective_finished():
        worker = worker_holder["worker"]
        if worker is not None:
            worker.deleteLater()
        worker_holder["worker"] = None
        e_button.setEnabled(True)

    def effective_failed(message):
        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous(error_message=message)
        e_result.setText("E-effective: —")
        i_result.setText("I-effective: —")
        trigger_result.setText("Trigger sample: —")
        e_gp_text.setText("Range use: unavailable after read error")
        _style_utilization(e_gp_bar, None)
        window.p9710_last_e_effective_lx = None
        window.p9710_last_i_effective_cd = None
        window.p9710_last_reading = None
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
        _update_range_use(e_gp_text, e_gp_bar,
                          reading.range_utilization_pct, reading.range_id)
        window.p9710_last_e_effective_lx = reading.e_effective_lx
        window.p9710_last_i_effective_cd = i_effective
        window.p9710_last_reading = reading

    def start_effective():
        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous()
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
    root.addWidget(CollapsibleSection("About measurement modes", note))

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
