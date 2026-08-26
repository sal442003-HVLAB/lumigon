"""Scrollable wrapper for the Lumigon Measurement workspace.

The Measurement page has grown beyond a fixed-height desktop viewport as
profile-specific sections such as ICAO MIOL were added.  This runtime wrapper
keeps the existing widgets and execution engine intact, but moves the current
page contents into one vertically scrollable container.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget


def attach_measurement_scroll_runtime(window):
    """Wrap the existing Measurement page in a vertical-only QScrollArea."""

    page = getattr(window, "measurement_workspace", None)
    if page is None:
        raise RuntimeError("Measurement workspace is not available for scrolling.")

    if getattr(window, "measurement_scroll_area", None) is not None:
        return window.measurement_scroll_area

    page_layout = page.layout()
    if page_layout is None:
        raise RuntimeError("Measurement workspace has no layout to wrap.")

    content = QWidget(page)
    content.setObjectName("measurementScrollContent")
    content_layout = QVBoxLayout(content)
    content_layout.setContentsMargins(10, 10, 10, 10)
    content_layout.setSpacing(max(0, page_layout.spacing()))

    # Preserve the exact existing widgets/layouts rather than rebuilding the
    # Measurement UI.  This keeps all signal connections and the detached Test
    # Plan workspace references valid.
    while page_layout.count():
        stretch = page_layout.stretch(0)
        item = page_layout.takeAt(0)

        widget = item.widget()
        if widget is not None:
            widget.setParent(content)
            content_layout.addWidget(widget, stretch, item.alignment())
            continue

        child_layout = item.layout()
        if child_layout is not None:
            content_layout.addLayout(child_layout, stretch)
            continue

        spacer = item.spacerItem()
        if spacer is not None:
            content_layout.addItem(spacer)

    scroll = QScrollArea(page)
    scroll.setObjectName("measurementScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setWidget(content)

    # Keep the existing dark page continuous through the viewport; the normal
    # application stylesheet still owns the actual widget styling.
    scroll.setStyleSheet(
        "QScrollArea#measurementScrollArea { border: none; background: transparent; }"
        "QScrollArea#measurementScrollArea > QWidget > QWidget { background: transparent; }"
    )

    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(0)
    page_layout.addWidget(scroll)

    window.measurement_scroll_area = scroll
    window.measurement_scroll_content = content

    # Opening Measurement should start at its header, not retain a stale scroll
    # position from widget construction/reparenting.
    QTimer.singleShot(0, lambda: scroll.verticalScrollBar().setValue(0))

    return scroll
