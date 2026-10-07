"""Safe vertical scrolling for the Lumigon Luxmeter tab.

Each instrument page is wrapped in its own vertical QScrollArea so the instrument
selector stays visible and each instrument retains its scroll position. Mouse-wheel input
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


def attach_luxmeter_scroll_runtime(window):
    """Keep the instrument selector visible; scroll each device independently."""
    stack = getattr(window, "luxmeter_instrument_stack", None)
    if stack is None:
        raise RuntimeError("Luxmeter instrument workspace is not available for scrolling.")
    existing = getattr(window, "luxmeter_scroll_areas", None)
    if existing is not None:
        return existing

    areas = []
    filters = []
    controls = []
    current_index = stack.currentIndex()
    for page in (window.luxmeter_cg_tab, window.luxmeter_p9710_tab):
        index = stack.indexOf(page)
        stack.removeWidget(page)
        scroll = QScrollArea(stack)
        scroll.setObjectName(f"luxmeterInstrumentScroll{index}")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        scroll.setStyleSheet(
            f"QScrollArea#{scroll.objectName()} {{ border:none; background:#101820; }}"
            f"QScrollArea#{scroll.objectName()} > QWidget > QWidget {{ background:#101820; }}"
        )
        stack.insertWidget(index, scroll)
        filter_obj = _LuxmeterNoWheelFilter(scroll, page)
        page_controls = list(page.findChildren(QAbstractSpinBox))
        page_controls.extend(page.findChildren(QComboBox))
        for control in page_controls:
            control.installEventFilter(filter_obj)
        areas.append(scroll)
        filters.append(filter_obj)
        controls.extend(page_controls)
        QTimer.singleShot(0, lambda scroll=scroll: scroll.verticalScrollBar().setValue(0))
    stack.setCurrentIndex(current_index)
    window.luxmeter_scroll_areas = areas
    window.luxmeter_no_wheel_filters = filters
    window.luxmeter_no_wheel_controls = controls
    return areas
