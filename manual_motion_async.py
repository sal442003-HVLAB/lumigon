"""Responsive manual motion for Lumigon Motor Control.

The original manual move handlers call MotionController synchronously from the
Qt GUI thread. Long moves therefore freeze the HMI until the target is reached.
This module keeps the Modbus bus single-owner during motion, but moves the
blocking motion transaction to a QThread and forwards the position feedback
already read by MotionController.wait_for_target() back to the UI.

This deliberately does NOT run the normal Modbus refresh timer in parallel with
motion. Doing so would let two threads share the RTU serial bus and can corrupt
frames. Live position/angle are instead sourced from the motion worker's own
P0-09 polling, so the operator sees encoder PUU and angle while the UI remains
responsive.
"""

from __future__ import annotations

import time
from types import MethodType

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import QMessageBox

from machine_config import MOVE_TIMEOUT_SECONDS, MOTION_POLL_INTERVAL_SECONDS, P0_01, P0_09
from motion_controller import GAMMA, C_AXIS, MotionController


_ORIGINAL_WAIT_FOR_TARGET = MotionController.wait_for_target
_PATCHED = False


def _wait_for_target_with_live_feedback(
    self: MotionController,
    axis,
    expected_feedback: int,
    timeout_seconds: float = None,
):
    """Original target wait plus optional thread-safe progress callback."""

    timeout = (
        MOVE_TIMEOUT_SECONDS
        if timeout_seconds is None
        else max(1.0, float(timeout_seconds))
    )
    deadline = time.monotonic() + timeout
    last_feedback = None

    while time.monotonic() < deadline:
        alarm = self.modbus.read_u16(axis.slave_id, P0_01)
        if alarm != 0:
            raise RuntimeError(f"{axis.name}: alarm 0x{alarm:04X} during motion.")

        last_feedback = self.modbus.read_s32(axis.slave_id, P0_09)
        callback = getattr(self, "live_feedback_callback", None)
        if callable(callback):
            try:
                callback(axis, int(last_feedback))
            except Exception:
                # UI telemetry must never abort an otherwise safe motion.
                pass

        if abs(last_feedback - expected_feedback) <= axis.tolerance_puu:
            return

        time.sleep(MOTION_POLL_INTERVAL_SECONDS)

    raise RuntimeError(
        f"{axis.name}: motion timeout after {timeout:.1f} s. "
        f"Expected {expected_feedback:+d} PUU, "
        f"last feedback {last_feedback:+d} PUU."
    )


def install_live_motion_feedback():
    global _PATCHED
    if _PATCHED:
        return
    MotionController.wait_for_target = _wait_for_target_with_live_feedback
    _PATCHED = True


class ManualMotionWorker(QThread):
    feedback = Signal(object, int)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(self, motion, action: str, axis, value=None, parent=None):
        super().__init__(parent)
        self.motion = motion
        self.action = str(action)
        self.axis = axis
        self.value = value

    def run(self):
        def publish(axis, feedback_puu):
            self.feedback.emit(axis, int(feedback_puu))

        self.motion.live_feedback_callback = publish
        try:
            if self.action == "move":
                self.motion.move_absolute(self.axis, float(self.value))
                message = f"{self.axis.name} reached {float(self.value):+.3f}°."
            elif self.action == "zero":
                self.motion.return_to_zero(self.axis)
                message = f"{self.axis.name} returned to 0.000°."
            elif self.action == "jog":
                self.motion.jog(self.axis, float(self.value))
                message = f"{self.axis.name} jog {float(self.value):+g}° complete."
            else:
                raise RuntimeError(f"Unsupported manual motion action: {self.action}")
            self.succeeded.emit(message)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.motion.live_feedback_callback = None


