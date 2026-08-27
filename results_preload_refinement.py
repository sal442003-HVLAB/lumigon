"""Refine the Results tab before a measurement run or CSV is loaded.

This module changes presentation only. The existing ResultsWorkspace remains the
single owner of run loading, analysis and chart logic.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout


PRELOAD_PANEL_HEIGHT = 300


def attach_results_preload_refinement(window):
    workspace = getattr(window, "results_workspace_controller", None)
    if workspace is None:
        raise RuntimeError("Results workspace is not available.")
    if getattr(workspace, "preload_panel", None) is not None:
        return workspace.preload_panel

    root = workspace.layout()
    if root is None:
        raise RuntimeError("Results workspace layout is not available.")

    # The original empty-state label is superseded by this compact landing card.
    empty_label = getattr(workspace, "empty_label", None)
    if empty_label is not None:
        empty_label.hide()

    panel = QFrame(workspace)
    panel.setObjectName("resultsPreloadPanel")
    # Keep the empty-state visually compact. It must not consume the full Results
    # viewport simply because all run-dependent widgets are hidden.
    panel.setFixedHeight(PRELOAD_PANEL_HEIGHT)
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    panel_layout = QVBoxLayout(panel)
    panel_layout.setContentsMargins(30, 28, 30, 26)
    panel_layout.setSpacing(10)

    title = QLabel("No Results Loaded")
    title.setObjectName("resultsPreloadTitle")
    title.setAlignment(Qt.AlignCenter)

    description = QLabel(
        "Complete a Lumigon measurement run or reopen a saved measurement CSV. "
        "Run summary, photometric metrics, compliance results and plots will appear here."
    )
    description.setObjectName("resultsPreloadDescription")
    description.setWordWrap(True)
    description.setAlignment(Qt.AlignCenter)
    description.setMinimumWidth(0)
    description.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    hint = QLabel(
        "A newly completed Measurement run is transferred to Results automatically."
    )
    hint.setObjectName("resultsPreloadHint")
    hint.setWordWrap(True)
    hint.setAlignment(Qt.AlignCenter)
    hint.setMinimumHeight(24)
    hint.setMinimumWidth(0)
    hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    actions = QHBoxLayout()
    actions.setSpacing(8)
    actions.addStretch(1)

    # Reuse the existing buttons and their already-connected slots.
    load_button = workspace.load_csv_button
    folder_button = workspace.open_folder_button
    load_button.setMinimumWidth(130)
    folder_button.setMinimumWidth(150)
    actions.addWidget(load_button)
    actions.addWidget(folder_button)
    actions.addStretch(1)

    panel_layout.addStretch(1)
    panel_layout.addWidget(title)
    panel_layout.addWidget(description)
    panel_layout.addSpacing(4)
    panel_layout.addLayout(actions)
    panel_layout.addWidget(hint)
    panel_layout.addStretch(1)

    # Header remains fixed at item 0. Put the compact landing card directly
    # below it and leave the unused Results area below the card empty.
    root.insertWidget(1, panel, 0, Qt.AlignTop)

    workspace.setStyleSheet(
        workspace.styleSheet()
        + """
        QFrame#resultsPreloadPanel {
            background-color: #17232D;
            border: 1px solid #34495E;
            border-radius: 8px;
        }
        QLabel#resultsPreloadTitle {
            color: #E9F3FA;
            font-size: 15pt;
            font-weight: 700;
        }
        QLabel#resultsPreloadDescription {
            color: #AAB7C4;
            padding: 2px 24px;
        }
        QLabel#resultsPreloadHint {
            color: #748B9B;
            font-size: 9pt;
            padding-top: 4px;
        }
        """
    )

    original_set_run = workspace.set_run

    def set_run_with_preload_hidden(run):
        panel.hide()
        return original_set_run(run)

    workspace.set_run = set_run_with_preload_hidden
    workspace.preload_panel = panel
    return panel
