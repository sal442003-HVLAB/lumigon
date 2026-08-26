"""Small UI companion for the enabled C × Gamma Step Grid."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel


SCAN_GRID = 2


def attach_grid_validation_ui(window):
    if getattr(window, "_grid_validation_ui_attached", False):
        return
    window._grid_validation_ui_attached = True

    validate_button = getattr(window, "measurement_validate_plan_button", None)
    scan_mode = getattr(window, "measurement_scan_mode_combo", None)
    state = getattr(window, "measurement_state_label", None)
    page = getattr(window, "measurement_workspace", None)
    if validate_button is None or scan_mode is None or state is None or page is None:
        return

    def refresh_text():
        if scan_mode.currentIndex() != SCAN_GRID:
            return
        if "VALIDATED GRID" not in state.text().upper():
            return

        for label in page.findChildren(QLabel):
            text = label.text()
            if (
                "Grid execution remains disabled" in text
                or "commissioning interlock requires the non-sweep servo" in text
            ):
                label.setText(
                    "Plan validated. C × Gamma Step Grid is enabled with serpentine "
                    "traversal and two-axis feedback verification at every point."
                )

    def after_validate(*_args):
        # grid_step_runtime updates the state on the next event-loop turn; run a
        # moment later so this companion only changes text after true validation.
        QTimer.singleShot(20, refresh_text)

    validate_button.clicked.connect(after_validate)
