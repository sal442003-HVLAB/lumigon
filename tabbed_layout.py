from PySide6.QtWidgets import (
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt


HEADER_HEIGHT = 100


def _layout_contains_widget(layout, target):
    if layout is None or target is None:
        return False

    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        child_layout = item.layout()
        if widget is target:
            return True
        if child_layout is not None and _layout_contains_widget(child_layout, target):
            return True
    return False


def _reparent_layout_widgets(layout, parent_widget):
    if layout is None:
        return

    layout.setParent(None)
    for index in range(layout.count()):
        item = layout.itemAt(index)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.setParent(parent_widget)
        elif child_layout is not None:
            _reparent_layout_widgets(child_layout, parent_widget)


def _add_item(layout, item, parent_widget):
    widget = item.widget()
    child_layout = item.layout()

    if widget is not None:
        widget.setParent(parent_widget)
        layout.addWidget(widget)
        return

    if child_layout is not None:
        _reparent_layout_widgets(child_layout, parent_widget)
        layout.addLayout(child_layout)


def _placeholder_tab(title, description):
    tab = QWidget()
    layout = QVBoxLayout(tab)

    heading = QLabel(title)
    heading.setObjectName("tabSectionTitle")
    heading.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    body = QLabel(description)
    body.setWordWrap(True)
    body.setObjectName("tabPlaceholder")
    body.setAlignment(Qt.AlignTop | Qt.AlignLeft)

    layout.addWidget(heading)
    layout.addWidget(body)
    layout.addStretch()
    return tab


def organize_main_window_tabs(window):
    """Split the commissioning HMI into functional tabs without changing logic.

    Existing controls are re-used and re-parented. No servo or luxmeter command
    behavior is changed by this function.
    """

    central = window.centralWidget()
    if central is None or central.layout() is None:
        raise RuntimeError("Main window layout is not available.")

    root = central.layout()
    root.setContentsMargins(10, 8, 10, 8)
    root.setSpacing(4)

    original_items = []
    while root.count():
        original_items.append(root.takeAt(0))

    header_item = None
    motor_items = []
    measurement_items = []
    unclassified_items = []

    for item in original_items:
        widget = item.widget()
        layout = item.layout()

        if layout is not None and _layout_contains_widget(
            layout,
            getattr(window, "connection_label", None),
        ):
            header_item = item
            continue

        if widget is getattr(window, "luxmeter_box", None):
            measurement_items.append(item)
            continue

        if widget in {
            getattr(window, "gamma_profile_box", None),
            getattr(window, "c_profile_box", None),
        }:
            motor_items.append(item)
            continue

        if widget is not None and getattr(widget, "title", lambda: "")() == "Communication":
            motor_items.append(item)
            continue

        if layout is not None and (
            _layout_contains_widget(layout, getattr(window, "gamma_panel", None))
            or _layout_contains_widget(layout, getattr(window, "c_panel", None))
            or _layout_contains_widget(layout, getattr(window, "zero_button", None))
        ):
            motor_items.append(item)
            continue

        if widget is not None and widget.objectName() == "readOnlyNotice":
            motor_items.append(item)
            continue

        unclassified_items.append(item)

    # Lumisphere-like header proportions: full-width, about 100 px high.
    if header_item is not None:
        header_widget = QWidget()
        header_widget.setObjectName("mainHeader")
        header_widget.setFixedHeight(HEADER_HEIGHT)

        header_layout = QVBoxLayout(header_widget)
        header_layout.setContentsMargins(14, 0, 14, 0)
        header_layout.setSpacing(0)
        _add_item(header_layout, header_item, header_widget)

        title = window.findChild(QLabel, "appTitle")
        if title is not None:
            title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

        root.addWidget(header_widget)
        window.main_header = header_widget

    tabs = QTabWidget()
    tabs.setObjectName("mainTabs")
    tabs.setDocumentMode(True)
    tabs.setMovable(False)
    tabs.tabBar().setExpanding(False)
    tabs.tabBar().setDrawBase(False)

    motor_tab = QWidget()
    motor_layout = QVBoxLayout(motor_tab)
    motor_layout.setContentsMargins(8, 8, 8, 8)
    motor_layout.setSpacing(8)

    for item in motor_items:
        _add_item(motor_layout, item, motor_tab)
    for item in unclassified_items:
        _add_item(motor_layout, item, motor_tab)
    motor_layout.addStretch()

    measurement_tab = QWidget()
    measurement_layout = QVBoxLayout(measurement_tab)
    measurement_layout.setContentsMargins(8, 8, 8, 8)
    measurement_layout.setSpacing(10)

    for item in measurement_items:
        _add_item(measurement_layout, item, measurement_tab)

    measurement_info = QLabel(
        "Measurement workspace — manual/live illuminance, measurement sequence, "
        "angle stepping and synchronized acquisition will be developed here."
    )
    measurement_info.setWordWrap(True)
    measurement_info.setObjectName("tabPlaceholder")
    measurement_layout.addWidget(measurement_info)
    measurement_layout.addStretch()

    results_tab = _placeholder_tab(
        "Results",
        "Reserved for intensity tables, polar/candela diagrams, test progress, "
        "saved measurement sets and export/report functions.",
    )

    safety_tab = _placeholder_tab(
        "Safety & I/O",
        "Reserved for HOME and LIMIT sensors, E-STOP/safety-chain status, "
        "Pilz safety relay state, drive digital I/O and commissioning diagnostics.",
    )

    settings_tab = _placeholder_tab(
        "Settings & Diagnostics",
        "Reserved for communication ports, axis limits, calibration/scaling, "
        "luxmeter sensitivity, default acquisition parameters and system diagnostics.",
    )

    tabs.addTab(motor_tab, "Motor Control")
    tabs.addTab(measurement_tab, "Measurement")
    tabs.addTab(results_tab, "Results")
    tabs.addTab(safety_tab, "Safety & I/O")
    tabs.addTab(settings_tab, "Settings")

    root.addWidget(tabs, 1)

    window.main_tabs = tabs
    window.motor_tab = motor_tab
    window.measurement_tab = measurement_tab
    window.results_tab = results_tab
    window.safety_tab = safety_tab
    window.settings_tab = settings_tab

    # Keep Lumigon's navy/blue palette, but use Lumisphere-like proportions:
    # compact adjacent tabs directly under a 100 px header.
    window.setStyleSheet(
        window.styleSheet()
        + """
        QWidget#mainHeader {
            background-color: #0B1420;
            border: 1px solid #1E2E3D;
            border-radius: 0px;
        }

        QLabel#appTitle {
            font-size: 26pt;
            font-weight: 700;
            color: #4DA3FF;
            padding-left: 4px;
        }

        QTabWidget#mainTabs::pane {
            border: 1px solid #34495E;
            border-radius: 0px;
            top: 0px;
            background-color: #101820;
        }

        QTabWidget#mainTabs > QTabBar {
            left: 0px;
        }

        QTabBar::tab {
            background-color: #14212B;
            color: #D7E1E8;
            border: 1px solid #34495E;
            border-bottom: 1px solid #34495E;
            border-radius: 2px;
            padding: 7px 15px;
            margin: 0px 1px 0px 0px;
            min-width: 0px;
            min-height: 20px;
            font-weight: 500;
        }

        QTabBar::tab:selected {
            background-color: #1769AA;
            color: #FFFFFF;
            border-color: #2C7DBB;
            font-weight: 600;
        }

        QTabBar::tab:hover:!selected {
            background-color: #1C303F;
            color: #FFFFFF;
        }

        QLabel#tabSectionTitle {
            font-size: 16pt;
            font-weight: 700;
            color: #4DA3FF;
            padding: 8px 4px;
        }

        QLabel#tabPlaceholder {
            color: #AAB7C4;
            background-color: #17232D;
            border: 1px solid #34495E;
            border-radius: 6px;
            padding: 12px;
        }
        """
    )
