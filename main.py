import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QVBoxLayout,
)

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
POPUP_MAX_WIDTH = 900
POPUP_MAX_HEIGHT = 520


def _find_popup_image():
    """Return the startup popup image path if present.

    The project may use either `asset` or `assets`. The preferred base filename
    is `popup`; common image extensions are accepted too.
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


def _show_startup_popup(popup_path):
    """Show the startup popup using the same sizing as Lumisphere.

    Lumisphere scales its popup into a 900 x 520 bounding box while preserving
    the image aspect ratio, then sizes the splash dialog to the rendered image.
    """

    if popup_path is None:
        return

    pixmap = QPixmap(str(popup_path))
    if pixmap.isNull():
        return

    dialog = QDialog()
    dialog.setWindowFlags(Qt.SplashScreen | Qt.WindowStaysOnTopHint)
    dialog.setModal(True)
    dialog.setStyleSheet(
        """
        QDialog {
            background-color: #101820;
            border: none;
        }

        QLabel {
            background-color: #101820;
        }
        """
    )

    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    image_label = QLabel()
    image_label.setAlignment(Qt.AlignCenter)

    scaled_pixmap = pixmap.scaled(
        POPUP_MAX_WIDTH,
        POPUP_MAX_HEIGHT,
        Qt.KeepAspectRatio,
        Qt.SmoothTransformation,
    )

    image_label.setPixmap(scaled_pixmap)
    layout.addWidget(image_label)

    dialog.adjustSize()

    QTimer.singleShot(
        POPUP_DURATION_MS,
        dialog.accept,
    )

    dialog.exec()


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

    _show_startup_popup(
        _find_popup_image()
    )

    window.showMaximized()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()
