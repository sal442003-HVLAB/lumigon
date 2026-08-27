"""Small Motor Control UI refinements for manual operation."""

from __future__ import annotations

from machine_config import JOG_STEP_DEG


def attach_motor_control_refinement(window):
    """Apply the confirmed manual jog increment and clarify the zero control."""

    for panel in (
        getattr(window, "gamma_panel", None),
        getattr(window, "c_panel", None),
    ):
        if panel is None:
            continue

        panel.jog_minus_button.setText(f"-{JOG_STEP_DEG:g}°")
        panel.jog_plus_button.setText(f"+{JOG_STEP_DEG:g}°")
        panel.target_spin.setSingleStep(float(JOG_STEP_DEG))

    zero_button = getattr(window, "zero_button", None)
    zero_label = getattr(window, "zero_info_label", None)

    if zero_button is not None:
        zero_button.setText("Set Zero — Both Axes")
        zero_button.setObjectName("sessionZeroButton")
        zero_button.setToolTip(
            "Set the current physical position as zero for both Gamma and C axes."
        )
        zero_button.setStyleSheet(
            """
            QPushButton#sessionZeroButton {
                background-color: #A66A00;
                color: #FFF7E6;
                border: 1px solid #D79A2B;
                border-radius: 6px;
                padding: 8px 18px;
                font-weight: 700;
            }
            QPushButton#sessionZeroButton:hover {
                background-color: #C17A00;
            }
            QPushButton#sessionZeroButton:pressed {
                background-color: #835300;
            }
            """
        )

    if zero_label is not None:
        zero_label.setObjectName("sessionZeroStatus")
        zero_label.setToolTip("Current zero-reference status for both axes.")
        zero_label.setStyleSheet(
            """
            QLabel#sessionZeroStatus {
                color: #F0C36A;
                background: transparent;
                border: none;
                padding: 7px 4px;
                font-weight: 600;
            }
            """
        )

    return zero_button
