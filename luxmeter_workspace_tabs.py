"""Compact nested workspace for Luxmeter instruments.

The top-level Luxmeter tab should stay simple. This module groups the existing
Czibula/Grundmann controls, the P-9710 synchronized measurement panel, and a
small validation area into dedicated sub-tabs without changing acquisition
logic.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.setParent(None)
        elif child_layout is not None:
            _clear_layout(child_layout)


def _make_page(*widgets):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(10, 10, 10, 10)
    layout.setSpacing(10)

    for widget in widgets:
        if widget is None:
            continue
        widget.setParent(page)
        layout.addWidget(widget)

    layout.addStretch(1)
    return page


def attach_luxmeter_workspace_tabs(window):
    """Replace the crowded Luxmeter page with three focused sub-tabs."""

    if getattr(window, "luxmeter_subtabs", None) is not None:
        return window.luxmeter_subtabs

    host = getattr(window, "luxmeter_tab", None)
    if host is None or host.layout() is None:
        raise RuntimeError("Luxmeter top-level tab is not available.")

    cg_box = getattr(window, "luxmeter_box", None)
    cg_effective_box = getattr(window, "luxmeter_effective_box", None)
    p9710_box = getattr(window, "p9710_effective_box", None)

    if cg_box is None:
        raise RuntimeError("C&G luxmeter controls must be attached first.")
    if p9710_box is None:
        raise RuntimeError("P-9710 panel must be attached first.")

    root = host.layout()
    _clear_layout(root)

    subtabs = QTabWidget(host)
    subtabs.setObjectName("luxmeterSubTabs")
    subtabs.setDocumentMode(True)
    subtabs.setMovable(False)
    subtabs.tabBar().setExpanding(False)
    subtabs.tabBar().setDrawBase(False)

    cg_page = _make_page(cg_box, cg_effective_box)
    p9710_page = _make_page(p9710_box)

    validation_page = QWidget()
    validation_layout = QVBoxLayout(validation_page)
    validation_layout.setContentsMargins(18, 18, 18, 18)
    validation_layout.setSpacing(10)

    title = QLabel("Validation / Comparison")
    title.setObjectName("luxmeterValidationTitle")

    body = QLabel(
        "Reserved for side-by-side cross-checks between the C&G Ph-Amp MB7 and "
        "Gigahertz-Optik P-9710. Formal comparison tools can be added here later "
        "without crowding either instrument workspace."
    )
    body.setWordWrap(True)
    body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    body.setObjectName("luxmeterValidationText")

    validation_layout.addWidget(title)
    validation_layout.addWidget(body)
    validation_layout.addStretch(1)

    subtabs.addTab(cg_page, "C&G Ph-Amp MB7")
    subtabs.addTab(p9710_page, "Gigahertz-Optik P-9710")
    subtabs.addTab(validation_page, "Validation")

    root.addWidget(subtabs, 1)

    window.luxmeter_subtabs = subtabs
    window.luxmeter_cg_tab = cg_page
    window.luxmeter_p9710_tab = p9710_page
    window.luxmeter_validation_tab = validation_page

    # Make the second-level tabs visibly subordinate to the main application tabs.
    host.setStyleSheet(
        host.styleSheet()
        + """
        QTabWidget#luxmeterSubTabs::pane {
            border: 1px solid #2B4050;
            background-color: #101820;
            top: 0px;
        }

        QTabWidget#luxmeterSubTabs > QTabBar::tab {
            background-color: #16232D;
            color: #BFCED8;
            border: 1px solid #2B4050;
            padding: 7px 14px;
            margin-right: 2px;
        }

        QTabWidget#luxmeterSubTabs > QTabBar::tab:selected {
            background-color: #1B5F91;
            color: #FFFFFF;
            border-color: #2D7FB9;
        }

        QLabel#luxmeterValidationTitle {
            color: #4DA3FF;
            font-size: 15pt;
            font-weight: 700;
        }

        QLabel#luxmeterValidationText {
            color: #9DB1BE;
            background-color: #17232D;
            border: 1px solid #2B4050;
            border-radius: 6px;
            padding: 14px;
        }
        """
    )

    return subtabs
