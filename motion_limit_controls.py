"""Configure travel bounds and keep scan inputs within the selected limits."""

from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QMessageBox

from motion_controller import C_AXIS, GAMMA


def apply_axis_limits_to_controls(window):
    for axis, prefix in ((GAMMA, "gamma"), (C_AXIS, "c")):
        limit = window.motion.axis_limit_deg(axis)
        panel = getattr(window, f"{prefix}_panel", None)
        if panel is not None:
            # Accept the requested target verbatim; the move handler reports
            # a limit violation instead of silently clamping the input.
            panel.target_spin.setRange(-1_000_000_000.0, 1_000_000_000.0)
        for base in ("measurement", "measurement_v2"):
            for end in ("start", "end"):
                control = getattr(window, f"{base}_{prefix}_{end}", None)
                if control is not None:
                    control.setRange(-limit, limit)
            step = getattr(window, f"{base}_{prefix}_step", None)
            if step is not None:
                step.setMaximum(2.0 * limit)

    envelope = window.findChild(QLabel, "measurementEnvelope")
    if envelope is not None:
        envelope.setText(
            f"Current travel limits: Gamma ±{window.motion.axis_limit_deg(GAMMA):g}°  •  "
            f"C ±{window.motion.axis_limit_deg(C_AXIS):g}°"
        )


def add_axis_limit_control(window, axis, layout):
    limit_spin = QDoubleSpinBox()
    limit_spin.setObjectName(f"{axis.name.lower()}SoftwareLimit")
    limit_spin.setRange(0.1, 1_000_000_000.0)
    limit_spin.setDecimals(1)
    limit_spin.setSingleStep(1.0)
    limit_spin.setSuffix("°")
    limit_spin.setMinimumWidth(110)
    limit_spin.setKeyboardTracking(False)
    limit_spin.setValue(window.motion.axis_limit_deg(axis))
    limit_spin.setToolTip(
        "Symmetric travel limit around Session Zero for this session. "
        "Press Enter or leave the field to apply."
    )
    limit_label = QLabel("Travel limit (±):")
    limit_label.setStyleSheet("color: #FF7675;")
    limit_spin.setStyleSheet("QDoubleSpinBox, QLineEdit { color: #FF7675; }")
    layout.addWidget(limit_label, 3, 0)
    layout.addWidget(limit_spin, 3, 1)

    def show_confirmation(value):
        status = getattr(window, f"{axis.name.lower()}_profile_status_label", None)
        if status is not None:
            status.setText(f"Confirmed: {axis.name} Travel limit ±{value:g}°")

    def commit_limit():
        previous = window.motion.axis_limit_deg(axis)
        value = limit_spin.value()
        if value == previous:
            show_confirmation(value)
            return
        try:
            for name in ("manual_motion_worker", "measurement_v2_worker",
                         "measurement_worker", "p9710_miol_grid_worker"):
                if getattr(window, name, None) is not None:
                    raise RuntimeError("Wait for the active movement or scan to finish before changing the limit.")
            zero = window.motion.gamma_zero_puu if axis == GAMMA else window.motion.c_zero_puu
            if window.modbus.is_connected and zero is not None:
                current = window.motion.get_current_angle(axis)
                if abs(current) > value + 1e-9:
                    raise ValueError(
                        f"{axis.name} is currently at {current:+.4f}°. "
                        f"Move it inside ±{value:g}° before reducing the limit."
                    )
            window.motion.set_axis_limit_deg(axis, value)
            apply_axis_limits_to_controls(window)
            show_confirmation(value)
        except Exception as exc:
            limit_spin.setValue(previous)
            QMessageBox.warning(window, "Travel Limit", str(exc))

    limit_spin.editingFinished.connect(commit_limit)
    return limit_spin