def attach_async_manual_motion(window):
    """Replace manual Motor Control actions with responsive worker-thread moves."""

    install_live_motion_feedback()
    if getattr(window, "manual_motion_worker", None) is not None:
        return

    window.manual_motion_worker = None
    timer_state = {"was_active": False}

    def panel_for_axis(axis):
        return window.gamma_panel if axis.slave_id == GAMMA.slave_id else window.c_panel

    def update_live_feedback(axis, feedback_puu: int):
        panel = panel_for_axis(axis)
        panel.position_label.setText(f"{int(feedback_puu):+d} PUU")

        zero = window.gamma_zero_puu if axis.slave_id == GAMMA.slave_id else window.c_zero_puu
        if zero is None:
            panel.angle_label.setText("Zero not set")
            return

        angle = window.motion.puu_to_degree(axis, int(feedback_puu) - int(zero))
        panel.angle_label.setText(f"{angle:+.4f}°")

    def set_motion_controls_enabled(enabled: bool):
        for panel in (window.gamma_panel, window.c_panel):
            for control in (
                panel.jog_minus_button,
                panel.jog_plus_button,
                panel.move_button,
                panel.zero_return_button,
                panel.target_spin,
            ):
                control.setEnabled(bool(enabled))

    def finish_worker():
        worker = window.manual_motion_worker
        if worker is not None:
            worker.deleteLater()
        window.manual_motion_worker = None
        set_motion_controls_enabled(True)

        if timer_state["was_active"] and window.modbus.is_connected:
            window.timer.start()
        timer_state["was_active"] = False

        # One full status refresh after the worker releases the serial bus.
        QTimer.singleShot(0, window.refresh_data)

    def start_worker(action: str, axis, value=None):
        if window.manual_motion_worker is not None:
            QMessageBox.information(
                window,
                "Motion in Progress",
                "Wait for the current axis move to finish before starting another move.",
            )
            return

        timer_state["was_active"] = bool(window.timer.isActive())
        if timer_state["was_active"]:
            window.timer.stop()

        worker = ManualMotionWorker(
            window.motion,
            action,
            axis,
            value=value,
            parent=window,
        )
        window.manual_motion_worker = worker
        set_motion_controls_enabled(False)
        worker.feedback.connect(update_live_feedback)
        worker.succeeded.connect(lambda text: panel_for_axis(axis).status_label.setText(text))
        worker.failed.connect(
            lambda text: QMessageBox.critical(window, "Movement Blocked", text)
        )
        worker.finished.connect(finish_worker)
        worker.start()

    def precheck(self):
        if not self.modbus.is_connected:
            QMessageBox.warning(self, "Not Connected", "Connect to the drives first.")
            return False
        if self.gamma_zero_puu is None or self.c_zero_puu is None:
            QMessageBox.warning(
                self,
                "Session Zero Required",
                "Set Zero for both axes before movement.",
            )
            return False
        if self.manual_motion_worker is not None:
            QMessageBox.information(self, "Motion in Progress", "A manual move is already running.")
            return False
        return True

    def jog_axis_async(self, axis, delta_degree):
        if not precheck(self):
            return
        answer = QMessageBox.question(
            self,
            "Confirm Limited Jog",
            f"{axis.name}: move {float(delta_degree):+g}°?\n\n"
            "The HMI remains responsive and encoder feedback will update during motion.\n"
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            start_worker("jog", axis, float(delta_degree))

    def move_axis_to_target_async(self, axis, target_degree: float):
        if not precheck(self):
            return
        try:
            current = self.motion.get_current_angle(axis)
        except Exception as exc:
            QMessageBox.critical(self, "Position Read Error", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Confirm Absolute Move",
            f"{axis.name}\n"
            f"Current: {current:+.3f}°\n"
            f"Target: {float(target_degree):+.3f}°\n\n"
            "The move runs in the background; encoder PUU and angle remain live.\n"
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            start_worker("move", axis, float(target_degree))

    def return_axis_to_zero_async(self, axis):
        if not precheck(self):
            return
        try:
            current = self.motion.get_current_angle(axis)
        except Exception as exc:
            QMessageBox.critical(self, "Position Read Error", str(exc))
            return
        answer = QMessageBox.question(
            self,
            "Confirm Return to Zero",
            f"{axis.name}: return from {current:+.3f}° to Session Zero?\n\n"
            "Encoder PUU and angle remain live during the return.\n"
            "Keep the physical E-STOP accessible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            start_worker("zero", axis)

    window.jog_axis = MethodType(jog_axis_async, window)
    window.move_axis_to_target = MethodType(move_axis_to_target_async, window)
    window.return_axis_to_zero = MethodType(return_axis_to_zero_async, window)
