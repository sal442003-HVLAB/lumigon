import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
)
from serial.tools import list_ports

from phamp_mb7 import (
    DEFAULT_INTEGRATION_TIME_MS,
    DEFAULT_SENSITIVITY_NA_PER_LX,
    PhAmpMB7,
    PhAmpError,
)


DEFAULT_LUXMETER_PORT = "COM9"
DEFAULT_SAMPLES = 5
DEFAULT_LIVE_INTERVAL_MS = 100

LUXMETER_CG = "C&G Ph-Amp MB7"
LUXMETER_GIGAHERTZ = "Gigahertz-Optik P-9710"


class LuxmeterLiveWorker(QThread):
    """Poll the latest Ph-Amp reading continuously without blocking the GUI."""

    reading_ready = Signal(float, float, float)
    read_error = Signal(str)

    def __init__(self, meter, interval_ms, warmup_ms=0, parent=None):
        super().__init__(parent)
        self.meter = meter
        self.interval_ms = int(interval_ms)
        self.warmup_ms = max(0, int(warmup_ms))

    def run(self):
        if self.warmup_ms:
            self.msleep(self.warmup_ms)

        last_emit_time = None

        while not self.isInterruptionRequested():
            cycle_started = time.monotonic()

            try:
                current_a = self.meter.read_current()
                lux = self.meter.current_to_lux(current_a)
            except Exception as exc:
                self.read_error.emit(str(exc))
                return

            now = time.monotonic()
            if last_emit_time is None:
                actual_interval_ms = 0.0
            else:
                actual_interval_ms = (now - last_emit_time) * 1000.0
            last_emit_time = now

            self.reading_ready.emit(current_a, lux, actual_interval_ms)

            elapsed_ms = (time.monotonic() - cycle_started) * 1000.0
            remaining_ms = max(0.0, self.interval_ms - elapsed_ms)

            # Sleep in short pieces so Stop Live reacts promptly.
            while remaining_ms > 0 and not self.isInterruptionRequested():
                chunk_ms = min(10, int(remaining_ms))
                if chunk_ms <= 0:
                    break
                self.msleep(chunk_ms)
                remaining_ms -= chunk_ms


def _available_ports():
    return [port.device for port in list_ports.comports()]


