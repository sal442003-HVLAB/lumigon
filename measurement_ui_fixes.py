from PySide6.QtWidgets import QComboBox, QGroupBox, QPushButton


GRID_MODE_INDEX = 2
SINGLE_C_GAMMA_INDEX = 0


def attach_measurement_ui_fixes(window):
    """Apply small runtime UI rules that keep scan/execution modes coherent."""

    scan_combo = getattr(window, "measurement_scan_mode_combo", None)
    plan_table = getattr(window, "measurement_plan_table", None)
    if scan_combo is None:
        return

    buttons = window.findChildren(QPushButton)
    step_button = next(
        (button for button in buttons if button.text().strip() == "Step Scan"),
        None,
    )
    continuous_button = next(
        (button for button in buttons if button.text().strip() == "Continuous Scan"),
        None,
    )

    if step_button is None or continuous_button is None:
        return

    model = scan_combo.model()
    grid_item = model.item(GRID_MODE_INDEX) if hasattr(model, "item") else None

    def set_continuous_rules(enabled):
        enabled = bool(enabled)

        # Continuous/fly scanning is currently implemented only for a single
        # moving axis. Prevent an invalid C x Gamma grid combination in the UI.
        if grid_item is not None:
            grid_item.setEnabled(not enabled)

        if enabled and scan_combo.currentIndex() == GRID_MODE_INDEX:
            scan_combo.setCurrentIndex(SINGLE_C_GAMMA_INDEX)

        scan_combo.setToolTip(
            "Continuous Scan currently supports Single C / Gamma Sweep or "
            "Single Gamma / C Sweep only."
            if enabled
            else "Step Scan supports single-axis scans and C x Gamma Grid plans."
        )

    continuous_button.clicked.connect(lambda: set_continuous_rules(True))
    step_button.clicked.connect(lambda: set_continuous_rules(False))

    # Determine the initial state from the button labels/check state where
    # available. Step Scan is the safe default if neither button exposes state.
    continuous_active = bool(
        getattr(continuous_button, "isChecked", lambda: False)()
    )
    set_continuous_rules(continuous_active)

    # Keep the execution strip visually separated from the plan table on
    # smaller displays instead of letting it crowd the last table rows.
    if plan_table is not None:
        plan_table.setMinimumHeight(180)

    for box in window.findChildren(QGroupBox):
        if box.title().strip() == "Execution":
            box.setMinimumHeight(66)
            break
