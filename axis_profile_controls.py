from PySide6.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QMessageBox,
)

from machine_config import (
    GAMMA_ID,
    C_ID,
    P1_36,
    P5_20,
    P5_60,
    PROFILE_MIN_MS,
    PROFILE_MAX_MS,
    PROFILE_STEP_MS,
    SPEED_MIN_RPM,
    SPEED_MAX_RPM,
    SPEED_STEP_RPM,
    GAMMA_SPEED_DEFAULT_RPM,
    GAMMA_RAMP_DEFAULT_MS,
    GAMMA_SCURVE_DEFAULT_MS,
    C_SPEED_DEFAULT_RPM,
    C_RAMP_DEFAULT_MS,
    C_SCURVE_DEFAULT_MS,
)
from motion_controller import GAMMA, C_AXIS


def _build_axis_profile_box(window, axis, speed_default, ramp_default, scurve_default):
    box = QGroupBox(f"{axis.name} Axis Motion Profile")
    layout = QGridLayout()

    speed = QDoubleSpinBox()
    speed.setRange(SPEED_MIN_RPM, SPEED_MAX_RPM)
    speed.setSingleStep(SPEED_STEP_RPM)
    speed.setDecimals(1)
    speed.setSuffix(" rpm")
    speed.setValue(speed_default)

    ramp = QSpinBox()
    ramp.setRange(PROFILE_MIN_MS, PROFILE_MAX_MS)
    ramp.setSingleStep(PROFILE_STEP_MS)
    ramp.setSuffix(" ms")
    ramp.setValue(ramp_default)

    scurve = QSpinBox()
    scurve.setRange(PROFILE_MIN_MS, PROFILE_MAX_MS)
    scurve.setSingleStep(PROFILE_STEP_MS)
    scurve.setSuffix(" ms")
    scurve.setValue(scurve_default)

    apply_button = QPushButton(f"Apply to {axis.name} Axis")
    status = QLabel("Not applied in this session")

    layout.addWidget(QLabel("Speed:"), 0, 0)
    layout.addWidget(speed, 0, 1)
    layout.addWidget(QLabel("Ramp (Accel/Decel):"), 0, 2)
    layout.addWidget(ramp, 0, 3)
    layout.addWidget(QLabel("S-curve:"), 0, 4)
    layout.addWidget(scurve, 0, 5)
    layout.addWidget(apply_button, 1, 0, 1, 2)
    layout.addWidget(status, 1, 2, 1, 4)

    box.setLayout(layout)

    def apply_profile():
        if not window.modbus.is_connected:
            QMessageBox.warning(
                window,
                "Not Connected",
                f"Connect to the drives before applying the {axis.name}-axis profile.",
            )
            return

        speed_rpm = speed.value()
        speed_raw = round(speed_rpm * 10.0)
        ramp_ms = ramp.value()
        scurve_ms = scurve.value()

        try:
            window.timer.stop()

            window.modbus.write_u16(axis.slave_id, P5_60, speed_raw)
            speed_readback = window.modbus.read_u16(axis.slave_id, P5_60)
            if speed_readback != speed_raw:
                raise RuntimeError(
                    f"{axis.name}: P5-60 readback {speed_readback / 10:.1f} rpm, "
                    f"expected {speed_rpm:.1f} rpm."
                )

            window.modbus.write_u16(axis.slave_id, P5_20, ramp_ms)
            ramp_readback = window.modbus.read_u16(axis.slave_id, P5_20)
            if ramp_readback != ramp_ms:
                raise RuntimeError(
                    f"{axis.name}: P5-20 readback {ramp_readback} ms, "
                    f"expected {ramp_ms} ms."
                )

            window.modbus.write_u16(axis.slave_id, P1_36, scurve_ms)
            scurve_readback = window.modbus.read_u16(axis.slave_id, P1_36)
            if scurve_readback != scurve_ms:
                raise RuntimeError(
                    f"{axis.name}: P1-36 readback {scurve_readback} ms, "
                    f"expected {scurve_ms} ms."
                )

            window.motion.set_expected_profile(
                axis,
                speed_readback,
                scurve_readback,
            )

            status.setText(
                f"Applied: {speed_readback / 10:.1f} rpm / "
                f"Ramp {ramp_readback} ms / "
                f"S-curve {scurve_readback} ms"
            )

        except Exception as exc:
            QMessageBox.critical(
                window,
                f"{axis.name} Profile Error",
                str(exc),
            )
        finally:
            window.timer.start()

    apply_button.clicked.connect(apply_profile)

    return box, speed, ramp, scurve, apply_button, status


def attach_axis_profile_controls(window):
    """Attach independent Speed/Ramp/S-curve controls for both axes."""

    central = window.centralWidget()
    if central is None or central.layout() is None:
        raise RuntimeError("Main window layout is not available.")

    parent_layout = central.layout()
    insert_index = max(0, parent_layout.count() - 2)

    gamma_controls = _build_axis_profile_box(
        window,
        GAMMA,
        GAMMA_SPEED_DEFAULT_RPM,
        GAMMA_RAMP_DEFAULT_MS,
        GAMMA_SCURVE_DEFAULT_MS,
    )
    c_controls = _build_axis_profile_box(
        window,
        C_AXIS,
        C_SPEED_DEFAULT_RPM,
        C_RAMP_DEFAULT_MS,
        C_SCURVE_DEFAULT_MS,
    )

    parent_layout.insertWidget(insert_index, gamma_controls[0])
    parent_layout.insertWidget(insert_index + 1, c_controls[0])

    (
        window.gamma_profile_box,
        window.gamma_speed_spin,
        window.gamma_ramp_spin,
        window.gamma_scurve_spin,
        window.gamma_profile_apply_button,
        window.gamma_profile_status_label,
    ) = gamma_controls

    (
        window.c_profile_box,
        window.c_speed_spin,
        window.c_ramp_spin,
        window.c_scurve_spin,
        window.c_profile_apply_button,
        window.c_profile_status_label,
    ) = c_controls