def attach_luxmeter_controls(window):
    """Attach selectable luxmeter controls to the main HMI."""

    central = window.centralWidget()
    if central is None or central.layout() is None:
        raise RuntimeError("Main window layout is not available.")

    parent_layout = central.layout()
    insert_index = max(0, parent_layout.count() - 2)

    box = QGroupBox(f"Luxmeter — {LUXMETER_CG}")
    layout = QGridLayout()

    instrument_combo = QComboBox()
    instrument_combo.addItems([
        LUXMETER_CG,
        LUXMETER_GIGAHERTZ,
    ])
    instrument_combo.setCurrentText(LUXMETER_CG)
    instrument_combo.setToolTip(
        "Select the photometer/luxmeter used for this Lumigon session."
    )

    port_combo = QComboBox()
    port_combo.setEditable(True)
    ports = _available_ports()
    port_combo.addItems(ports)
    if DEFAULT_LUXMETER_PORT in ports:
        port_combo.setCurrentText(DEFAULT_LUXMETER_PORT)
    else:
        port_combo.setCurrentText(DEFAULT_LUXMETER_PORT)

    refresh_ports_button = QPushButton("Refresh Ports")
    connect_button = QPushButton("Connect Luxmeter")
    disconnect_button = QPushButton("Disconnect")
    read_button = QPushButton("Read Lux")
    start_live_button = QPushButton("Start Live")
    stop_live_button = QPushButton("Stop Live")

    sensitivity_spin = QDoubleSpinBox()
    sensitivity_spin.setRange(0.001, 1000000.0)
    sensitivity_spin.setDecimals(4)
    sensitivity_spin.setSingleStep(0.01)
    sensitivity_spin.setSuffix(" nA/lx")
    sensitivity_spin.setValue(DEFAULT_SENSITIVITY_NA_PER_LX)

    samples_spin = QSpinBox()
    samples_spin.setRange(1, 50)
    samples_spin.setValue(DEFAULT_SAMPLES)

    integration_spin = QSpinBox()
    integration_spin.setRange(10, 400)
    integration_spin.setSingleStep(10)
    integration_spin.setSuffix(" ms")
    integration_spin.setValue(DEFAULT_INTEGRATION_TIME_MS)

    live_interval_spin = QSpinBox()
    live_interval_spin.setRange(10, 5000)
    live_interval_spin.setSingleStep(10)
    live_interval_spin.setSuffix(" ms")
    live_interval_spin.setValue(DEFAULT_LIVE_INTERVAL_MS)

    status_label = QLabel("● Disconnected")
    status_label.setObjectName("connectionOff")
    live_status_label = QLabel("Live: Stopped")
    id_label = QLabel("Firmware: —")
    current_label = QLabel("Current: —")
    lux_label = QLabel("Lux: —")
    stability_label = QLabel("Std. dev.: —")

    layout.addWidget(QLabel("Instrument:"), 0, 0)
    layout.addWidget(instrument_combo, 0, 1, 1, 3)
    layout.addWidget(status_label, 0, 5)

    layout.addWidget(QLabel("Port:"), 1, 0)
    layout.addWidget(port_combo, 1, 1)
    layout.addWidget(refresh_ports_button, 1, 2)
    layout.addWidget(connect_button, 1, 3)
    layout.addWidget(disconnect_button, 1, 4)

    layout.addWidget(QLabel("Sensitivity:"), 2, 0)
    layout.addWidget(sensitivity_spin, 2, 1)
    layout.addWidget(QLabel("Samples:"), 2, 2)
    layout.addWidget(samples_spin, 2, 3)
    layout.addWidget(QLabel("Integration:"), 2, 4)
    layout.addWidget(integration_spin, 2, 5)

    layout.addWidget(read_button, 3, 0)
    layout.addWidget(start_live_button, 3, 1)
    layout.addWidget(stop_live_button, 3, 2)
    layout.addWidget(QLabel("Poll interval:"), 3, 3)
    layout.addWidget(live_interval_spin, 3, 4)
    layout.addWidget(live_status_label, 3, 5)

    layout.addWidget(current_label, 4, 0, 1, 2)
    layout.addWidget(lux_label, 4, 2)
    layout.addWidget(stability_label, 4, 3)
    layout.addWidget(id_label, 4, 4, 1, 2)

    box.setLayout(layout)

    def _repolish(label):
        label.style().unpolish(label)
        label.style().polish(label)

    def _live_worker():
        worker = getattr(window, "luxmeter_live_worker", None)
        if worker is not None and worker.isRunning():
            return worker
        return None

    def _selected_instrument():
        return instrument_combo.currentText()

    def _update_controls():
        meter = getattr(window, "luxmeter", None)
        connected = meter is not None and meter.is_connected
        live = _live_worker() is not None
        cg_selected = _selected_instrument() == LUXMETER_CG

        instrument_combo.setEnabled(not connected and not live)
        port_combo.setEnabled(not connected and not live)
        refresh_ports_button.setEnabled(not connected and not live)
        connect_button.setEnabled(not connected and not live)
        disconnect_button.setEnabled(connected)

        # These controls currently belong to the C&G Ph-Amp driver. P-9710
        # parameters will be exposed when its RS232 driver is added.
        sensitivity_spin.setEnabled(cg_selected and not live)
        integration_spin.setEnabled(cg_selected and not live)
        live_interval_spin.setEnabled(cg_selected and not live)
        samples_spin.setEnabled(cg_selected and not live)

        read_button.setEnabled(cg_selected and connected and not live)
        start_live_button.setEnabled(cg_selected and connected and not live)
        stop_live_button.setEnabled(live)

    def instrument_changed(*_args):
        selected = _selected_instrument()
        box.setTitle(f"Luxmeter — {selected}")
        window.luxmeter_selected_instrument = selected

        if selected == LUXMETER_GIGAHERTZ:
            id_label.setText("P-9710 RS232 driver: pending hardware validation")
            current_label.setText("Current: —")
            lux_label.setText("Lux: —")
            stability_label.setText("Std. dev.: —")
        else:
            id_label.setText("Firmware: —")

        _update_controls()

    def refresh_ports():
        current = port_combo.currentText().strip()
        ports_now = _available_ports()
        port_combo.clear()
        port_combo.addItems(ports_now)
        if current:
            port_combo.setCurrentText(current)
        elif DEFAULT_LUXMETER_PORT in ports_now:
            port_combo.setCurrentText(DEFAULT_LUXMETER_PORT)

    def _set_connected_state(version):
        status_label.setText("● Connected")
        status_label.setObjectName("connectionOn")
        _repolish(status_label)
        id_label.setText(f"Firmware: {version}")
        _update_controls()

    def _set_disconnected_state():
        status_label.setText("● Disconnected")
        status_label.setObjectName("connectionOff")
        _repolish(status_label)
        live_status_label.setText("Live: Stopped")
        _update_controls()

    def _stop_live(wait=True):
        worker = _live_worker()
        if worker is None:
            window.luxmeter_live_worker = None
            live_status_label.setText("Live: Stopped")
            _update_controls()
            return True

        worker.requestInterruption()

        if wait:
            if not worker.wait(1000):
                return False

        return True

    def connect_luxmeter():
        selected = _selected_instrument()
        window.luxmeter_selected_instrument = selected

        if selected == LUXMETER_GIGAHERTZ:
            QMessageBox.information(
                window,
                "Gigahertz-Optik P-9710",
                "P-9710 has been selected for this session.\n\n"
                "Its RS232 command set is available, but the Lumigon P-9710 driver "
                "will be enabled after connection and hardware validation with the instrument.",
            )
            return

        port = port_combo.currentText().strip()
        if not port:
            QMessageBox.warning(window, "Luxmeter Port", "Select a COM port first.")
            return

        disconnect_luxmeter(silent=True)

        meter = PhAmpMB7(
            port,
            sensitivity_na_per_lx=sensitivity_spin.value(),
            integration_time_ms=integration_spin.value(),
        )

        try:
            version = meter.connect()
            meter.configure_for_lumigon()
        except Exception as exc:
            meter.disconnect()
            QMessageBox.critical(window, "Luxmeter Connection Error", str(exc))
            return

        window.luxmeter = meter
        _set_connected_state(version)

    def disconnect_luxmeter(silent=False):
        if not _stop_live(wait=True):
            if not silent:
                QMessageBox.warning(
                    window,
                    "Luxmeter Disconnect",
                    "Live acquisition is still stopping. Try Disconnect again in a moment.",
                )
            return

        meter = getattr(window, "luxmeter", None)
        if meter is not None:
            try:
                meter.disconnect()
            except Exception as exc:
                if not silent:
                    QMessageBox.warning(window, "Luxmeter Disconnect", str(exc))
        window.luxmeter = None
        _set_disconnected_state()

    def _apply_measurement_settings(meter):
        meter.sensitivity_na_per_lx = sensitivity_spin.value()

        requested_integration = integration_spin.value()
        if meter.integration_time_ms != requested_integration:
            meter.set_integration_time(requested_integration)

    def read_lux():
        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "Luxmeter", "Connect the luxmeter first.")
            return

        if _live_worker() is not None:
            QMessageBox.warning(window, "Luxmeter", "Stop Live acquisition before Read Lux.")
            return

        try:
            _apply_measurement_settings(meter)
            meter.set_software_trigger()
            reading = meter.read_lux(samples=samples_spin.value())
        except (PhAmpError, ValueError) as exc:
            QMessageBox.critical(window, "Luxmeter Read Error", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(window, "Unexpected Luxmeter Error", str(exc))
            return

        current_na = reading.mean_current_a * 1e9
        current_label.setText(f"Current: {current_na:.2f} nA")
        lux_label.setText(f"Lux: {reading.lux:.3f} lx")
        stability_label.setText(f"Std. dev.: {reading.stdev_lux:.3f} lx")

        window.luxmeter_last_current_a = reading.mean_current_a
        window.luxmeter_last_lux = reading.lux

    def _update_live_reading(current_a, lux, actual_interval_ms):
        current_na = current_a * 1e9
        current_label.setText(f"Current: {current_na:.2f} nA")
        lux_label.setText(f"Lux: {lux:.3f} lx")

        if actual_interval_ms > 0:
            live_status_label.setText(
                f"Live: Running | actual {actual_interval_ms:.0f} ms"
            )
        else:
            live_status_label.setText("Live: Running")

        window.luxmeter_last_current_a = current_a
        window.luxmeter_last_lux = lux
        window.luxmeter_last_live_timestamp = time.time()
        window.luxmeter_last_live_interval_ms = actual_interval_ms

    def _live_error(message):
        live_status_label.setText("Live: Error")
        QMessageBox.critical(window, "Luxmeter Live Error", message)

    def _live_finished():
        worker = getattr(window, "luxmeter_live_worker", None)
        if worker is not None:
            worker.deleteLater()
        window.luxmeter_live_worker = None

        meter = getattr(window, "luxmeter", None)
        restore_error = None
        if meter is not None and meter.is_connected:
            try:
                # Formal Read Lux uses T1 so every M? acquires a fresh sample.
                meter.set_software_trigger()
            except Exception as exc:
                restore_error = str(exc)

        if live_status_label.text() != "Live: Error":
            if restore_error:
                live_status_label.setText("Live: Stopped | T1 restore error")
            else:
                live_status_label.setText("Live: Stopped")
        _update_controls()

    def start_live():
        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "Luxmeter", "Connect the luxmeter first.")
            return

        if _live_worker() is not None:
            return

        try:
            _apply_measurement_settings(meter)

            # T0 is the correct mode for a real-time display: the Ph-Amp measures
            # continuously and M? returns the latest completed reading instead of
            # starting a brand-new integration for every UI refresh.
            meter.set_internal_trigger()
        except (PhAmpError, ValueError) as exc:
            QMessageBox.critical(window, "Luxmeter Live Setup Error", str(exc))
            return
        except Exception as exc:
            QMessageBox.critical(window, "Unexpected Luxmeter Error", str(exc))
            return

        worker = LuxmeterLiveWorker(
            meter,
            interval_ms=live_interval_spin.value(),
            warmup_ms=meter.integration_time_ms + 10,
            parent=window,
        )
        worker.reading_ready.connect(_update_live_reading)
        worker.read_error.connect(_live_error)
        worker.finished.connect(_live_finished)

        window.luxmeter_live_worker = worker
        live_status_label.setText("Live: Starting…")
        stability_label.setText("Std. dev.: — (Live uses latest continuous sample)")

        worker.start()
        _update_controls()

    def stop_live():
        worker = _live_worker()
        if worker is None:
            live_status_label.setText("Live: Stopped")
            _update_controls()
            return

        live_status_label.setText("Live: Stopping…")
        worker.requestInterruption()

    instrument_combo.currentIndexChanged.connect(instrument_changed)
    refresh_ports_button.clicked.connect(refresh_ports)
    connect_button.clicked.connect(connect_luxmeter)
    disconnect_button.clicked.connect(disconnect_luxmeter)
    read_button.clicked.connect(read_lux)
    start_live_button.clicked.connect(start_live)
    stop_live_button.clicked.connect(stop_live)

    parent_layout.insertWidget(insert_index, box)

    window.luxmeter_box = box
    window.luxmeter_instrument_combo = instrument_combo
    window.luxmeter_selected_instrument = instrument_combo.currentText()
    window.luxmeter_port_combo = port_combo
    window.luxmeter_refresh_ports_button = refresh_ports_button
    window.luxmeter_connect_button = connect_button
    window.luxmeter_disconnect_button = disconnect_button
    window.luxmeter_read_button = read_button
    window.luxmeter_start_live_button = start_live_button
    window.luxmeter_stop_live_button = stop_live_button
    window.luxmeter_sensitivity_spin = sensitivity_spin
    window.luxmeter_samples_spin = samples_spin
    window.luxmeter_integration_spin = integration_spin
    window.luxmeter_live_interval_spin = live_interval_spin
    window.luxmeter_status_label = status_label
    window.luxmeter_live_status_label = live_status_label
    window.luxmeter_id_label = id_label
    window.luxmeter_current_label = current_label
    window.luxmeter_lux_label = lux_label
    window.luxmeter_stability_label = stability_label
    window.luxmeter = None
    window.luxmeter_live_worker = None
    window.luxmeter_last_current_a = None
    window.luxmeter_last_lux = None
    window.luxmeter_last_live_timestamp = None
    window.luxmeter_last_live_interval_ms = None

    instrument_changed()
    _update_controls()
