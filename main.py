import sys
import warnings
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
from execution_mode_controls import attach_execution_mode_controls
from measurement_ui_fixes import attach_measurement_ui_fixes
from test_plan_workspace import attach_test_plan_workspace
from test_plan_runtime_improvements import install_test_plan_runtime_improvements
from measurement_results_runtime import install_measurement_results_runtime
from results_workspace import attach_results_workspace
from results_viewport_fix import attach_results_viewport_fix
from luxmeter_resilience import install_phamp_connect_retry

from machine_config import (
    GAMMA_LIMIT_DEG,
    C_LIMIT_DEG,
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


def _apply_confirmed_axis_limits(window):
    """Apply the confirmed independent motion ranges to visible HMI controls."""

    gamma_panel = getattr(window, "gamma_panel", None)
    if gamma_panel is not None:
        gamma_panel.target_spin.setRange(-GAMMA_LIMIT_DEG, GAMMA_LIMIT_DEG)

    c_panel = getattr(window, "c_panel", None)
    if c_panel is not None:
        c_panel.target_spin.setRange(-C_LIMIT_DEG, C_LIMIT_DEG)

    for name in ("measurement_gamma_start", "measurement_gamma_end"):
        control = getattr(window, name, None)
        if control is not None:
            control.setRange(-GAMMA_LIMIT_DEG, GAMMA_LIMIT_DEG)

    for name in ("measurement_c_start", "measurement_c_end"):
        control = getattr(window, name, None)
        if control is not None:
            control.setRange(-C_LIMIT_DEG, C_LIMIT_DEG)

    gamma_step = getattr(window, "measurement_gamma_step", None)
    if gamma_step is not None:
        gamma_step.setMaximum(2.0 * GAMMA_LIMIT_DEG)

    c_step = getattr(window, "measurement_c_step", None)
    if c_step is not None:
        c_step.setMaximum(2.0 * C_LIMIT_DEG)

    envelope = window.findChild(QLabel, "measurementEnvelope")
    if envelope is not None:
        envelope.setText(
            f"Current enforced software envelope: Gamma ±{GAMMA_LIMIT_DEG:g}°  •  "
            f"C ±{C_LIMIT_DEG:g}°"
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

    install_phamp_connect_retry()
    install_test_plan_runtime_improvements()
    install_measurement_results_runtime()

    window = MainWindow()
    attach_axis_profile_controls(window)
    attach_luxmeter_controls(window)

    notice = window.findChild(QLabel, "readOnlyNotice")
    if notice is not None:
        notice.setText(
            "HMI v0.3 — Confirmed motion envelope — "
            f"Gamma ±{GAMMA_LIMIT_DEG:g}°, C ±{C_LIMIT_DEG:g}°. "
            "Continuous bounded moves enabled."
        )

    organize_main_window_tabs(window)
    attach_results_workspace(window)
    attach_results_viewport_fix(window)
    _apply_confirmed_axis_limits(window)
    attach_execution_mode_controls(window)
    attach_measurement_ui_fixes(window)

    # Pause/Abort are intentionally unconnected until a run starts in the old
    # Measurement implementation. The detached Test Plan workspace takes over
    # those buttons at startup, and PySide emits a RuntimeWarning when its
    # defensive disconnect() finds no previous slot. This warning is harmless;
    # suppress only that specific libpyside message while the workspace is
    # attached so real RuntimeWarnings remain visible.
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r'libpyside: Failed to disconnect \(None\) from signal "clicked\(\)"\.',
            category=RuntimeWarning,
        )
        attach_test_plan_workspace(window)

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
