from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from machine_config import ABSOLUTE_LIMIT_DEG


DEFAULT_SETTLE_TIME_S = 1.0
DEFAULT_SAMPLES = 5
DEFAULT_INTEGRATION_MS = 100


def _readonly_item(text):
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def build_measurement_workspace(window):
    """Build the first profile-driven Measurement workspace.

    This stage intentionally creates the workflow/UI only.  It does not command
    either axis and it does not start automatic lux acquisition yet.  The goal is
    to establish a clean test-definition and test-plan layer before wiring it to
    the motion/acquisition engine.
    """

    page = QWidget()
    page.setObjectName("measurementWorkspace")

    root = QVBoxLayout(page)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(10)

    # ------------------------------------------------------------------
    # Title / state
    # ------------------------------------------------------------------
    title_row = QHBoxLayout()

    title_block = QVBoxLayout()
    title = QLabel("Measurement Workspace")
    title.setObjectName("measurementTitle")
    subtitle = QLabel(
        "Profile-driven photometric test definition, angular scan planning and acquisition workflow"
    )
    subtitle.setObjectName("measurementSubtitle")
    title_block.addWidget(title)
    title_block.addWidget(subtitle)

    state = QLabel("DRAFT  •  NOT VALIDATED")
    state.setObjectName("measurementStateDraft")
    state.setAlignment(Qt.AlignCenter)
    state.setMinimumWidth(190)

    title_row.addLayout(title_block, 1)
    title_row.addWidget(state, 0, Qt.AlignRight | Qt.AlignVCenter)
    root.addLayout(title_row)

    # ------------------------------------------------------------------
    # Top cards
    # ------------------------------------------------------------------
    cards = QHBoxLayout()
    cards.setSpacing(10)

    definition_box = QGroupBox("Test Definition")
    definition_form = QFormLayout(definition_box)
    definition_form.setContentsMargins(12, 12, 12, 12)
    definition_form.setSpacing(8)

    application_combo = QComboBox()
    application_combo.addItems([
        "Aviation",
        "Road Traffic Signals",
        "Automotive Lighting",
        "Custom Photometric Scan",
    ])

    product_combo = QComboBox()
    product_combo.addItems([
        "Obstacle Light",
        "Airfield Ground Light",
        "Other / Custom",
    ])

    profile_combo = QComboBox()
    profile_combo.addItems([
        "MIOL — Development Profile",
        "Custom Photometric Scan",
    ])

    standard_edit = QLineEdit("Development profile — standard not assigned")
    standard_edit.setReadOnly(True)

    sample_id_edit = QLineEdit()
    sample_id_edit.setPlaceholderText("e.g. Sample-001")

    distance_spin = QDoubleSpinBox()
    distance_spin.setRange(0.10, 1000.0)
    distance_spin.setDecimals(2)
    distance_spin.setSingleStep(0.5)
    distance_spin.setSuffix(" m")
    distance_spin.setValue(10.0)

    definition_form.addRow("Application:", application_combo)
    definition_form.addRow("Product:", product_combo)
    definition_form.addRow("Profile:", profile_combo)
    definition_form.addRow("Standard:", standard_edit)
    definition_form.addRow("Sample ID:", sample_id_edit)
    definition_form.addRow("Measurement distance:", distance_spin)

    scan_box = QGroupBox("Angular Scan")
    scan_grid = QGridLayout(scan_box)
    scan_grid.setContentsMargins(12, 12, 12, 12)
    scan_grid.setHorizontalSpacing(8)
    scan_grid.setVerticalSpacing(8)

    scan_grid.addWidget(QLabel("Axis"), 0, 0)
    scan_grid.addWidget(QLabel("Start"), 0, 1)
    scan_grid.addWidget(QLabel("End"), 0, 2)
    scan_grid.addWidget(QLabel("Step"), 0, 3)

    c_start = QDoubleSpinBox()
    c_end = QDoubleSpinBox()
    c_step = QDoubleSpinBox()
    gamma_start = QDoubleSpinBox()
    gamma_end = QDoubleSpinBox()
    gamma_step = QDoubleSpinBox()

    for control in (c_start, c_end, gamma_start, gamma_end):
        control.setRange(-ABSOLUTE_LIMIT_DEG, ABSOLUTE_LIMIT_DEG)
        control.setDecimals(2)
        control.setSingleStep(0.5)
        control.setSuffix("°")

    for control in (c_step, gamma_step):
        control.setRange(0.10, 30.0)
        control.setDecimals(2)
        control.setSingleStep(0.5)
        control.setSuffix("°")
        control.setValue(1.0)

    c_start.setValue(0.0)
    c_end.setValue(0.0)
    gamma_start.setValue(-5.0)
    gamma_end.setValue(5.0)

    scan_grid.addWidget(QLabel("C"), 1, 0)
    scan_grid.addWidget(c_start, 1, 1)
    scan_grid.addWidget(c_end, 1, 2)
    scan_grid.addWidget(c_step, 1, 3)

    scan_grid.addWidget(QLabel("Gamma"), 2, 0)
    scan_grid.addWidget(gamma_start, 2, 1)
    scan_grid.addWidget(gamma_end, 2, 2)
    scan_grid.addWidget(gamma_step, 2, 3)

    order_combo = QComboBox()
    order_combo.addItems([
        "Gamma sweep at fixed C",
        "C sweep at fixed Gamma",
    ])
    scan_grid.addWidget(QLabel("Scan order:"), 3, 0)
    scan_grid.addWidget(order_combo, 3, 1, 1, 3)

    envelope = QLabel(
        f"Current software envelope: ±{ABSOLUTE_LIMIT_DEG:g}° on both axes"
    )
    envelope.setObjectName("measurementEnvelope")
    envelope.setWordWrap(True)
    scan_grid.addWidget(envelope, 4, 0, 1, 4)

    acquisition_box = QGroupBox("Acquisition")
    acquisition_form = QFormLayout(acquisition_box)
    acquisition_form.setContentsMargins(12, 12, 12, 12)
    acquisition_form.setSpacing(8)

    settle_spin = QDoubleSpinBox()
    settle_spin.setRange(0.0, 30.0)
    settle_spin.setDecimals(1)
    settle_spin.setSingleStep(0.1)
    settle_spin.setSuffix(" s")
    settle_spin.setValue(DEFAULT_SETTLE_TIME_S)

    samples_spin = QSpinBox()
    samples_spin.setRange(1, 50)
    samples_spin.setValue(DEFAULT_SAMPLES)

    integration_spin = QSpinBox()
    integration_spin.setRange(10, 400)
    integration_spin.setSingleStep(10)
    integration_spin.setSuffix(" ms")
    integration_spin.setValue(DEFAULT_INTEGRATION_MS)

    use_profile_check = QCheckBox("Apply these settings for this run")
    use_profile_check.setChecked(True)

    source_label = QLabel("C&G Ph-Amp MB7 → photocurrent → Lux")
    source_label.setWordWrap(True)

    acquisition_form.addRow("Settling time:", settle_spin)
    acquisition_form.addRow("Samples / point:", samples_spin)
    acquisition_form.addRow("Integration:", integration_spin)
    acquisition_form.addRow("Source:", source_label)
    acquisition_form.addRow("", use_profile_check)

    cards.addWidget(definition_box, 4)
    cards.addWidget(scan_box, 4)
    cards.addWidget(acquisition_box, 3)
    root.addLayout(cards)

    # ------------------------------------------------------------------
    # Plan controls
    # ------------------------------------------------------------------
    plan_header = QHBoxLayout()
    plan_title = QLabel("Test Plan Preview")
    plan_title.setObjectName("measurementSectionTitle")

    build_button = QPushButton("Build Test Plan")
    validate_button = QPushButton("Validate Plan")
    validate_button.setObjectName("secondaryActionButton")

    plan_header.addWidget(plan_title)
    plan_header.addStretch(1)
    plan_header.addWidget(build_button)
    plan_header.addWidget(validate_button)
    root.addLayout(plan_header)

    plan_table = QTableWidget(0, 7)
    plan_table.setObjectName("measurementPlanTable")
    plan_table.setHorizontalHeaderLabels([
        "Point",
        "C",
        "Gamma",
        "Settle",
        "Samples",
        "Expected / Notes",
        "Status",
    ])
    plan_table.verticalHeader().setVisible(False)
    plan_table.setAlternatingRowColors(True)
    plan_table.setSelectionBehavior(QTableWidget.SelectRows)
    plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
    plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    plan_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
    plan_table.setMinimumHeight(250)
    root.addWidget(plan_table, 1)

    # ------------------------------------------------------------------
    # Execution footer — intentionally disabled until engine stage.
    # ------------------------------------------------------------------
    footer = QHBoxLayout()
    engine_note = QLabel(
        "Stage 1: plan definition only. Motor movement and synchronized acquisition are not connected yet."
    )
    engine_note.setObjectName("measurementEngineNote")
    engine_note.setWordWrap(True)

    start_button = QPushButton("Start Measurement")
    pause_button = QPushButton("Pause")
    abort_button = QPushButton("Abort")

    start_button.setEnabled(False)
    pause_button.setEnabled(False)
    abort_button.setEnabled(False)
    start_button.setToolTip("Enabled after the measurement engine is connected in the next stage.")

    footer.addWidget(engine_note, 1)
    footer.addWidget(start_button)
    footer.addWidget(pause_button)
    footer.addWidget(abort_button)
    root.addLayout(footer)

    def _axis_values(start, end, step):
        start = float(start)
        end = float(end)
        step = abs(float(step))
        if step <= 0.0:
            return []

        direction = 1.0 if end >= start else -1.0
        signed_step = step * direction
        values = []
        current = start
        epsilon = 1e-9

        if direction > 0:
            while current <= end + epsilon:
                values.append(round(current, 6))
                current += signed_step
        else:
            while current >= end - epsilon:
                values.append(round(current, 6))
                current += signed_step

        if values and abs(values[-1] - end) > epsilon:
            values.append(round(end, 6))
        return values

    def build_plan():
        c_values = _axis_values(c_start.value(), c_end.value(), c_step.value())
        gamma_values = _axis_values(
            gamma_start.value(), gamma_end.value(), gamma_step.value()
        )

        points = []
        if order_combo.currentIndex() == 0:
            for c_value in c_values:
                for gamma_value in gamma_values:
                    points.append((c_value, gamma_value))
        else:
            for gamma_value in gamma_values:
                for c_value in c_values:
                    points.append((c_value, gamma_value))

        plan_table.setRowCount(len(points))
        for row, (c_value, gamma_value) in enumerate(points):
            plan_table.setItem(row, 0, _readonly_item(row + 1))
            plan_table.setItem(row, 1, _readonly_item(f"{c_value:.2f}°"))
            plan_table.setItem(row, 2, _readonly_item(f"{gamma_value:.2f}°"))
            plan_table.setItem(row, 3, _readonly_item(f"{settle_spin.value():.1f} s"))
            plan_table.setItem(row, 4, _readonly_item(samples_spin.value()))
            plan_table.setItem(row, 5, _readonly_item("Development profile"))
            plan_table.setItem(row, 6, _readonly_item("Pending"))

        state.setText(f"DRAFT  •  {len(points)} POINTS")
        state.setObjectName("measurementStateDraft")
        state.style().unpolish(state)
        state.style().polish(state)

    def validate_plan():
        if plan_table.rowCount() == 0:
            build_plan()

        violations = []
        for name, value in (
            ("C start", c_start.value()),
            ("C end", c_end.value()),
            ("Gamma start", gamma_start.value()),
            ("Gamma end", gamma_end.value()),
        ):
            if abs(value) > ABSOLUTE_LIMIT_DEG:
                violations.append(f"{name}: {value:g}°")

        if violations:
            state.setText("INVALID  •  OUTSIDE SAFE ENVELOPE")
            state.setObjectName("measurementStateInvalid")
            state.style().unpolish(state)
            state.style().polish(state)
            QMessageBox.warning(
                window,
                "Measurement Plan",
                "The plan exceeds the current software motion envelope:\n\n"
                + "\n".join(violations),
            )
            return

        state.setText(f"VALIDATED  •  {plan_table.rowCount()} POINTS")
        state.setObjectName("measurementStateValid")
        state.style().unpolish(state)
        state.style().polish(state)

        for row in range(plan_table.rowCount()):
            plan_table.setItem(row, 6, _readonly_item("Ready"))

    build_button.clicked.connect(build_plan)
    validate_button.clicked.connect(validate_plan)

    # Give the first opening of the tab a useful, concrete MIOL development
    # preview without performing any hardware action.
    build_plan()

    window.measurement_workspace = page
    window.measurement_application_combo = application_combo
    window.measurement_product_combo = product_combo
    window.measurement_profile_combo = profile_combo
    window.measurement_standard_edit = standard_edit
    window.measurement_sample_id_edit = sample_id_edit
    window.measurement_distance_spin = distance_spin
    window.measurement_c_start = c_start
    window.measurement_c_end = c_end
    window.measurement_c_step = c_step
    window.measurement_gamma_start = gamma_start
    window.measurement_gamma_end = gamma_end
    window.measurement_gamma_step = gamma_step
    window.measurement_scan_order_combo = order_combo
    window.measurement_settle_spin = settle_spin
    window.measurement_samples_spin = samples_spin
    window.measurement_integration_spin = integration_spin
    window.measurement_plan_table = plan_table
    window.measurement_build_plan_button = build_button
    window.measurement_validate_plan_button = validate_button
    window.measurement_start_button = start_button
    window.measurement_pause_button = pause_button
    window.measurement_abort_button = abort_button
    window.measurement_state_label = state

    return page
