import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QSplashScreen

from main_window import MainWindow
from axis_profile_controls import attach_axis_profile_controls
from luxmeter_controls import attach_luxmeter_controls
from tabbed_layout import organize_main_window_tabs

from machine_config import (
    ABSOLUTE_LIMIT_DEG,
    APP_NAME,
    APP_VERSION,
)


POPUP_DURATION_MS = 5000


def _find_popup_image():
    """Return the startup popup image path if present.

    The user's project may use either `asset` or `assets`. The preferred base
    filename is simply `popup`; common image extensions are accepted too.
    """

    project_dir = Path(__file__).resolve().parent
    candidates = []

    for folder_name in ("asset", "assets"):
        folder = project_dir / folder_name
        candidates.extend(
            [
                folder / "popup",
                folder / "popup.png",
                folder / "popup.jpg",
                folder / "popup.jpeg",
                folder / "popup.webp",
                folder / "popup.bmp",
            ]
        )

    for path in candidates:
        if path.is_file():
            return path

    return None


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

    screen = app.primaryScreen()
    if screen is not None:
        window.setGeometry(screen.availableGeometry())

    popup_path = _find_popup_image()
    splash = None

    def show_main_window():
        window.showMaximized()
        if splash is not None:
            splash.finish(window)

    if popup_path is not None:
        popup_pixmap = QPixmap(str(popup_path))

        if not popup_pixmap.isNull():
            if screen is not None:
                available = screen.availableGeometry()
                max_width = int(available.width() * 0.90)
                max_height = int(available.height() * 0.90)

                if (
                    popup_pixmap.width() > max_width
                    or popup_pixmap.height() > max_height
                ):
                    popup_pixmap = popup_pixmap.scaled(
                        max_width,
                        max_height,
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )

            splash = QSplashScreen(popup_pixmap)
            splash.show()
            app.processEvents()
            QTimer.singleShot(POPUP_DURATION_MS, show_main_window)
        else:
            show_main_window()
    else:
        show_main_window()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
