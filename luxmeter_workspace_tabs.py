"""One Luxmeter workspace with a persistent instrument selector."""

from PySide6.QtCore import QEvent, QObject, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLayout,
                             QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from luxmeter_controls import LUXMETER_CG, LUXMETER_GIGAHERTZ


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.setParent(None)
        elif child_layout is not None:
            _clear_layout(child_layout)


def _make_page(widget):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setSizeConstraint(QLayout.SetMinimumSize)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(10)
    widget.setParent(page)
    layout.addWidget(widget)
    layout.addStretch(1)
    return page


class _SelectorNoWheel(QObject):
    def eventFilter(self, obj, event):
        return event.type() == QEvent.Type.Wheel


def attach_luxmeter_workspace_tabs(window):
    """Keep the existing entry point, replacing device tabs with one selector."""
    existing = getattr(window, "luxmeter_instrument_stack", None)
    if existing is not None:
        return existing
    host = getattr(window, "luxmeter_tab", None)
    if host is None or host.layout() is None:
        raise RuntimeError("Luxmeter top-level tab is not available.")
    cg_box = getattr(window, "luxmeter_box", None)
    p9710_box = getattr(window, "p9710_effective_box", None)
    if cg_box is None or p9710_box is None:
        raise RuntimeError("Both instrument workspaces must be attached first.")

    selector = getattr(window, "luxmeter_instrument_combo", None)
    if selector is None:
        selector = QComboBox()
        selector.addItems([LUXMETER_CG, LUXMETER_GIGAHERTZ])
    for index, caption, instrument in (
        (0, "C&G Ph-Amp MB7", LUXMETER_CG),
        (1, "Gigahertz-Optik P-9710", LUXMETER_GIGAHERTZ),
    ):
        selector.setItemText(index, caption)
        selector.setItemData(index, instrument)
    connection = getattr(window, "luxmeter_connection_box", None)
    if connection is not None:
        grid = connection.layout()
        grid.removeWidget(selector)
        item = grid.itemAtPosition(0, 0)
        if item is not None and item.widget() is not None:
            label = item.widget()
            grid.removeWidget(label)
            label.hide()
            label.deleteLater()

    root = host.layout()
    _clear_layout(root)
    root.setContentsMargins(0, 8, 0, 8)
    root.setSpacing(0)
    chooser = QWidget(host)
    chooser.setObjectName("luxmeterInstrumentChooser")
    chooser_layout = QHBoxLayout(chooser)
    chooser_layout.setContentsMargins(24, 6, 24, 6)
    chooser_layout.setSpacing(12)
    chooser_layout.addWidget(QLabel("Instrument:"))
    selector.setParent(chooser)
    selector.setMinimumWidth(0)
    selector.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    selector.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    chooser_layout.addWidget(selector)
    chooser_layout.addStretch(1)
    root.addWidget(chooser)

    stack = QStackedWidget(host)
    cg_page = _make_page(cg_box)
    p9710_page = _make_page(p9710_box)
    stack.addWidget(cg_page)
    stack.addWidget(p9710_page)
    root.addWidget(stack, 1)
    window.luxmeter_instrument_stack = stack
    window.luxmeter_instrument_combo = selector
    window.luxmeter_instrument_chooser = chooser
    window.luxmeter_cg_tab = cg_page
    window.luxmeter_p9710_tab = p9710_page
    current = {"index": 0}

    def busy():
        for name in ("luxmeter_live_worker", "p9710_flash_timing_worker",
                     "measurement_v2_worker", "measurement_worker", "p9710_miol_grid_worker"):
            if getattr(window, name, None) is not None:
                return True
        holder = getattr(window, "p9710_mode_worker_holder", None)
        if holder is not None and holder.get("worker") is not None:
            return True
        return any(timer.isActive() for timer in getattr(window, "p9710_continuous_timers", ()))

    def refresh_selection():
        active = busy()
        selector.setEnabled(not active)
        selector.setToolTip(
            "Stop Live or wait for the acquisition to finish before changing instrument."
            if active else "Select the instrument; each device retains its own connection, settings and results."
        )
        return active

    def select_instrument(index):
        if refresh_selection():
            with QSignalBlocker(selector):
                selector.setCurrentIndex(current["index"])
            return
        current["index"] = index
        stack.setCurrentIndex(index)
        window.luxmeter_selected_instrument = selector.currentData()
        stack.updateGeometry()

    selector.currentIndexChanged.connect(select_instrument)
    window.refresh_luxmeter_instrument_selection = refresh_selection
    wheel_filter = _SelectorNoWheel(selector)
    selector.installEventFilter(wheel_filter)
    window.luxmeter_instrument_wheel_filter = wheel_filter
    select_instrument(selector.currentIndex())
    return stack
