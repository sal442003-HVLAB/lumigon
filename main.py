import sys

from PySide6.QtWidgets import QApplication, QLabel

from main_window import MainWindow
from axis_profile_controls import attach_axis_profile_controls
from luxmeter_controls import attach_luxmeter_controls
from tabbed_layout import organize_main_window_tabs

from machine_config import (
    ABSOLUTE_LIMIT_DEG,
    APP_NAME,
    APP_VERSION,
)


def main():
    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        APP_NAME
    )

    app.setApplicationVersion(
        APP_VERSION
    )

    window = MainWindow()
    attach_axis_profile_controls(window)
    attach_luxmeter_controls(window)

    notice = window.findChild(QLabel, "readOnlyNotice")
    if notice is not None:
        notice.setText(
            "HMI v0.3 — Commissioning Mode — "
            f"Absolute target limited to ±{ABSOLUTE_LIMIT_DEG:g}°. "
            "Continuous bounded moves; one-degree segmentation disabled."
        )

    organize_main_window_tabs(window)

    window.showMaximized()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
