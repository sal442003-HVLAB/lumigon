import sys

from PySide6.QtWidgets import QApplication

from main_window import MainWindow
from c_profile_controls import attach_c_profile_controls

from machine_config import (
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
    attach_c_profile_controls(window)

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
