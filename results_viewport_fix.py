"""Viewport isolation for the Lumigon Results tab.

Matplotlib canvases and the populated Results summary can report large size
hints.  If they participate directly in the main QTabWidget layout, Qt may grow
the minimum size of the whole maximized MainWindow beyond the physical screen.
The fixed-height header then scales with that oversized geometry, which looks
like the entire HMI has suddenly zoomed after loading a CSV.

Keep Results inside its own scroll viewport so content size can never dictate
MainWindow geometry.  Only the Results content scrolls; the Lumigon header and
main tab strip remain fixed.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractScrollArea,
    QFrame,
    QScrollArea,
    QSizePolicy,
)


def attach_results_viewport_fix(window):
    """Isolate Results content from the main-window size negotiation."""

    if getattr(window, "results_scroll_area", None) is not None:
        return window.results_scroll_area

    tab = getattr(window, "results_tab", None)
    workspace = getattr(window, "results_workspace_controller", None)
    if tab is None or workspace is None:
        raise RuntimeError("Results workspace is not available for viewport isolation.")

    layout = tab.layout()
    if layout is None:
        raise RuntimeError("Results tab layout is not available.")

    # Remove the Results workspace from direct participation in QTabWidget size
    # negotiation.  This is the key part of the fix.
    layout.removeWidget(workspace)
    workspace.setParent(None)

    tab.setMinimumSize(0, 0)
    tab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    scroll = QScrollArea(tab)
    scroll.setObjectName("resultsScrollArea")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
    scroll.setMinimumSize(0, 0)
    scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    # The workspace may be taller than the viewport (summary + analysis + plot),
    # but that height is now local to the scroll area and cannot enlarge Lumigon.
    workspace.setMinimumWidth(0)
    workspace.setMinimumHeight(0)
    workspace.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    charts = getattr(workspace, "charts", None)
    if charts is not None:
        charts.setMinimumWidth(0)
        charts.setMinimumHeight(320)
        charts.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        stack = getattr(charts, "stack", None)
        if stack is not None:
            stack.setMinimumWidth(0)
            stack.setMinimumHeight(280)
            stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        # FigureCanvasQTAgg's DPI-based sizeHint is useful in a standalone
        # window but must not create a horizontal minimum inside Lumigon.
        for name in ("polar_canvas", "cartesian_canvas"):
            canvas = getattr(charts, name, None)
            if canvas is not None:
                canvas.setMinimumSize(0, 0)
                canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

    scroll.setWidget(workspace)
    layout.addWidget(scroll, 1)

    window.results_scroll_area = scroll
    return scroll
