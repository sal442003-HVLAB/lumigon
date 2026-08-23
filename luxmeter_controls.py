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


def _available_ports():
    return [port.device for port in list_ports.comports()]


def attach_luxmeter_controls(window):
    """Attach independent Ph-Amp MB7 controls to the main HMI."""

    central = window.centralWidget()
    if central is None or central.layout() is None:
        raise RuntimeError("Main window layout is not available.")

    parent_layout = central.layout()
    insert_index = max(0, parent_layout.count() - 2)

    box = QGroupBox("Luxmeter — C&G Ph-Amp MB7")
    layout = QGridLayout()

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

    status_label = QLabel("● Disconnected")
    status_label.setObjectName("connectionOff")
    id_label = QLabel("Firmware: —")
    current_label = QLabel("Current: —")
    lux_label = QLabel("Lux: —")
    stability_label = QLabel("Std. dev.: —")

    layout.addWidget(QLabel("Port:"), 0, 0)
    layout.addWidget(port_combo, 0, 1)
    layout.addWidget(refresh_ports_button, 0, 2)
    layout.addWidget(connect_button, 0, 3)
    layout.addWidget(disconnect_button, 0, 4)
    layout.addWidget(status_label, 0, 5)

    layout.addWidget(QLabel("Sensitivity:"), 1, 0)
    layout.addWidget(sensitivity_spin, 1, 1)
    layout.addWidget(QLabel("Samples:"), 1, 2)
    layout.addWidget(samples_spin, 1, 3)
    layout.addWidget(QLabel("Integration:"), 1, 4)
    layout.addWidget(integration_spin, 1, 5)

    layout.addWidget(read_button, 2, 0, 1, 2)
    layout.addWidget(current_label, 2, 2)
    layout.addWidget(lux_label, 2, 3)
    layout.addWidget(stability_label, 2, 4)
    layout.addWidget(id_label, 2, 5)

    box.setLayout(layout)

    def _repolish(label):
        label.style().unpolish(label)
        label.style().polish(label)

    def refresh_ports():
        current = port_combo.currentText().strip()
        ports_now = _available_ports()
        port_combo.clear()
        port_combo.addItems(ports_now)
        if current:
            port_combo.setCurrentText(current)
        elif DEFAULT_LUXMETER_PORT in ports_now:
            port_combo.setCurrentText(DEFAULT_LUXMETER_PORT)

    def connect_luxmeter():
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
        status_label.setText("● Connected")
        status_label.setObjectName("connectionOn")
        _repolish(status_label)
        id_label.setText(f"Firmware: {version}")

    def disconnect_luxmeter(silent=False):
        meter = getattr(window, "luxmeter", None)
        if meter is not None:
            try:
                meter.disconnect()
            except Exception as exc:
                if not silent:
                    QMessageBox.warning(window, "Luxmeter Disconnect", str(exc))
        window.luxmeter = None
        status_label.setText("● Disconnected")
        status_label.setObjectName("connectionOff")
        _repolish(status_label)

    def read_lux():
        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            QMessageBox.warning(window, "Luxmeter", "Connect the luxmeter first.")
            return

        try:
            meter.sensitivity_na_per_lx = sensitivity_spin.value()

            requested_integration = integration_spin.value()
            if meter.integration_time_ms != requested_integration:
                meter.set_integration_time(requested_integration)

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

    refresh_ports_button.clicked.connect(refresh_ports)
    connect_button.clicked.connect(connect_luxmeter)
    disconnect_button.clicked.connect(disconnect_luxmeter)
    read_button.clicked.connect(read_lux)

    parent_layout.insertWidget(insert_index, box)

    window.luxmeter_box = box
    window.luxmeter_port_combo = port_combo
    window.luxmeter_refresh_ports_button = refresh_ports_button
    window.luxmeter_connect_button = connect_button
    window.luxmeter_disconnect_button = disconnect_button
    window.luxmeter_read_button = read_button
    window.luxmeter_sensitivity_spin = sensitivity_spin
    window.luxmeter_samples_spin = samples_spin
    window.luxmeter_integration_spin = integration_spin
    window.luxmeter_status_label = status_label
    window.luxmeter_id_label = id_label
    window.luxmeter_current_label = current_label
    window.luxmeter_lux_label = lux_label
    window.luxmeter_stability_label = stability_label
    window.luxmeter = None
