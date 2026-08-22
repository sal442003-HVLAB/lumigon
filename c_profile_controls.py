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
    C_ID,
    P1_36,
    P5_20,
    P5_60,
    C_PROFILE_MIN_MS,
    C_PROFILE_MAX_MS,
    C_PROFILE_STEP_MS,
    C_RAMP_DEFAULT_MS,
    C_SCURVE_DEFAULT_MS,
    C_SPEED_MIN_RPM,
    C_SPEED_MAX_RPM,
    C_SPEED_STEP_RPM,
    C_SPEED_DEFAULT_RPM,
)


def attach_c_profile_controls(window):
    """Attach commissioning controls for C-axis PR ramp, S-curve and speed."""

    central = window.centralWidget()
    if central is None or central.layout() is None:
        raise RuntimeError("Main window layout is not available.")

    box = QGroupBox("C Axis Motion Profile")
    layout = QGridLayout()

    ramp = QSpinBox()
    ramp.setRange(C_PROFILE_MIN_MS, C_PROFILE_MAX_MS)
    ramp.setSingleStep(C_PROFILE_STEP_MS)
    ramp.setSuffix(" ms")
    ramp.setValue(C_RAMP_DEFAULT_MS)

    scurve = QSpinBox()
    scurve.setRange(C_PROFILE_MIN_MS, C_PROFILE_MAX_MS)
    scurve.setSingleStep(C_PROFILE_STEP_MS)
    scurve.setSuffix(" ms")
    scurve.setValue(C_SCURVE_DEFAULT_MS)

    speed = QDoubleSpinBox()
    speed.setRange(C_SPEED_MIN_RPM, C_SPEED_MAX_RPM)
    speed.setSingleStep(C_SPEED_STEP_RPM)
    speed.setDecimals(1)
    speed.setSuffix(" rpm")
    speed.setValue(C_SPEED_DEFAULT_RPM)

    apply_button = QPushButton("Apply to C Axis")
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

    # Insert above the Session Zero / safety controls while preserving
    # the existing v0.3.4 axis panels and movement controls.
    parent_layout = central.layout()
    insert_index = max(0, parent_layout.count() - 2)
    parent_layout.insertWidget(insert_index, box)

    def apply_profile():
        if not window.modbus.is_connected:
            QMessageBox.warning(
                window,
                "Not Connected",
                "Connect to the drives before applying the C-axis profile.",
            )
            return

        speed_rpm = speed.value()
        speed_raw = round(speed_rpm * 10.0)
        ramp_ms = ramp.value()
        scurve_ms = scurve.value()

        try:
            window.timer.stop()

            window.modbus.write_u16(C_ID, P5_60, speed_raw)
            speed_readback = window.modbus.read_u16(C_ID, P5_60)
            if speed_readback != speed_raw:
                raise RuntimeError(
                    f"C: P5-60 readback {speed_readback / 10:.1f} rpm, "
                    f"expected {speed_rpm:.1f} rpm."
                )

            window.modbus.write_u16(C_ID, P5_20, ramp_ms)
            ramp_readback = window.modbus.read_u16(C_ID, P5_20)
            if ramp_readback != ramp_ms:
                raise RuntimeError(
                    f"C: P5-20 readback {ramp_readback} ms, "
                    f"expected {ramp_ms} ms."
                )

            window.modbus.write_u16(C_ID, P1_36, scurve_ms)
            scurve_readback = window.modbus.read_u16(C_ID, P1_36)
            if scurve_readback != scurve_ms:
                raise RuntimeError(
                    f"C: P1-36 readback {scurve_readback} ms, "
                    f"expected {scurve_ms} ms."
                )

            # Keep MotionController safety verification synchronized with
            # the operator-selected C-axis profile values.
            window.motion.c_expected_speed_raw = speed_raw
            window.motion.c_expected_scurve_ms = scurve_ms

            status.setText(
                f"Applied: {speed_readback / 10:.1f} rpm / "
                f"Ramp {ramp_readback} ms / "
                f"S-curve {scurve_readback} ms"
            )

        except Exception as exc:
            QMessageBox.critical(
                window,
                "C Profile Error",
                str(exc),
            )
        finally:
            window.timer.start()

    apply_button.clicked.connect(apply_profile)

    window.c_speed_spin = speed
    window.c_ramp_spin = ramp
    window.c_scurve_spin = scurve
    window.c_profile_apply_button = apply_button
    window.c_profile_status_label = status
