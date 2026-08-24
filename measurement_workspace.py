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
MAX_PLAN_POINTS = 5000
MEASUREMENT_OVERHEAD_MS = 6
INTER_SAMPLE_DELAY_MS = 50

SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
SCAN_GRID = 2


def _readonly_item(text):
    item = QTableWidgetItem(str(text))
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def _format_duration(seconds):
    seconds = max(0.0, float(seconds))
    rounded = int(round(seconds))
    hours, remainder = divmod(rounded, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours} h {minutes} min {secs} s"
    if minutes:
        return f"{minutes} min {secs} s"
    return f"{secs} s"


def build_measurement_workspace(window):
    """Build the profile-driven Measurement workspace.

    This stage defines and validates test plans only.  It deliberately does not
    command either servo axis and does not launch synchronized lux acquisition.
    """

    page = QWidget()
    page.setObjectName("measurementWorkspace")

    root = QVBoxLayout(page)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(8)

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
    state.setMinimumWidth(210)

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

    scan_mode_combo = QComboBox()
    scan_mode_combo.addItems([
        "Single C / Gamma Sweep",
        "Single Gamma / C Sweep",
        "C × Gamma Grid",
    ])
    scan_grid.addWidget(QLabel("Scan mode:"), 0, 0)
    scan_grid.addWidget(scan_mode_combo, 0, 1, 1, 3)

    scan_grid.addWidget(QLabel("Axis"), 1, 0)
    scan_grid.addWidget(QLabel("Start / Fixed"), 1, 1)
    scan_grid.addWidget(QLabel("End"), 1, 2)
    scan_grid.addWidget(QLabel("Step"), 1, 3)

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

    scan_grid.addWidget(QLabel("C"), 2, 0)
    scan_grid.addWidget(c_start, 2, 1)
    scan_grid.addWidget(c_end, 2, 2)
    scan_grid.addWidget(c_step, 2, 3)

    scan_grid.addWidget(QLabel("Gamma"), 3, 0)
    scan_grid.addWidget(gamma_start, 3, 1)
    scan_grid.addWidget(gamma_end, 3, 2)
    scan_grid.addWidget(gamma_step, 3, 3)

    traversal_combo = QComboBox()
    traversal_combo.addItems([
        "Gamma sweep for each C position",
        "C sweep for each Gamma position",
    ])
    scan_grid.addWidget(QLabel("Traversal:"), 4, 0)
    scan_grid.addWidget(traversal_combo, 4, 1, 1, 3)

    envelope = QLabel(
        f"Current software envelope: ±{ABSOLUTE_LIMIT_DEG:g}° on both axes"
    )
    envelope.setObjectName("measurementEnvelope")
    envelope.setWordWrap(True)
    scan_grid.addWidget(envelope, 5, 0, 1, 4)

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
    # Plan controls / summary
    # ------------------------------------------------------------------
    plan_header = QHBoxLayout()
    plan_title = QLabel("Test Plan Preview")
    plan_title.setObjectName("measurementSectionTitle")

    plan_summary = QLabel("0 points  •  estimated acquisition time: —")
    plan_summary.setStyleSheet("color: #8AA8BC; padding-left: 12px;")

    build_button = QPushButton("Build Test Plan")
    validate_button = QPushButton("Validate Plan")
    validate_button.setObjectName("secondaryActionButton")

    plan_header.addWidget(plan_title)
    plan_header.addWidget(plan_summary)
    plan_header.addStretch(1)
    plan_header.addWidget(build_button)
    plan_header.addWidget(validate_button)
    root.addLayout(plan_header)

    plan_table = QTableWidget(0, 9)
    plan_table.setObjectName("measurementPlanTable")
    plan_table.setHorizontalHeaderLabels([
        "Point",
        "C",
        "Gamma",
        "Settle",
        "Samples",
        "Lux",
        "Candela",
        "Expected / Notes",
        "Status",
    ])
    plan_table.verticalHeader().setVisible(False)
    plan_table.setAlternatingRowColors(True)
    plan_table.setSelectionBehavior(QTableWidget.SelectRows)
    plan_table.setEditTriggers(QTableWidget.NoEditTriggers)
    plan_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    plan_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
    plan_table.setMinimumHeight(220)
    root.addWidget(plan_table, 1)

    # ------------------------------------------------------------------
    # Execution footer: visually isolated from the table.
    # ------------------------------------------------------------------
    execution_box = QGroupBox("Execution")
    execution_layout = QHBoxLayout(execution_box)
    execution_layout.setContentsMargins(10, 8, 10, 8)
    execution_layout.setSpacing(8)

    engine_note = QLabel(
        "Stage 1: validation gate only — automatic motor movement and synchronized acquisition are not connected yet."
    )
    engine_note.setObjectName("measurementEngineNote")
    engine_note.setWordWrap(True)

    start_button = QPushButton("Start Measurement")
    pause_button = QPushButton("Pause")
    abort_button = QPushButton("Abort")

    start_button.setEnabled(False)
    pause_button.setEnabled(False)
    abort_button.setEnabled(False)

    execution_layout.addWidget(engine_note, 1)
    execution_layout.addWidget(start_button)
    execution_layout.addWidget(pause_button)
    execution_layout.addWidget(abort_button)
    root.addWidget(execution_box, 0)

    plan_is_valid = False
    plan_points = []

    def _repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _set_state(text, object_name):
        state.setText(text)
        state.setObjectName(object_name)
        _repolish(state)

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

    def _estimated_acquisition_seconds(point_count):
        samples = samples_spin.value()
        measurement_s = (integration_spin.value() + MEASUREMENT_OVERHEAD_MS) / 1000.0
        inter_sample_s = INTER_SAMPLE_DELAY_MS / 1000.0
        sample_block_s = samples * measurement_s
        if samples > 1:
            sample_block_s += (samples - 1) * inter_sample_s
        return point_count * (settle_spin.value() + sample_block_s)

    def _update_plan_summary(point_count):
        estimate_s = _estimated_acquisition_seconds(point_count)
        plan_summary.setText(
            f"{point_count} points  •  estimated acquisition time: "
            f"≈ {_format_duration(estimate_s)}  •  motion time excluded"
        )

    def _mark_dirty(*_args):
        nonlocal plan_is_valid
        plan_is_valid = False
        start_button.setEnabled(False)
        _set_state("DRAFT  •  CHANGES NOT VALIDATED", "measurementStateDraft")

    def _sync_single_axis_values():
        mode = scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            c_end.setValue(c_start.value())
        elif mode == SCAN_SINGLE_GAMMA_C:
            gamma_end.setValue(gamma_start.value())

    def _apply_scan_mode(*_args):
        mode = scan_mode_combo.currentIndex()

        single_c = mode == SCAN_SINGLE_C_GAMMA
        single_gamma = mode == SCAN_SINGLE_GAMMA_C
        grid = mode == SCAN_GRID

        c_end.setEnabled(not single_c)
        c_step.setEnabled(not single_c)
        gamma_end.setEnabled(not single_gamma)
        gamma_step.setEnabled(not single_gamma)
        traversal_combo.setEnabled(grid)

        if single_c:
            c_end.setValue(c_start.value())
            traversal_combo.setCurrentIndex(0)
        elif single_gamma:
            gamma_end.setValue(gamma_start.value())
            traversal_combo.setCurrentIndex(1)

        _mark_dirty()

    def _build_points():
        mode = scan_mode_combo.currentIndex()

        if mode == SCAN_SINGLE_C_GAMMA:
            c_values = [c_start.value()]
            gamma_values = _axis_values(
                gamma_start.value(), gamma_end.value(), gamma_step.value()
            )
            return [(c_values[0], gamma_value) for gamma_value in gamma_values]

        if mode == SCAN_SINGLE_GAMMA_C:
            gamma_values = [gamma_start.value()]
            c_values = _axis_values(c_start.value(), c_end.value(), c_step.value())
            return [(c_value, gamma_values[0]) for c_value in c_values]

        c_values = _axis_values(c_start.value(), c_end.value(), c_step.value())
        gamma_values = _axis_values(
            gamma_start.value(), gamma_end.value(), gamma_step.value()
        )

        estimated_count = len(c_values) * len(gamma_values)
        if estimated_count > MAX_PLAN_POINTS:
            raise ValueError(
                f"The requested grid contains {estimated_count} points. "
                f"The current preview limit is {MAX_PLAN_POINTS} points. "
                "Increase the angular step or reduce the scan range."
            )

        points = []
        if traversal_combo.currentIndex() == 0:
            for c_value in c_values:
                for gamma_value in gamma_values:
                    points.append((c_value, gamma_value))
        else:
            for gamma_value in gamma_values:
                for c_value in c_values:
                    points.append((c_value, gamma_value))
        return points

    def build_plan():
        nonlocal plan_is_valid, plan_points

        _sync_single_axis_values()

        try:
            points = _build_points()
        except ValueError as exc:
            plan_table.setRowCount(0)
            plan_points = []
            plan_is_valid = False
            start_button.setEnabled(False)
            _set_state("INVALID  •  PLAN TOO LARGE", "measurementStateInvalid")
            plan_summary.setText("0 points  •  estimated acquisition time: —")
            QMessageBox.warning(window, "Measurement Plan", str(exc))
            return False

        if len(points) > MAX_PLAN_POINTS:
            QMessageBox.warning(
                window,
                "Measurement Plan",
                f"The requested plan contains {len(points)} points. "
                f"The current preview limit is {MAX_PLAN_POINTS} points.",
            )
            return False

        plan_points = points
        plan_is_valid = False
        start_button.setEnabled(False)

        plan_table.setRowCount(len(points))
        for row, (c_value, gamma_value) in enumerate(points):
            plan_table.setItem(row, 0, _readonly_item(row + 1))
            plan_table.setItem(row, 1, _readonly_item(f"{c_value:.2f}°"))
            plan_table.setItem(row, 2, _readonly_item(f"{gamma_value:.2f}°"))
            plan_table.setItem(row, 3, _readonly_item(f"{settle_spin.value():.1f} s"))
            plan_table.setItem(row, 4, _readonly_item(samples_spin.value()))
            plan_table.setItem(row, 5, _readonly_item("—"))
            plan_table.setItem(row, 6, _readonly_item("—"))
            plan_table.setItem(row, 7, _readonly_item("Development profile"))
            plan_table.setItem(row, 8, _readonly_item("Pending"))

        _update_plan_summary(len(points))
        _set_state(f"DRAFT  •  {len(points)} POINTS", "measurementStateDraft")
        return True

    def validate_plan():
        nonlocal plan_is_valid

        if not build_plan():
            return

        violations = []
        for point_index, (c_value, gamma_value) in enumerate(plan_points, start=1):
            if abs(c_value) > ABSOLUTE_LIMIT_DEG + 1e-9:
                violations.append(
                    f"Point {point_index}: C={c_value:g}° exceeds ±{ABSOLUTE_LIMIT_DEG:g}°"
                )
            if abs(gamma_value) > ABSOLUTE_LIMIT_DEG + 1e-9:
                violations.append(
                    f"Point {point_index}: Gamma={gamma_value:g}° exceeds ±{ABSOLUTE_LIMIT_DEG:g}°"
                )
            if len(violations) >= 10:
                break

        if violations:
            plan_is_valid = False
            start_button.setEnabled(False)
            _set_state("INVALID  •  OUTSIDE SAFE ENVELOPE", "measurementStateInvalid")
            QMessageBox.warning(
                window,
                "Measurement Plan",
                "The plan exceeds the current software motion envelope:\n\n"
                + "\n".join(violations),
            )
            return

        if not plan_points:
            plan_is_valid = False
            start_button.setEnabled(False)
            _set_state("INVALID  •  EMPTY PLAN", "measurementStateInvalid")
            return

        plan_is_valid = True
        _set_state(f"VALIDATED  •  {len(plan_points)} POINTS", "measurementStateValid")

        for row in range(plan_table.rowCount()):
            plan_table.setItem(row, 8, _readonly_item("Ready"))

        # The button now reflects the real validation gate.  The click handler
        # below is deliberately non-motion until the execution engine is wired.
        start_button.setEnabled(True)

    def start_measurement_preview():
        if not plan_is_valid:
            QMessageBox.warning(
                window,
                "Measurement",
                "Build and validate the test plan before starting a measurement.",
            )
            return

        QMessageBox.information(
            window,
            "Measurement Engine",
            "The plan is validated and ready for execution.\n\n"
            "Automatic axis movement and synchronized Lux acquisition are not "
            "connected in this stage, so no motor command has been issued.",
        )

    build_button.clicked.connect(build_plan)
    validate_button.clicked.connect(validate_plan)
    start_button.clicked.connect(start_measurement_preview)

    scan_mode_combo.currentIndexChanged.connect(_apply_scan_mode)
    traversal_combo.currentIndexChanged.connect(_mark_dirty)

    c_start.valueChanged.connect(_sync_single_axis_values)
    gamma_start.valueChanged.connect(_sync_single_axis_values)

    for control in (
        c_start,
        c_end,
        c_step,
        gamma_start,
        gamma_end,
        gamma_step,
        settle_spin,
        samples_spin,
        integration_spin,
        distance_spin,
    ):
        control.valueChanged.connect(_mark_dirty)

    application_combo.currentIndexChanged.connect(_mark_dirty)
    product_combo.currentIndexChanged.connect(_mark_dirty)
    profile_combo.currentIndexChanged.connect(_mark_dirty)
    sample_id_edit.textChanged.connect(_mark_dirty)
    use_profile_check.toggled.connect(_mark_dirty)

    # Initial MIOL development view: fixed C=0°, Gamma -5°...+5°.
    _apply_scan_mode()
    build_plan()

    window.measurement_workspace = page
    window.measurement_application_combo = application_combo
    window.measurement_product_combo = product_combo
    window.measurement_profile_combo = profile_combo
    window.measurement_standard_edit = standard_edit
    window.measurement_sample_id_edit = sample_id_edit
    window.measurement_distance_spin = distance_spin
    window.measurement_scan_mode_combo = scan_mode_combo
    window.measurement_c_start = c_start
    window.measurement_c_end = c_end
    window.measurement_c_step = c_step
    window.measurement_gamma_start = gamma_start
    window.measurement_gamma_end = gamma_end
    window.measurement_gamma_step = gamma_step
    window.measurement_scan_order_combo = traversal_combo
    window.measurement_settle_spin = settle_spin
    window.measurement_samples_spin = samples_spin
    window.measurement_integration_spin = integration_spin
    window.measurement_plan_summary_label = plan_summary
    window.measurement_plan_table = plan_table
    window.measurement_build_plan_button = build_button
    window.measurement_validate_plan_button = validate_button
    window.measurement_start_button = start_button
    window.measurement_pause_button = pause_button
    window.measurement_abort_button = abort_button
    window.measurement_state_label = state

    return page
