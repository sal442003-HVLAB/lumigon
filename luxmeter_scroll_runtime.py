"""Safe vertical scrolling for the Lumigon Luxmeter tab.

The complete Luxmeter page is wrapped in a vertical QScrollArea so instrument
workspaces can extend downward without compressing controls. Mouse-wheel input
over spin boxes and combo boxes is redirected to page scrolling to avoid
accidental parameter changes while navigating the page.
"""

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QScrollArea,
)


class _LuxmeterNoWheelFilter(QObject):
    def __init__(self, scroll_area, parent=None):
        super().__init__(parent)
        self.scroll_area = scroll_area

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.Wheel:
            return False
        if not isinstance(obj, (QAbstractSpinBox, QComboBox)):
            return False

        bar = self.scroll_area.verticalScrollBar()
        pixel_delta = event.pixelDelta().y()
        angle_delta = event.angleDelta().y()

        if pixel_delta:
            delta = pixel_delta
        elif angle_delta:
            notches = angle_delta / 120.0
            delta = int(round(notches * max(30, bar.singleStep() * 3)))
        else:
            delta = 0

        if delta:
            bar.setValue(bar.value() - delta)

        event.accept()
        return True


def _install_no_wheel_filter(page, scroll, window):
    filter_obj = _LuxmeterNoWheelFilter(scroll, page)
    controls = list(page.findChildren(QAbstractSpinBox))
    controls.extend(page.findChildren(QComboBox))
    for control in controls:
        control.installEventFilter(filter_obj)

    window.luxmeter_no_wheel_filter = filter_obj
    window.luxmeter_no_wheel_controls = controls


def attach_luxmeter_scroll_runtime(window):
    """Wrap the complete Luxmeter top-level tab in a vertical scroll area."""

    page = getattr(window, "luxmeter_tab", None)
    tabs = getattr(window, "main_tabs", None)
    if page is None:
        raise RuntimeError("Luxmeter page is not available for scrolling.")
    if tabs is None:
        raise RuntimeError("Main tab widget is not available for Luxmeter scrolling.")

    existing = getattr(window, "luxmeter_scroll_area", None)
    if existing is not None:
        return existing

    index = tabs.indexOf(page)
    if index < 0:
        raise RuntimeError("Luxmeter page is not registered in the main tab widget.")

    label = tabs.tabText(index)
    current_index = tabs.currentIndex()
    tabs.removeTab(index)

    scroll = QScrollArea(tabs)
    scroll.setObjectName("luxmeterScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(page)
    scroll.setStyleSheet(
        "QScrollArea#luxmeterScrollArea {"
        " border: none; background: #101820; }"
        "QScrollArea#luxmeterScrollArea > QWidget > QWidget {"
        " background: #101820; }"
    )

    tabs.insertTab(index, scroll, label)
    if current_index == index:
        tabs.setCurrentIndex(index)
    elif current_index > index:
        tabs.setCurrentIndex(current_index)

    window.luxmeter_scroll_area = scroll
    window.luxmeter_scroll_content = page

    _install_no_wheel_filter(page, scroll, window)
    QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))
    return scroll
