"""Continuous-reading controls for the P-9710 mode workspace.

The underlying mode workspace deliberately owns all actual instrument reads.
This runtime layer simply re-triggers each verified single-shot CW/peak read at
an operator-selected interval, and never starts another read while the previous
worker is still active.  It therefore preserves the same integration/range/
synchronisation path used by the single-shot buttons.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


CW_MODE_NAMES = (
    "CW",
    "CW Maximum",
    "CW Minimum",
    "Peak Maximum",
    "Peak Minimum",
    "Peak-to-Peak",
)


def _find_mode_combo(box):
    for combo in box.findChildren(QComboBox):
        items = [combo.itemText(i) for i in range(combo.count())]
        if items[: len(CW_MODE_NAMES)] == list(CW_MODE_NAMES):
            return combo
    return None


def _find_mode_stack(box):
    for stack in box.findChildren(QStackedWidget):
        if stack.count() >= len(CW_MODE_NAMES) + 1:
            return stack
    return None


def _find_read_button(page, mode_name: str):
    wanted = f"Read {mode_name}"
    for button in page.findChildren(QPushButton):
        if button.text() == wanted:
            return button
    return None


def _page_layout(page):
    layout = page.layout()
    if layout is None:
        return None
    return layout


def attach_p9710_continuous_runtime(window):
    """Add Start/Stop continuous reading to the six CW/peak pages."""

    if getattr(window, "p9710_continuous_timers", None) is not None:
        return window.p9710_continuous_timers

    box = getattr(window, "p9710_effective_box", None)
    if box is None:
        return None

    mode_combo = _find_mode_combo(box)
    stack = _find_mode_stack(box)
    if mode_combo is None or stack is None:
        return None

    timers = []
    controls = []

    def stop_all():
        for timer, start_button, stop_button, status in controls:
            timer.stop()
            start_button.setEnabled(True)
            stop_button.setEnabled(False)
            status.setText("Continuous: stopped")
            status.setStyleSheet("color:#8FA9B9;")

    for index, mode_name in enumerate(CW_MODE_NAMES):
        page = stack.widget(index)
        read_button = _find_read_button(page, mode_name)
        layout = _page_layout(page)
        if read_button is None or layout is None:
            continue

        continuous_row = QWidget(page)
        row = QHBoxLayout(continuous_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        start_button = QPushButton("Start continuous")
        stop_button = QPushButton("Stop")
        stop_button.setEnabled(False)

        interval_spin = QDoubleSpinBox()
        interval_spin.setRange(0.20, 10.0)
        interval_spin.setDecimals(2)
        interval_spin.setSingleStep(0.10)
        interval_spin.setSuffix(" s")
        interval_spin.setValue(0.50)
        interval_spin.setToolTip(
            "Requested refresh interval. If one instrument read takes longer, "
            "Lumigon waits until it is finished and skips overlapping triggers."
        )

        status = QLabel("Continuous: stopped")
        status.setStyleSheet("color:#8FA9B9;")

        row.addWidget(start_button)
        row.addWidget(stop_button)
        row.addWidget(QLabel("Refresh:"))
        row.addWidget(interval_spin)
        row.addWidget(status)
        row.addStretch(1)

        # Put the live controls directly below the single-shot controls/results.
        # Grid pages accept a row-spanning QWidget; VBox pages simply append it.
        try:
            next_row = max(0, layout.rowCount() - 1)
            layout.addWidget(continuous_row, next_row, 0, 1, 5)
        except AttributeError:
            layout.addWidget(continuous_row)

        timer = QTimer(page)
        timer.setTimerType(QTimer.CoarseTimer)

        def make_tick(button):
            def tick():
                # The mode workspace disables the read button while its QThread
                # is active.  Respect that state so serial transactions can never
                # overlap.
                if button.isEnabled():
                    button.click()
            return tick

        timer.timeout.connect(make_tick(read_button))

        def make_start(timer, start_button, stop_button, status, interval_spin, read_button):
            def start():
                ms = max(200, int(round(interval_spin.value() * 1000.0)))
                timer.setInterval(ms)
                timer.start()
                start_button.setEnabled(False)
                stop_button.setEnabled(True)
                status.setText(f"Continuous: running ({ms / 1000.0:.2f} s)")
                status.setStyleSheet("color:#55EFC4; font-weight:700;")
                # Give the operator an immediate first reading.
                if read_button.isEnabled():
                    read_button.click()
            return start

        def make_stop(timer, start_button, stop_button, status):
            def stop():
                timer.stop()
                start_button.setEnabled(True)
                stop_button.setEnabled(False)
                status.setText("Continuous: stopped")
                status.setStyleSheet("color:#8FA9B9;")
            return stop

        start_button.clicked.connect(
            make_start(timer, start_button, stop_button, status, interval_spin, read_button)
        )
        stop_button.clicked.connect(make_stop(timer, start_button, stop_button, status))

        timers.append(timer)
        controls.append((timer, start_button, stop_button, status))

    # Never keep polling a page after the operator changes measurement mode.
    mode_combo.currentIndexChanged.connect(lambda _index: stop_all())

    # Stop polling before/when the shared P-9710 connection is disconnected.
    for button in box.findChildren(QPushButton):
        if button.text() == "Disconnect":
            button.clicked.connect(stop_all)
            break

    window.p9710_continuous_timers = timers
    window.p9710_stop_continuous = stop_all
    return timers
