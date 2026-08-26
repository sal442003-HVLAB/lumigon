"""Safe vertical scrolling for the Lumigon Measurement tab.

The Measurement workspace is already a fully built QWidget with connected
controls, runtime extensions and references used by the detached Test Plan
workspace.  Do not move its internal layouts/widgets after construction.
Instead, replace only the QTabWidget page with a QScrollArea whose widget is the
original Measurement workspace.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QScrollArea


def attach_measurement_scroll_runtime(window):
    """Wrap the complete Measurement tab in a vertical-only QScrollArea."""

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

    # removeTab() does not delete the page. QScrollArea.setWidget() then safely
    # reparents that complete page as one object; none of its child layouts or
    # connected widgets are reconstructed or moved individually.
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
        # Removing and reinserting a tab temporarily shifts indexes. Restore the
        # user's original selected tab when Measurement was not active.
        tabs.setCurrentIndex(current_index)

    window.measurement_scroll_area = scroll
    window.measurement_scroll_content = page

    QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))
    return scroll
