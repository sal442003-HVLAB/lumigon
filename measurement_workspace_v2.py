"""Minimal Version 2 Measurement workspace for Lumigon.

This page is intentionally setup-only for the first V2 step.  It does not
change Motion Control or Luxmeter behavior and it does not yet execute a scan.
The acquisition engine will be connected only after the new workflow is
validated.
"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


DEFAULT_DISTANCE_M = 5.00
DEFAULT_C_START_DEG = -80.0
DEFAULT_C_END_DEG = 80.0
DEFAULT_C_STEP_DEG = 10.0
DEFAULT_GAMMA_START_DEG = -5.0
DEFAULT_GAMMA_END_DEG = 5.0
DEFAULT_GAMMA_STEP_DEG = 1.0


def _angle_spin(*, minimum: float, maximum: float, value: float, step: float):
    control = QDoubleSpinBox()
    control.setRange(minimum, maximum)
    control.setDecimals(1)
    control.setSingleStep(step)
    control.setSuffix("°")
    control.setValue(value)
    control.setFixedWidth(150)
    return control


def _axis_count(start: float, end: float, step: float) -> int:
    step = abs(float(step))
    if step <= 0.0:
        return 0
    span = abs(float(end) - float(start))
    return int(math.floor(span / step + 1e-9)) + 1


def build_measurement_workspace_v2(window):
    """Build the clean Version 2 Measurement setup page."""

    page = QWidget()
    page.setObjectName("measurementWorkspace")

    root = QVBoxLayout(page)
    root.setContentsMargins(18, 16, 18, 18)
    root.setSpacing(14)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    header = QHBoxLayout()
    header.setSpacing(12)

    title_block = QVBoxLayout()
    title_block.setSpacing(2)

    title = QLabel("Measurement")
    title.setObjectName("measurementV2Title")

    subtitle = QLabel("Goniophotometric scan setup")
    subtitle.setObjectName("measurementV2Subtitle")

    title_block.addWidget(title)
    title_block.addWidget(subtitle)
    header.addLayout(title_block, 1)

    status = QLabel("V2  •  SETUP")
    status.setObjectName("measurementV2Status")
    status.setAlignment(Qt.AlignCenter)
    status.setFixedWidth(150)
    header.addWidget(status, 0, Qt.AlignVCenter)

    root.addLayout(header)

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------
    test_box = QGroupBox("Test")
    test_form = QFormLayout(test_box)
    test_form.setContentsMargins(14, 12, 14, 12)
    test_form.setHorizontalSpacing(18)
    test_form.setVerticalSpacing(10)

    sample_id = QLineEdit()
    sample_id.setPlaceholderText("Sample ID")
    sample_id.setMaximumWidth(360)

    distance = QDoubleSpinBox()
    distance.setRange(0.10, 1000.0)
    distance.setDecimals(2)
    distance.setSingleStep(0.10)
    distance.setSuffix(" m")
    distance.setValue(DEFAULT_DISTANCE_M)
    distance.setFixedWidth(150)

    measurement_method = QLabel("Flashing LED  •  I-effective")
    measurement_method.setObjectName("measurementV2Value")

    test_form.addRow("Sample:", sample_id)
    test_form.addRow("Distance:", distance)
    test_form.addRow("Measurement:", measurement_method)

    root.addWidget(test_box)

    # ------------------------------------------------------------------
    # Angular scan
    # ------------------------------------------------------------------
    scan_box = QGroupBox("Angular Scan")
    scan = QGridLayout(scan_box)
    scan.setContentsMargins(14, 12, 14, 12)
    scan.setHorizontalSpacing(12)
    scan.setVerticalSpacing(10)

    scan.addWidget(QLabel("Axis"), 0, 0)
    scan.addWidget(QLabel("Start"), 0, 1)
    scan.addWidget(QLabel("End"), 0, 2)
    scan.addWidget(QLabel("Resolution"), 0, 3)

    c_start = _angle_spin(
        minimum=-360.0,
        maximum=360.0,
        value=DEFAULT_C_START_DEG,
        step=10.0,
    )
    c_end = _angle_spin(
        minimum=-360.0,
        maximum=360.0,
        value=DEFAULT_C_END_DEG,
        step=10.0,
    )
    c_step = _angle_spin(
        minimum=0.1,
        maximum=90.0,
        value=DEFAULT_C_STEP_DEG,
        step=1.0,
    )

    gamma_start = _angle_spin(
        minimum=-90.0,
        maximum=90.0,
        value=DEFAULT_GAMMA_START_DEG,
        step=1.0,
    )
    gamma_end = _angle_spin(
        minimum=-90.0,
        maximum=90.0,
        value=DEFAULT_GAMMA_END_DEG,
        step=1.0,
    )
    gamma_step = _angle_spin(
        minimum=0.1,
        maximum=30.0,
        value=DEFAULT_GAMMA_STEP_DEG,
        step=0.5,
    )

    scan.addWidget(QLabel("C"), 1, 0)
    scan.addWidget(c_start, 1, 1)
    scan.addWidget(c_end, 1, 2)
    scan.addWidget(c_step, 1, 3)

    scan.addWidget(QLabel("Gamma"), 2, 0)
    scan.addWidget(gamma_start, 2, 1)
    scan.addWidget(gamma_end, 2, 2)
    scan.addWidget(gamma_step, 2, 3)

    scan.setColumnStretch(4, 1)

    summary = QLabel()
    summary.setObjectName("measurementV2Summary")
    summary.setWordWrap(True)
    scan.addWidget(summary, 3, 0, 1, 5)

    root.addWidget(scan_box)

    # ------------------------------------------------------------------
    # Acquisition summary — fixed workflow, not another set of controls.
    # ------------------------------------------------------------------
    acquisition_box = QGroupBox("Acquisition")
    acquisition = QGridLayout(acquisition_box)
    acquisition.setContentsMargins(14, 12, 14, 12)
    acquisition.setHorizontalSpacing(18)
    acquisition.setVerticalSpacing(8)

    acquisition.addWidget(QLabel("Photometer:"), 0, 0)
    acquisition.addWidget(QLabel("Gigahertz-Optik P-9710"), 0, 1)
    acquisition.addWidget(QLabel("Method:"), 1, 0)
    acquisition.addWidget(QLabel("CW waveform acquisition"), 1, 1)
    acquisition.addWidget(QLabel("Timing:"), 2, 0)
    acquisition.addWidget(QLabel("Automatic from optical pulse"), 2, 1)
    acquisition.addWidget(QLabel("Effective value:"), 3, 0)
    acquisition.addWidget(QLabel("Schmidt-Clausen in Lumigon"), 3, 1)
    acquisition.setColumnStretch(1, 1)

    root.addWidget(acquisition_box)

    # ------------------------------------------------------------------
    # One clear action. Execution intentionally remains disconnected.
    # ------------------------------------------------------------------
    footer = QHBoxLayout()
    footer.setSpacing(10)

    ready_note = QLabel("Setup only — scan execution will be connected in the next V2 step.")
    ready_note.setObjectName("measurementV2Note")
    ready_note.setWordWrap(True)
    footer.addWidget(ready_note, 1)

    start_button = QPushButton("Start Measurement")
    start_button.setFixedWidth(190)
    start_button.setEnabled(False)
    start_button.setToolTip(
        "V2 acquisition execution is intentionally not connected yet."
    )
    footer.addWidget(start_button, 0, Qt.AlignRight)

    root.addLayout(footer)
    root.addStretch(1)

    def update_summary(*_args):
        c_count = _axis_count(c_start.value(), c_end.value(), c_step.value())
        gamma_count = _axis_count(
            gamma_start.value(), gamma_end.value(), gamma_step.value()
        )
        total = c_count * gamma_count
        summary.setText(
            f"{c_count} C planes  •  {gamma_count} Gamma angles  •  "
            f"{total} measurement points"
        )

    for control in (
        c_start,
        c_end,
        c_step,
        gamma_start,
        gamma_end,
        gamma_step,
    ):
        control.valueChanged.connect(update_summary)

    update_summary()

    # Keep only the small, stable public surface needed by future V2 runtime.
    window.measurement_workspace = page
    window.measurement_v2_sample_id_edit = sample_id
    window.measurement_v2_distance_spin = distance
    window.measurement_v2_c_start = c_start
    window.measurement_v2_c_end = c_end
    window.measurement_v2_c_step = c_step
    window.measurement_v2_gamma_start = gamma_start
    window.measurement_v2_gamma_end = gamma_end
    window.measurement_v2_gamma_step = gamma_step
    window.measurement_v2_summary_label = summary
    window.measurement_v2_start_button = start_button

    page.setMinimumWidth(0)
    page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    page.setStyleSheet(
        """
        QWidget#measurementWorkspace {
            background-color: #101820;
        }
        QLabel#measurementV2Title {
            color: #E9F3FA;
            font-size: 20pt;
            font-weight: 700;
        }
        QLabel#measurementV2Subtitle,
        QLabel#measurementV2Note {
            color: #8299A9;
        }
        QLabel#measurementV2Status {
            color: #9DD5F3;
            background-color: #142A38;
            border: 1px solid #2C617E;
            border-radius: 5px;
            padding: 6px 10px;
            font-weight: 700;
        }
        QLabel#measurementV2Value {
            color: #DDEAF2;
            font-weight: 600;
        }
        QLabel#measurementV2Summary {
            color: #9FC4D8;
            background-color: #14212B;
            border: 1px solid #2B4050;
            border-radius: 5px;
            padding: 9px 11px;
        }
        """
    )

    return page
