"""Compact layout for profile-specific Measurement panels.

Presentation-only helper: keep the existing obstacle workflow and MIOL widgets
and their signal connections intact, but arrange them side by side to reduce
vertical scrolling on the Measurement page.
"""

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


def attach_measurement_profile_layout(window):
    if getattr(window, "measurement_profile_panels_row", None) is not None:
        return window.measurement_profile_panels_row

    workspace = getattr(window, "measurement_workspace", None)
    obstacle_box = getattr(window, "measurement_obstacle_workflow_box", None)
    miol_box = getattr(window, "measurement_miol_profile_box", None)
    if workspace is None or obstacle_box is None or miol_box is None:
        raise RuntimeError("Measurement profile panels are not ready for compact layout.")

    root = workspace.layout()
    if root is None:
        raise RuntimeError("Measurement workspace layout is not available.")

    # Preserve the earlier of the two positions so the combined row remains in
    # the same general place in the Measurement workflow.
    obstacle_index = root.indexOf(obstacle_box)
    miol_index = root.indexOf(miol_box)
    indices = [index for index in (obstacle_index, miol_index) if index >= 0]
    insert_index = min(indices) if indices else min(2, root.count())

    # removeWidget only removes them from the root layout; it does not destroy
    # either widget or any of their existing signal/slot connections.
    root.removeWidget(obstacle_box)
    root.removeWidget(miol_box)

    row_widget = QWidget(workspace)
    row_widget.setObjectName("measurementProfilePanelsRow")
    row_widget.setMinimumWidth(0)
    row_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    row = QHBoxLayout(row_widget)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)

    obstacle_box.setMinimumWidth(0)
    miol_box.setMinimumWidth(0)
    obstacle_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    miol_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    row.addWidget(obstacle_box, 11)
    row.addWidget(miol_box, 9)

    root.insertWidget(insert_index, row_widget)

    window.measurement_profile_panels_row = row_widget
    return row_widget
