"""Motor Control refinements for safe, repeatable manual operation."""

from __future__ import annotations

from types import MethodType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from machine_config import (
    JOG_STEP_DEG,
    P1_36,
    P5_20,
    P5_60,
    GAMMA_SPEED_DEFAULT_RPM,
    GAMMA_RAMP_DEFAULT_MS,
    GAMMA_SCURVE_DEFAULT_MS,
    C_SPEED_DEFAULT_RPM,
    C_RAMP_DEFAULT_MS,
    C_SCURVE_DEFAULT_MS,
)
from motion_controller import GAMMA, C_AXIS


ZERO_PENDING_STYLE = """
QPushButton#sessionZeroButton {
    background-color: #A66A00;
    color: #FFF7E6;
    border: 1px solid #D79A2B;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 700;
}
QPushButton#sessionZeroButton:hover { background-color: #C17A00; }
QPushButton#sessionZeroButton:pressed { background-color: #835300; }
"""

ZERO_SET_STYLE = """
QPushButton#sessionZeroButton {
    background-color: #1F8A5B;
    color: #F3FFF8;
    border: 1px solid #43B581;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: 700;
}
QPushButton#sessionZeroButton:hover { background-color: #249E68; }
QPushButton#sessionZeroButton:pressed { background-color: #176B46; }
"""


def _write_verified_profile(window, axis, speed_rpm, ramp_ms, scurve_ms):
    speed_raw = round(float(speed_rpm) * 10.0)

    window.modbus.write_u16(axis.slave_id, P5_60, speed_raw)
    speed_readback = window.modbus.read_u16(axis.slave_id, P5_60)
    if speed_readback != speed_raw:
        raise RuntimeError(
            f"{axis.name}: speed readback {speed_readback / 10:.1f} rpm; "
            f"expected {speed_rpm:.1f} rpm."
        )

    window.modbus.write_u16(axis.slave_id, P5_20, int(ramp_ms))
    ramp_readback = window.modbus.read_u16(axis.slave_id, P5_20)
    if ramp_readback != int(ramp_ms):
        raise RuntimeError(
            f"{axis.name}: ramp readback {ramp_readback} ms; expected {ramp_ms} ms."
        )

    window.modbus.write_u16(axis.slave_id, P1_36, int(scurve_ms))
    scurve_readback = window.modbus.read_u16(axis.slave_id, P1_36)
    if scurve_readback != int(scurve_ms):
        raise RuntimeError(
            f"{axis.name}: S-curve readback {scurve_readback} ms; "
            f"expected {scurve_ms} ms."
        )

    window.motion.set_expected_profile(
        axis,
        speed_readback,
        ramp_readback,
        scurve_readback,
    )


