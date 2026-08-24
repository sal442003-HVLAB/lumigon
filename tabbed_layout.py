from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
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
    """Split the commissioning HMI into functional tabs without changing logic."""

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
    communication_item = None
    axis_controls_item = None
    gamma_profile_item = None
    c_profile_item = None
    zero_item = None
    notice_item = None
    measurement_items = []
    unclassified_items = []

    connection_label = getattr(window, "connection_label", None)
    gamma_panel = getattr(window, "gamma_panel", None)
    c_panel = getattr(window, "c_panel", None)
    zero_button = getattr(window, "zero_button", None)
    gamma_profile_box = getattr(window, "gamma_profile_box", None)
    c_profile_box = getattr(window, "c_profile_box", None)

    for item in original_items:
        widget = item.widget()
        layout = item.layout()

        if layout is not None and _layout_contains_widget(layout, connection_label):
            header_item = item
            continue

        if widget is getattr(window, "luxmeter_box", None):
            measurement_items.append(item)
            continue

        if widget is gamma_profile_box:
            gamma_profile_item = item
            continue

        if widget is c_profile_box:
            c_profile_item = item
            continue

        if widget is not None and getattr(widget, "title", lambda: "")() == "Communication":
            communication_item = item
            continue

        if layout is not None and (
            _layout_contains_widget(layout, gamma_panel)
            or _layout_contains_widget(layout, c_panel)
        ):
            axis_controls_item = item
            continue

        if layout is not None and _layout_contains_widget(layout, zero_button):
            zero_item = item
            continue

        if widget is not None and widget.objectName() == "readOnlyNotice":
            notice_item = item
            continue

        unclassified_items.append(item)

    # ------------------------------------------------------------------
    # Full-width 100 px header. Reserved for future Lumigon artwork.
    # ------------------------------------------------------------------
    title = window.findChild(QLabel, "appTitle")

    if header_item is not None and header_item.layout() is not None:
        old_header_layout = header_item.layout()
        if connection_label is not None:
            old_header_layout.removeWidget(connection_label)
            connection_label.setParent(None)
        if title is not None:
            old_header_layout.removeWidget(title)
            title.setParent(None)

    header_widget = QWidget()
    header_widget.setObjectName("mainHeader")
    header_widget.setFixedHeight(HEADER_HEIGHT)
    header_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    header_widget.setMinimumWidth(0)
    header_widget.setMaximumWidth(16777215)

    new_header_layout = QHBoxLayout(header_widget)
    new_header_layout.setContentsMargins(18, 0, 18, 0)
    new_header_layout.setSpacing(0)

    if title is not None:
        title.setParent(header_widget)
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        new_header_layout.addWidget(title)

    new_header_layout.addStretch(1)
    root.addWidget(header_widget, 0)
    window.main_header = header_widget

    # Drive connection state lives inside Communication, not the header.
    if communication_item is not None and communication_item.widget() is not None:
        communication_box = communication_item.widget()
        communication_layout = communication_box.layout()
        if communication_layout is not None and connection_label is not None:
            status_caption = QLabel("Drive status:")
            status_caption.setObjectName("communicationStatusCaption")
            connection_label.setParent(communication_box)
            communication_layout.addWidget(status_caption)
            communication_layout.addWidget(connection_label)
            window.drive_status_caption = status_caption

    # ------------------------------------------------------------------
    # Compact Lumisphere-style tab strip, retaining Lumigon colors.
    # ------------------------------------------------------------------
    tabs = QTabWidget()
    tabs.setObjectName("mainTabs")
    tabs.setDocumentMode(True)
    tabs.setMovable(False)
    tabs.tabBar().setExpanding(False)
    tabs.tabBar().setDrawBase(False)

    # ------------------------------------------------------------------
    # Motor Control: keep Communication full width, then place the four
    # functional cards in one compact row:
    # Gamma axis | Gamma profile | C axis | C profile.
    # This intentionally leaves the lower half of the tab available for
    # later commissioning/status functions instead of stretching cards.
    # ------------------------------------------------------------------
    motor_tab = QWidget()
    motor_layout = QVBoxLayout(motor_tab)
    motor_layout.setContentsMargins(8, 8, 8, 8)
    motor_layout.setSpacing(8)

    if communication_item is not None:
        _add_item(motor_layout, communication_item, motor_tab)

    compact_row = QHBoxLayout()
    compact_row.setContentsMargins(0, 0, 0, 0)
    compact_row.setSpacing(8)

    if axis_controls_item is not None and axis_controls_item.layout() is not None:
        old_axis_layout = axis_controls_item.layout()
        if gamma_panel is not None:
            old_axis_layout.removeWidget(gamma_panel)
        if c_panel is not None:
            old_axis_layout.removeWidget(c_panel)

    if gamma_panel is not None:
        gamma_panel.setParent(motor_tab)
        gamma_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        compact_row.addWidget(gamma_panel, 3)

    if gamma_profile_box is not None:
        gamma_profile_box.setParent(motor_tab)
        gamma_profile_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        compact_row.addWidget(gamma_profile_box, 2)

    if c_panel is not None:
        c_panel.setParent(motor_tab)
        c_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        compact_row.addWidget(c_panel, 3)

    if c_profile_box is not None:
        c_profile_box.setParent(motor_tab)
        c_profile_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        compact_row.addWidget(c_profile_box, 2)

    motor_layout.addLayout(compact_row)

    for item in unclassified_items:
        _add_item(motor_layout, item, motor_tab)

    if zero_item is not None:
        _add_item(motor_layout, zero_item, motor_tab)

    if notice_item is not None:
        _add_item(motor_layout, notice_item, motor_tab)

    motor_layout.addStretch(1)

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

        QLabel#communicationStatusCaption {
            color: #AAB7C4;
            padding-left: 8px;
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
            border-radius: 1px;
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
