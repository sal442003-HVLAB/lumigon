import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from machine_config import ABSOLUTE_LIMIT_DEG
from measurement_execution import (
    SCAN_GRID,
    SCAN_SINGLE_C_GAMMA,
    SCAN_SINGLE_GAMMA_C,
    MeasurementRunWorker,
)


DEFAULT_SETTLE_TIME_S = 1.0
DEFAULT_SAMPLES = 5
DEFAULT_INTEGRATION_MS = 100
MAX_PLAN_POINTS = 5000
MEASUREMENT_OVERHEAD_MS = 6
INTER_SAMPLE_DELAY_MS = 50


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


class MeasurementProgressDialog(QDialog):
    """Run monitor for an automatic measurement sequence."""

    def __init__(self, total_points, initial_estimate_s, parent=None):
        super().__init__(parent)
        self.total_points = max(1, int(total_points))
        self.initial_estimate_s = max(0.0, float(initial_estimate_s))
        self.completed_points = 0
        self.started_at = time.monotonic()
        self.run_finished = False

        self.setWindowTitle("Lumigon — Measurement Run")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Automatic Measurement in Progress")
        title.setObjectName("measurementRunTitle")
        root.addWidget(title)

        self.status_label = QLabel("Preparing measurement…")
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("measurementRunStatus")
        root.addWidget(self.status_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)

        self.current_point_label = QLabel("—")
        self.target_label = QLabel("—")
        self.completed_label = QLabel("0")
        self.remaining_label = QLabel(str(self.total_points))
        self.elapsed_label = QLabel("0 s")
        self.eta_label = QLabel(_format_duration(self.initial_estimate_s))

        grid.addWidget(QLabel("Current point:"), 0, 0)
        grid.addWidget(self.current_point_label, 0, 1)
        grid.addWidget(QLabel("Target:"), 1, 0)
        grid.addWidget(self.target_label, 1, 1)
        grid.addWidget(QLabel("Completed:"), 2, 0)
        grid.addWidget(self.completed_label, 2, 1)
        grid.addWidget(QLabel("Remaining:"), 3, 0)
        grid.addWidget(self.remaining_label, 3, 1)
        grid.addWidget(QLabel("Elapsed:"), 4, 0)
        grid.addWidget(self.elapsed_label, 4, 1)
        grid.addWidget(QLabel("Estimated remaining:"), 5, 0)
        grid.addWidget(self.eta_label, 5, 1)
        root.addLayout(grid)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, self.total_points)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("%v / %m points   •   %p%")
        root.addWidget(self.progress_bar)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.pause_button = QPushButton("Pause")
        self.abort_button = QPushButton("Abort")
        controls.addWidget(self.pause_button)
        controls.addWidget(self.abort_button)
        root.addLayout(controls)

        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(500)
        self.clock_timer.timeout.connect(self._refresh_times)
        self.clock_timer.start()

        self.setStyleSheet(
            """
            QDialog {
                background-color: #101820;
                color: #E8EEF3;
            }
            QLabel#measurementRunTitle {
                color: #4DA3FF;
                font-size: 16pt;
                font-weight: 700;
            }
            QLabel#measurementRunStatus {
                color: #C7D7E2;
                background-color: #17232D;
                border: 1px solid #34495E;
                border-radius: 6px;
                padding: 10px;
            }
            QProgressBar {
                border: 1px solid #34495E;
                border-radius: 5px;
                background-color: #111B23;
                text-align: center;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background-color: #1769AA;
                border-radius: 4px;
            }
            """
        )

    def _refresh_times(self):
        elapsed = max(0.0, time.monotonic() - self.started_at)
        self.elapsed_label.setText(_format_duration(elapsed))

        remaining_points = max(0, self.total_points - self.completed_points)
        if self.completed_points > 0:
            avg_point_s = elapsed / self.completed_points
            eta_s = avg_point_s * remaining_points
        else:
            eta_s = max(0.0, self.initial_estimate_s - elapsed)
        self.eta_label.setText(_format_duration(eta_s))

    def set_point(self, sequence, total, c_deg, gamma_deg):
        self.current_point_label.setText(f"{sequence} / {total}")
        self.target_label.setText(f"C {c_deg:+.3f}°   •   Gamma {gamma_deg:+.3f}°")

    def set_status(self, text):
        self.status_label.setText(text)

    def set_completed(self, completed):
        self.completed_points = max(0, min(int(completed), self.total_points))
        remaining = max(0, self.total_points - self.completed_points)
        self.completed_label.setText(str(self.completed_points))
        self.remaining_label.setText(str(remaining))
        self.progress_bar.setValue(self.completed_points)
        self._refresh_times()

    def set_paused(self, paused):
        if paused:
            self.pause_button.setText("Resume")
            self.set_status("Measurement paused at a safe checkpoint.")
        else:
            self.pause_button.setText("Pause")

    def finish(self, text):
        self.run_finished = True
        self.clock_timer.stop()
        self.set_status(text)
        self.pause_button.setEnabled(False)
        self.abort_button.setEnabled(False)



