"""Safe vertical scrolling for the Lumigon Measurement tab.

The Measurement workspace is wrapped in a vertical QScrollArea. Mouse-wheel
input over editable numeric/selection controls is redirected to page scrolling
so operators cannot accidentally change test parameters while navigating the
Measurement page.
"""

from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QScrollArea,
)


class _MeasurementNoWheelFilter(QObject):
    """Redirect wheel input from editors to the Measurement scroll bar."""

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
    filter_obj = _MeasurementNoWheelFilter(scroll, page)
    controls = list(page.findChildren(QAbstractSpinBox))
    controls.extend(page.findChildren(QComboBox))
    for control in controls:
        control.installEventFilter(filter_obj)

    window.measurement_no_wheel_filter = filter_obj
    window.measurement_no_wheel_controls = controls


def attach_measurement_scroll_runtime(window):
    """Wrap Measurement in a vertical scroll area and make scrolling parameter-safe."""

    page = getattr(window, "measurement_workspace", None)
    tabs = getattr(window, "main_tabs", None)
    if page is None:
        raise RuntimeError("Measurement workspace is not available for scrolling.")
    if tabs is None:
        raise RuntimeError("Main tab widget is not available for Measurement scrolling.")

    existing = getattr(window, "measurement_scroll_area", None)
    if existing is not None:
        return existing

    index = tabs.indexOf(page)
    if index < 0:
        raise RuntimeError("Measurement workspace is not registered in the main tab widget.")

    label = tabs.tabText(index)
    current_index = tabs.currentIndex()
    tabs.removeTab(index)

    scroll = QScrollArea(tabs)
    scroll.setObjectName("measurementScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(page)
    scroll.setStyleSheet(
        "QScrollArea#measurementScrollArea {"
        " border: none; background: #101820; }"
        "QScrollArea#measurementScrollArea > QWidget > QWidget {"
        " background: #101820; }"
    )

    tabs.insertTab(index, scroll, label)
    if current_index == index:
        tabs.setCurrentIndex(index)
    elif current_index > index:
        tabs.setCurrentIndex(current_index)

    window.measurement_scroll_area = scroll
    window.measurement_scroll_content = page

    _install_no_wheel_filter(page, scroll, window)
    QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))
    return scroll
