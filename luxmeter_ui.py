"""Shared layout primitives for the two instrument workspaces."""

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget, QStackedWidget,
)


def form_section(title, rows):
    box = QGroupBox(title)
    layout = QFormLayout(box)
    layout.setContentsMargins(14, 16, 14, 14)
    layout.setSpacing(12)
    layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    for caption, control in rows:
        layout.addRow(caption, control)
    return box


def result_section(title, *widgets):
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(16, 18, 16, 16)
    layout.setSpacing(14)
    for widget in widgets:
        if isinstance(widget, QLabel):
            widget.setWordWrap(True)
        layout.addWidget(widget)
    layout.addStretch(1)
    return box


def two_columns(left, right, parent=None):
    host = QWidget(parent)
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    for box in (left, right):
        box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(box, 1)
    return host


class CurrentPageStack(QStackedWidget):
    """Let the visible mode determine the scroll height, not the longest mode."""

    def sizeHint(self):
        page = self.currentWidget()
        return page.sizeHint() if page is not None else super().sizeHint()

    def minimumSizeHint(self):
        page = self.currentWidget()
        if page is None:
            return super().minimumSizeHint()
        return QSize(0, page.sizeHint().height())


def refresh_instrument_selection(window):
    refresh = getattr(window, "refresh_luxmeter_instrument_selection", None)
    if callable(refresh):
        refresh()


class CollapsibleSection(QWidget):
    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.ArrowType.RightArrow)
        self.button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.button.setStyleSheet(
            "QToolButton { background:#16232D; color:#BFCED8; border:1px solid #2B4050;"
            " border-radius:6px; padding:10px; text-align:left; font-weight:600; }"
            "QToolButton:hover { background:#1C303F; }"
        )
        self.content = content
        content.setParent(self)
        layout.addWidget(self.button)
        layout.addWidget(content)
        content.hide()
        self.button.toggled.connect(self.set_expanded)

    def set_expanded(self, expanded):
        self.button.setChecked(expanded)
        self.button.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self.content.setVisible(expanded)