def build_measurement_workspace(window):
    """Build profile-driven planning and automatic single-axis execution."""

    page = QWidget()
    page.setObjectName("measurementWorkspace")

    root = QVBoxLayout(page)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(8)

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
    scan_grid.setVerticalSpacing(7)

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

    traversal_label = QLabel("Traversal:")
    traversal_combo = QComboBox()
    traversal_combo.addItems([
        "Gamma sweep for each C position",
        "C sweep for each Gamma position",
    ])
    scan_grid.addWidget(traversal_label, 4, 0)
    scan_grid.addWidget(traversal_combo, 4, 1, 1, 3)

    envelope = QLabel(
        f"Current enforced software envelope: ±{ABSOLUTE_LIMIT_DEG:g}° on both axes"
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

    execution_box = QGroupBox("Execution")
    execution_layout = QHBoxLayout(execution_box)
    execution_layout.setContentsMargins(10, 8, 10, 8)
    execution_layout.setSpacing(8)

    engine_note = QLabel(
        "Validate a single-axis plan, then Start Measurement to run all Ready points automatically."
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
    execution_running = False
    active_worker = None
    progress_dialog = None
    main_timer_was_active = False
    run_completed_normally = False

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

    def _ready_rows():
        rows = []
        for row in range(plan_table.rowCount()):
            item = plan_table.item(row, 8)
            if item is not None and item.text() == "Ready":
                rows.append(row)
        return rows

    def _measured_count():
        count = 0
        for row in range(plan_table.rowCount()):
            item = plan_table.item(row, 8)
            if item is not None and item.text() == "Measured":
                count += 1
        return count

    def _mark_dirty(*_args):
        nonlocal plan_is_valid
        if execution_running:
            return
        plan_is_valid = False
        start_button.setEnabled(False)
        _set_state("DRAFT  •  CHANGES NOT VALIDATED", "measurementStateDraft")

    def _sync_single_axis_values():
        mode = scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            c_end.setValue(c_start.value())
        elif mode == SCAN_SINGLE_GAMMA_C:
            gamma_end.setValue(gamma_start.value())

    def _refresh_scan_mode_controls():
        mode = scan_mode_combo.currentIndex()
        single_c = mode == SCAN_SINGLE_C_GAMMA
        single_gamma = mode == SCAN_SINGLE_GAMMA_C
        grid = mode == SCAN_GRID

        c_end.setEnabled(not single_c)
        c_step.setEnabled(not single_c)
        gamma_end.setEnabled(not single_gamma)
        gamma_step.setEnabled(not single_gamma)
        traversal_label.setVisible(grid)
        traversal_combo.setVisible(grid)
        traversal_combo.setEnabled(grid)

    def _apply_scan_mode(*_args):
        mode = scan_mode_combo.currentIndex()
        if mode == SCAN_SINGLE_C_GAMMA:
            c_end.setValue(c_start.value())
            traversal_combo.setCurrentIndex(0)
        elif mode == SCAN_SINGLE_GAMMA_C:
            gamma_end.setValue(gamma_start.value())
            traversal_combo.setCurrentIndex(1)
        _refresh_scan_mode_controls()
        _mark_dirty()

    def _set_editor_enabled(enabled):
        for control in (
            application_combo,
            product_combo,
            profile_combo,
            sample_id_edit,
            distance_spin,
            scan_mode_combo,
            c_start,
            c_end,
            c_step,
            gamma_start,
            gamma_end,
            gamma_step,
            traversal_combo,
            settle_spin,
            samples_spin,
            integration_spin,
            use_profile_check,
            build_button,
            validate_button,
        ):
            control.setEnabled(enabled)
        if enabled:
            _refresh_scan_mode_controls()

    def _build_points():
        mode = scan_mode_combo.currentIndex()

        if mode == SCAN_SINGLE_C_GAMMA:
            c_value = c_start.value()
            gamma_values = _axis_values(
                gamma_start.value(), gamma_end.value(), gamma_step.value()
            )
            return [(c_value, gamma_value) for gamma_value in gamma_values]

        if mode == SCAN_SINGLE_GAMMA_C:
            gamma_value = gamma_start.value()
            c_values = _axis_values(c_start.value(), c_end.value(), c_step.value())
            return [(c_value, gamma_value) for c_value in c_values]

        c_values = _axis_values(c_start.value(), c_end.value(), c_step.value())
        gamma_values = _axis_values(
            gamma_start.value(), gamma_end.value(), gamma_step.value()
        )

        estimated_count = len(c_values) * len(gamma_values)
        if estimated_count > MAX_PLAN_POINTS:
            raise ValueError(
                f"The requested grid contains {estimated_count} points. "
                f"The current preview limit is {MAX_PLAN_POINTS} points."
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

        if execution_running:
            return False

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
        window.measurement_results = []

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
        engine_note.setText(
            "Plan built. Validate it before automatic execution."
        )
        return True

    def validate_plan():
        nonlocal plan_is_valid

        if execution_running:
            return
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
                "The plan exceeds the current enforced software motion envelope:\n\n"
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

        if scan_mode_combo.currentIndex() == SCAN_GRID:
            start_button.setEnabled(False)
            engine_note.setText(
                "Plan validated. C × Gamma Grid execution remains disabled while the "
                "current commissioning interlock requires the non-sweep servo to stay OFF."
            )
        else:
            start_button.setEnabled(True)
            engine_note.setText(
                "Plan validated. Start Measurement will execute all Ready points from start to end."
            )

    def _measurement_prerequisites():
        if not plan_is_valid:
            return "Build and validate the test plan before measuring."
        if scan_mode_combo.currentIndex() == SCAN_GRID:
            return (
                "C × Gamma Grid automatic execution is not enabled yet. "
                "Use a single-axis scan during this commissioning stage."
            )

        modbus = getattr(window, "modbus", None)
        if modbus is None or not modbus.is_connected:
            return "Connect the servo drives before measuring."

        motion = getattr(window, "motion", None)
        if motion is None:
            return "Motion controller is not available."
        if motion.gamma_zero_puu is None or motion.c_zero_puu is None:
            return "Capture a valid Session Zero for both axes before measuring."

        meter = getattr(window, "luxmeter", None)
        if meter is None or not meter.is_connected:
            return "Connect the Luxmeter before measuring."

        live_worker = getattr(window, "luxmeter_live_worker", None)
        if live_worker is not None and live_worker.isRunning():
            return "Stop Luxmeter Live acquisition before starting a formal measurement run."

        if not _ready_rows():
            return "There are no Ready points remaining in this plan."
        return None

    def _confirmation_text(ready_rows):
        mode = scan_mode_combo.currentIndex()
        first_row = ready_rows[0]
        last_row = ready_rows[-1]
        first_c, first_gamma = plan_points[first_row]
        last_c, last_gamma = plan_points[last_row]

        if mode == SCAN_SINGLE_C_GAMMA:
            axis_text = (
                f"C remains fixed at {first_c:+.3f}°.\n"
                f"Gamma scan: {first_gamma:+.3f}° → {last_gamma:+.3f}°.\n"
                "Commissioning interlock: Gamma servo must be ON and C servo OFF."
            )
        else:
            axis_text = (
                f"Gamma remains fixed at {first_gamma:+.3f}°.\n"
                f"C scan: {first_c:+.3f}° → {last_c:+.3f}°.\n"
                "Commissioning interlock: C servo must be ON and Gamma servo OFF."
            )

        return (
            f"Start automatic measurement of {len(ready_rows)} Ready points?\n\n"
            f"{axis_text}\n\n"
            f"Settling: {settle_spin.value():.1f} s / point\n"
            f"Samples: {samples_spin.value()} / point\n"
            f"Distance: {distance_spin.value():.2f} m\n\n"
            "The run proceeds from the first Ready point to the last without "
            "asking for confirmation at each point."
        )

    def _finish_execution_ui():
        nonlocal execution_running, active_worker, progress_dialog
        nonlocal main_timer_was_active, run_completed_normally

        worker = active_worker
        if worker is not None:
            worker.deleteLater()
        active_worker = None
        window.measurement_worker = None
        execution_running = False

        if main_timer_was_active:
            modbus = getattr(window, "modbus", None)
            timer = getattr(window, "timer", None)
            if modbus is not None and modbus.is_connected and timer is not None:
                timer.start()
        main_timer_was_active = False

        _set_editor_enabled(True)
        pause_button.setEnabled(False)
        pause_button.setText("Pause")
        abort_button.setEnabled(False)

        measured = _measured_count()
        total = plan_table.rowCount()
        remaining = len(_ready_rows())

        if run_completed_normally and total > 0 and remaining == 0:
            _set_state(f"COMPLETE  •  {measured}/{total} MEASURED", "measurementStateValid")
            start_button.setEnabled(False)
            engine_note.setText("Measurement run complete — all validated points were measured.")
        else:
            _set_state(
                f"VALIDATED  •  {measured}/{total} MEASURED",
                "measurementStateValid",
            )
            start_button.setEnabled(plan_is_valid and remaining > 0)

        if progress_dialog is not None:
            QTimer.singleShot(800, progress_dialog.accept)
        progress_dialog = None
        run_completed_normally = False

    def start_measurement_run():
        nonlocal execution_running, active_worker, progress_dialog
        nonlocal main_timer_was_active, run_completed_normally

        problem = _measurement_prerequisites()
        if problem:
            QMessageBox.warning(window, "Measurement", problem)
            return

        ready_rows = _ready_rows()
        answer = QMessageBox.question(
            window,
            "Confirm Automatic Measurement",
            _confirmation_text(ready_rows),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        meter = window.luxmeter
        if hasattr(window, "luxmeter_sensitivity_spin"):
            meter.sensitivity_na_per_lx = window.luxmeter_sensitivity_spin.value()

        run_points = [
            (row, plan_points[row][0], plan_points[row][1])
            for row in ready_rows
        ]

        worker = MeasurementRunWorker(
            motion=window.motion,
            meter=meter,
            scan_mode=scan_mode_combo.currentIndex(),
            points=run_points,
            settle_time_s=settle_spin.value(),
            samples=samples_spin.value(),
            integration_ms=integration_spin.value(),
            apply_measurement_settings=use_profile_check.isChecked(),
            distance_m=distance_spin.value(),
            parent=window,
        )

        dialog = MeasurementProgressDialog(
            len(run_points),
            _estimated_acquisition_seconds(len(run_points)),
            parent=window,
        )

        execution_running = True
        active_worker = worker
        progress_dialog = dialog
        window.measurement_worker = worker
        window.measurement_progress_dialog = dialog
        run_completed_normally = False

        timer = getattr(window, "timer", None)
        main_timer_was_active = bool(timer is not None and timer.isActive())
        if main_timer_was_active:
            timer.stop()

        _set_editor_enabled(False)
        start_button.setEnabled(False)
        pause_button.setEnabled(True)
        abort_button.setEnabled(True)
        _set_state(
            f"RUNNING  •  0/{len(run_points)} MEASURED",
            "measurementStateDraft",
        )
        engine_note.setText("Automatic measurement run started.")

        completed_this_run = 0
        paused = False

        def on_progress(message):
            engine_note.setText(message)
            dialog.set_status(message)

        def on_point_started(row, sequence, total, c_deg, gamma_deg):
            plan_table.setItem(row, 8, _readonly_item("Running"))
            plan_table.selectRow(row)
            first_item = plan_table.item(row, 0)
            if first_item is not None:
                plan_table.scrollToItem(first_item)
            dialog.set_point(sequence, total, c_deg, gamma_deg)
            _set_state(
                f"RUNNING  •  POINT {sequence}/{total}",
                "measurementStateDraft",
            )

        def on_point_result(row, current_na, lux, stdev_lux, candela):
            nonlocal completed_this_run
            completed_this_run += 1

            c_target, gamma_target = plan_points[row]
            plan_table.setItem(row, 5, _readonly_item(f"{lux:.3f}"))
            plan_table.setItem(row, 6, _readonly_item(f"{candela:.1f}"))
            plan_table.setItem(row, 8, _readonly_item("Measured"))

            if hasattr(window, "luxmeter_current_label"):
                window.luxmeter_current_label.setText(f"Current: {current_na:.2f} nA")
            if hasattr(window, "luxmeter_lux_label"):
                window.luxmeter_lux_label.setText(f"Lux: {lux:.3f} lx")
            if hasattr(window, "luxmeter_stability_label"):
                window.luxmeter_stability_label.setText(
                    f"Std. dev.: {stdev_lux:.3f} lx"
                )

            window.luxmeter_last_current_a = current_na * 1e-9
            window.luxmeter_last_lux = lux
            window.measurement_results.append({
                "point": row + 1,
                "c_deg": c_target,
                "gamma_deg": gamma_target,
                "lux": lux,
                "candela": candela,
                "stdev_lux": stdev_lux,
                "mean_current_na": current_na,
                "distance_m": distance_spin.value(),
                "samples": samples_spin.value(),
                "integration_ms": meter.integration_time_ms,
            })

            dialog.set_completed(completed_this_run)
            engine_note.setText(
                f"Point {row + 1} measured: {lux:.3f} lx  •  "
                f"{candela:.1f} cd  •  σ={stdev_lux:.3f} lx"
            )

        def on_pause_state(is_paused):
            nonlocal paused
            paused = bool(is_paused)
            pause_button.setText("Resume" if paused else "Pause")
            dialog.set_paused(paused)

        def toggle_pause():
            if active_worker is None or not active_worker.isRunning():
                return
            active_worker.request_pause(not paused)

        def request_abort():
            if active_worker is None or not active_worker.isRunning():
                return
            active_worker.requestInterruption()
            active_worker.request_pause(False)
            pause_button.setEnabled(False)
            abort_button.setEnabled(False)
            dialog.pause_button.setEnabled(False)
            dialog.abort_button.setEnabled(False)
            message = (
                "Abort requested — an active servo move is allowed to finish safely; "
                "the run will stop at the next safe checkpoint."
            )
            engine_note.setText(message)
            dialog.set_status(message)

        def on_aborted(message):
            for row in ready_rows:
                item = plan_table.item(row, 8)
                if item is not None and item.text() == "Running":
                    plan_table.setItem(row, 8, _readonly_item("Ready"))
            engine_note.setText(message)
            dialog.finish(message)

        def on_failed(message):
            for row in ready_rows:
                item = plan_table.item(row, 8)
                if item is not None and item.text() == "Running":
                    plan_table.setItem(row, 8, _readonly_item("Ready"))
            engine_note.setText("Measurement run stopped due to an error.")
            dialog.finish("Measurement run failed.")
            QMessageBox.critical(window, "Measurement Run Error", message)

        def on_completed():
            nonlocal run_completed_normally
            run_completed_normally = True
            dialog.set_completed(len(run_points))
            dialog.finish("Measurement run complete.")

        worker.progress.connect(on_progress)
        worker.point_started.connect(on_point_started)
        worker.point_result.connect(on_point_result)
        worker.pause_state.connect(on_pause_state)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.run_completed.connect(on_completed)
        worker.finished.connect(_finish_execution_ui)

        pause_button.clicked.connect(toggle_pause)
        abort_button.clicked.connect(request_abort)
        dialog.pause_button.clicked.connect(toggle_pause)
        dialog.abort_button.clicked.connect(request_abort)

        dialog.show()
        worker.start()

    build_button.clicked.connect(build_plan)
    validate_button.clicked.connect(validate_plan)
    start_button.clicked.connect(start_measurement_run)

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
    window.measurement_worker = None
    window.measurement_progress_dialog = None
    window.measurement_results = []

    return page