def attach_motor_control_refinement(window):
    """Apply one-degree manual jogs, zero-state UI and automatic drive profiles."""

    # ------------------------------------------------------------------
    # Manual jog presentation and confirmation.
    # Existing button lambdas resolve window.jog_axis at click time, so replacing
    # the bound method here also fixes the old hard-coded 0.1-degree prompt.
    # ------------------------------------------------------------------
    for panel in (
        getattr(window, "gamma_panel", None),
        getattr(window, "c_panel", None),
    ):
        if panel is None:
            continue
        panel.jog_minus_button.setText(f"-{JOG_STEP_DEG:g}°")
        panel.jog_plus_button.setText(f"+{JOG_STEP_DEG:g}°")
        panel.target_spin.setSingleStep(float(JOG_STEP_DEG))

    def jog_axis_refined(self, axis, delta_degree):
        if not self.modbus.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to the drives first.")
            return
        if self.gamma_zero_puu is None or self.c_zero_puu is None:
            QMessageBox.warning(
                self,
                "Session Zero Required",
                "Set Zero for both axes before movement.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Confirm Limited Jog",
            f"{axis.name}: move {delta_degree:+g}°?\n\n"
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.timer.stop()
        try:
            self.motion.jog(axis, delta_degree)
            QTimer.singleShot(500, self.refresh_data)
        except Exception as exc:
            QMessageBox.critical(self, "Movement Blocked", str(exc))
        finally:
            self.timer.start()

    window.jog_axis = MethodType(jog_axis_refined, window)

    # ------------------------------------------------------------------
    # Session Zero: a single stateful button. Amber = not set, green = set.
    # The old side label remains only as an internal success sentinel and is
    # hidden from the operator.
    # ------------------------------------------------------------------
    zero_button = getattr(window, "zero_button", None)
    zero_label = getattr(window, "zero_info_label", None)

    if zero_button is not None:
        zero_button.setText("Set Zero — Both Axes")
        zero_button.setObjectName("sessionZeroButton")
        zero_button.setToolTip(
            "Set the current physical position as zero for both Gamma and C axes."
        )
        zero_button.setStyleSheet(ZERO_PENDING_STYLE)

        original_zero = window.capture_session_zero
        try:
            zero_button.clicked.disconnect()
        except Exception:
            pass

        def set_zero_and_update_button():
            old_gamma = window.gamma_zero_puu
            old_c = window.c_zero_puu
            old_label = zero_label.text() if zero_label is not None else ""
            if zero_label is not None:
                zero_label.setText("__zero_capture_pending__")

            original_zero()

            success = bool(
                zero_label is not None
                and zero_label.text().startswith("Session zero:")
                and window.gamma_zero_puu is not None
                and window.c_zero_puu is not None
            )
            if success:
                zero_button.setText("Zero Set — Both Axes")
                zero_button.setStyleSheet(ZERO_SET_STYLE)
                zero_button.setToolTip(
                    f"Gamma zero: {window.gamma_zero_puu:+d} PUU\n"
                    f"C zero: {window.c_zero_puu:+d} PUU"
                )
                return

            # A failed re-zero must not leave a partially updated reference.
            window.gamma_zero_puu = old_gamma
            window.c_zero_puu = old_c
            if old_gamma is not None and old_c is not None:
                window.motion.set_session_zero(old_gamma, old_c)
            if zero_label is not None:
                zero_label.setText(old_label)

        zero_button.clicked.connect(set_zero_and_update_button)

    if zero_label is not None:
        zero_label.hide()

    # ------------------------------------------------------------------
    # Connect wrapper: always write and verify the confirmed default motion
    # profile on both drives after communication succeeds.
    # ------------------------------------------------------------------
    connect_button = getattr(window, "connect_button", None)
    original_connect = window.connect_drives
    if connect_button is not None:
        try:
            connect_button.clicked.disconnect()
        except Exception:
            pass

        def connect_with_default_profiles():
            original_connect()
            if not window.modbus.is_connected:
                return

            try:
                _write_verified_profile(
                    window,
                    GAMMA,
                    GAMMA_SPEED_DEFAULT_RPM,
                    GAMMA_RAMP_DEFAULT_MS,
                    GAMMA_SCURVE_DEFAULT_MS,
                )
                _write_verified_profile(
                    window,
                    C_AXIS,
                    C_SPEED_DEFAULT_RPM,
                    C_RAMP_DEFAULT_MS,
                    C_SCURVE_DEFAULT_MS,
                )
            except Exception as exc:
                window.disconnect_drives()
                QMessageBox.critical(
                    window,
                    "Motion Profile Verification Error",
                    "Drive communication succeeded, but the default motion profile "
                    f"could not be verified on both axes.\n\n{exc}",
                )
                return

            window.connection_label.setToolTip(
                "Connected. Default motion profile verified on both axes: "
                "5.0 rpm / Ramp 300 ms / S-curve 2000 ms."
            )

        connect_button.clicked.connect(connect_with_default_profiles)

    # Axis-profile widgets are attached immediately after this refinement in
    # main.py. Hide their manual Apply controls once the event loop starts and
    # leave the confirmed defaults visible as read-only information.
    def finalize_profile_ui():
        profile_sets = (
            (
                getattr(window, "gamma_speed_spin", None),
                getattr(window, "gamma_ramp_spin", None),
                getattr(window, "gamma_scurve_spin", None),
                getattr(window, "gamma_profile_apply_button", None),
                getattr(window, "gamma_profile_status_label", None),
                GAMMA_SPEED_DEFAULT_RPM,
                GAMMA_RAMP_DEFAULT_MS,
                GAMMA_SCURVE_DEFAULT_MS,
            ),
            (
                getattr(window, "c_speed_spin", None),
                getattr(window, "c_ramp_spin", None),
                getattr(window, "c_scurve_spin", None),
                getattr(window, "c_profile_apply_button", None),
                getattr(window, "c_profile_status_label", None),
                C_SPEED_DEFAULT_RPM,
                C_RAMP_DEFAULT_MS,
                C_SCURVE_DEFAULT_MS,
            ),
        )

        for speed, ramp, scurve, apply_button, status, sv, rv, cv in profile_sets:
            if speed is not None:
                speed.setValue(float(sv))
                speed.setEnabled(False)
                speed.setToolTip("Applied and verified automatically when drives connect.")
            if ramp is not None:
                ramp.setValue(int(rv))
                ramp.setEnabled(False)
                ramp.setToolTip("Applied and verified automatically when drives connect.")
            if scurve is not None:
                scurve.setValue(int(cv))
                scurve.setEnabled(False)
                scurve.setToolTip("Applied and verified automatically when drives connect.")
            if apply_button is not None:
                apply_button.hide()
            if status is not None:
                status.setText("Auto-applied on Connect")
                status.setStyleSheet("color: #7FB8A4;")

    QTimer.singleShot(0, finalize_profile_ui)
    return zero_button
