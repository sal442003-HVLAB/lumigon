"""Detached Test Plan review/run workspace for Lumigon.

This module is deliberately UI-only.  It reuses the existing Measurement page
Test Plan table and execution controls, so Step Scan and Continuous Scan keep
using the same table, buttons, workers and result storage that already exist.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


SCAN_SINGLE_C_GAMMA = 0
SCAN_SINGLE_GAMMA_C = 1
SCAN_GRID = 2


class TestPlanWorkspace(QMainWindow):
    """Maximized review workspace backed by the existing Measurement plan."""

    def __init__(
        self,
        host_window,
        plan_table,
        execution_box,
        build_button,
        validate_button,
    ):
        super().__init__(host_window)
        self.host_window = host_window
        self.plan_table = plan_table
        self.execution_box = execution_box
        self.build_button = build_button
        self.validate_button = validate_button

        self.setWindowTitle("Lumigon — Test Plan Workspace")
        self.setWindowFlag(Qt.Window, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.resize(1400, 820)

        central = QWidget(self)
        central.setObjectName("testPlanWorkspace")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # --------------------------------------------------------------
        # Header
        # --------------------------------------------------------------
        header = QHBoxLayout()
        header.setSpacing(12)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        title = QLabel("Test Plan Workspace")
        title.setObjectName("testPlanWorkspaceTitle")
        subtitle = QLabel(
            "Full-size review and run view — uses the active Measurement plan and engine"
        )
        subtitle.setObjectName("testPlanWorkspaceSubtitle")

        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        header.addLayout(title_block, 1)

        self.state_label = QLabel("DRAFT")
        self.state_label.setObjectName("testPlanWorkspaceState")
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setMinimumWidth(230)
        header.addWidget(self.state_label, 0, Qt.AlignVCenter)

        close_button = QPushButton("Close")
        close_button.setObjectName("secondaryActionButton")
        close_button.clicked.connect(self.close)
        header.addWidget(close_button, 0, Qt.AlignVCenter)

        root.addLayout(header)

        # --------------------------------------------------------------
        # Read-only context summary
        # --------------------------------------------------------------
        context_box = QGroupBox("Plan Context")
        context_box.setObjectName("testPlanContextBox")
        context = QGridLayout(context_box)
        context.setContentsMargins(12, 10, 12, 10)
        context.setHorizontalSpacing(18)
        context.setVerticalSpacing(6)

        self.identity_label = QLabel("—")
        self.identity_label.setWordWrap(True)
        self.scan_label = QLabel("—")
        self.scan_label.setWordWrap(True)
        self.acquisition_label = QLabel("—")
        self.acquisition_label.setWordWrap(True)
        self.progress_label = QLabel("—")
        self.progress_label.setWordWrap(True)

        context.addWidget(QLabel("Test:"), 0, 0)
        context.addWidget(self.identity_label, 0, 1)
        context.addWidget(QLabel("Angular scan:"), 1, 0)
        context.addWidget(self.scan_label, 1, 1)
        context.addWidget(QLabel("Acquisition:"), 0, 2)
        context.addWidget(self.acquisition_label, 0, 3)
        context.addWidget(QLabel("Plan status:"), 1, 2)
        context.addWidget(self.progress_label, 1, 3)
        context.setColumnStretch(1, 3)
        context.setColumnStretch(3, 2)

        root.addWidget(context_box)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        section_title = QLabel("Test Plan")
        section_title.setObjectName("measurementSectionTitle")
        toolbar.addWidget(section_title)
        toolbar.addStretch(1)

        rebuild_button = QPushButton("Build / Rebuild Plan")
        revalidate_button = QPushButton("Validate Plan")
        rebuild_button.clicked.connect(self.build_button.click)
        revalidate_button.clicked.connect(self.validate_button.click)
        toolbar.addWidget(rebuild_button)
        toolbar.addWidget(revalidate_button)
        root.addLayout(toolbar)

        # This is the exact same table object used by both measurement engines.
        self.plan_table.setParent(central)
        self.plan_table.setMinimumHeight(420)
        root.addWidget(self.plan_table, 1)

        # Reuse the existing Execution group and its already-connected buttons.
        self.execution_box.setParent(central)
        root.addWidget(self.execution_box, 0)

        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(200)
        self.sync_timer.timeout.connect(self.refresh_summary)
        self.sync_timer.start()

        self.setStyleSheet(
            host_window.styleSheet()
            + """
            QMainWindow {
                background-color: #101820;
            }
            QWidget#testPlanWorkspace {
                background-color: #101820;
            }
            QLabel#testPlanWorkspaceTitle {
                color: #E9F3FA;
                font-size: 19pt;
                font-weight: 700;
            }
            QLabel#testPlanWorkspaceSubtitle {
                color: #7F98AA;
                padding-bottom: 2px;
            }
            QLabel#testPlanWorkspaceState {
                border-radius: 12px;
                padding: 7px 12px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QGroupBox#testPlanContextBox QLabel {
                color: #B8CAD6;
            }
            """
        )

        self.refresh_summary()

    def _execution_mode_text(self):
        continuous = getattr(self.host_window, "measurement_continuous_mode_button", None)
        if continuous is not None and continuous.isChecked():
            return "Continuous Scan"
        return "Step Scan"

    def _scan_text(self):
        mode_combo = self.host_window.measurement_scan_mode_combo
        mode = mode_combo.currentIndex()

        c_start = self.host_window.measurement_c_start.value()
        c_end = self.host_window.measurement_c_end.value()
        c_step = self.host_window.measurement_c_step.value()
        gamma_start = self.host_window.measurement_gamma_start.value()
        gamma_end = self.host_window.measurement_gamma_end.value()
        gamma_step = self.host_window.measurement_gamma_step.value()

        if mode == SCAN_SINGLE_C_GAMMA:
            return (
                f"C {c_start:+.2f}° fixed  •  Gamma {gamma_start:+.2f}° → "
                f"{gamma_end:+.2f}°  •  step {gamma_step:g}°"
            )
        if mode == SCAN_SINGLE_GAMMA_C:
            return (
                f"Gamma {gamma_start:+.2f}° fixed  •  C {c_start:+.2f}° → "
                f"{c_end:+.2f}°  •  step {c_step:g}°"
            )

        traversal = self.host_window.measurement_scan_order_combo.currentText()
        return (
            f"C {c_start:+.2f}° → {c_end:+.2f}° / {c_step:g}°  •  "
            f"Gamma {gamma_start:+.2f}° → {gamma_end:+.2f}° / {gamma_step:g}°  •  "
            f"{traversal}"
        )

    def _status_counts(self):
        counts = {}
        for row in range(self.plan_table.rowCount()):
            item = self.plan_table.item(row, 8)
            status = item.text().strip() if item is not None else "—"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _apply_state_style(self, text):
        upper = text.upper()
        if "INVALID" in upper:
            self.state_label.setStyleSheet(
                "color:#FFC9C9; background:#3A1F24; border:1px solid #9C3D49;"
            )
        elif "VALIDATED" in upper or "COMPLETE" in upper:
            self.state_label.setStyleSheet(
                "color:#BFE7C8; background:#173226; border:1px solid #2E7D4B;"
            )
        else:
            self.state_label.setStyleSheet(
                "color:#9DB4C4; background:#1B2934; border:1px solid #3B5365;"
            )

    def refresh_summary(self):
        window = self.host_window

        source_state = getattr(window, "measurement_state_label", None)
        state_text = source_state.text() if source_state is not None else "DRAFT"
        self.state_label.setText(state_text)
        self._apply_state_style(state_text)

        application = window.measurement_application_combo.currentText()
        product = window.measurement_product_combo.currentText()
        profile = window.measurement_profile_combo.currentText()
        sample = window.measurement_sample_id_edit.text().strip() or "Sample ID not set"
        self.identity_label.setText(
            f"{application}  /  {product}  /  {profile}  •  {sample}"
        )

        self.scan_label.setText(self._scan_text())

        distance = window.measurement_distance_spin.value()
        integration = window.measurement_integration_spin.value()
        settle = window.measurement_settle_spin.value()
        samples = window.measurement_samples_spin.value()
        execution = self._execution_mode_text()
        self.acquisition_label.setText(
            f"{execution}  •  distance {distance:.2f} m  •  integration {integration} ms  •  "
            f"settle {settle:.1f} s  •  {samples} sample(s)/point"
        )

        counts = self._status_counts()
        total = self.plan_table.rowCount()
        measured = counts.get("Measured", 0)
        ready = counts.get("Ready", 0)
        running = counts.get("Running", 0)
        pending = counts.get("Pending", 0)
        self.progress_label.setText(
            f"{total} points  •  {measured} measured  •  {ready} ready  •  "
            f"{running} running  •  {pending} pending"
        )

    def open_maximized(self):
        self.refresh_summary()
        self.showMaximized()
        self.raise_()
        self.activateWindow()

    def _measurement_is_running(self):
        step_worker = getattr(self.host_window, "measurement_worker", None)
        continuous_worker = getattr(
            self.host_window,
            "continuous_measurement_worker",
            None,
        )
        return bool(
            (step_worker is not None and step_worker.isRunning())
            or (continuous_worker is not None and continuous_worker.isRunning())
        )

    def closeEvent(self, event):
        if self._measurement_is_running():
            QMessageBox.warning(
                self,
                "Measurement Running",
                "The Test Plan Workspace stays open while a measurement is running. "
                "Pause or abort the run before closing this window.",
            )
            event.ignore()
            return
        super().closeEvent(event)


def _detach_plan_header(root, plan_table, page):
    """Remove the old preview header and return its useful widgets."""

    table_index = root.indexOf(plan_table)
    if table_index <= 0:
        raise RuntimeError("Could not locate the Test Plan header in Measurement layout.")

    header_item = root.takeAt(table_index - 1)
    header_layout = header_item.layout()
    if header_layout is None:
        raise RuntimeError("Measurement Test Plan header layout is not available.")

    widgets = []
    while header_layout.count():
        item = header_layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(page)
            widgets.append(widget)

    header_layout.deleteLater()
    return widgets


def attach_test_plan_workspace(window):
    """Replace the embedded plan table with a compact summary + Open button."""

    if getattr(window, "test_plan_workspace", None) is not None:
        return

    page = getattr(window, "measurement_workspace", None)
    plan_table = getattr(window, "measurement_plan_table", None)
    build_button = getattr(window, "measurement_build_plan_button", None)
    validate_button = getattr(window, "measurement_validate_plan_button", None)
    start_button = getattr(window, "measurement_start_button", None)

    if any(
        item is None
        for item in (page, plan_table, build_button, validate_button, start_button)
    ):
        raise RuntimeError("Measurement workspace is incomplete.")

    root = page.layout()
    if root is None:
        raise RuntimeError("Measurement workspace layout is unavailable.")

    execution_box = start_button.parentWidget()
    if execution_box is None:
        raise RuntimeError("Measurement execution controls are unavailable.")

    header_widgets = _detach_plan_header(root, plan_table, page)
    old_plan_title = next(
        (
            widget
            for widget in header_widgets
            if isinstance(widget, QLabel) and widget.text().strip() == "Test Plan Preview"
        ),
        None,
    )
    if old_plan_title is not None:
        old_plan_title.hide()

    # The existing summary/build/validate widgets keep all of their current
    # callbacks. We only place them into a cleaner compact card.
    plan_summary = getattr(window, "measurement_plan_summary_label", None)
    if plan_summary is None:
        raise RuntimeError("Measurement plan summary label is unavailable.")

    root.removeWidget(plan_table)
    root.removeWidget(execution_box)

    summary_box = QGroupBox("Test Plan")
    summary_box.setObjectName("measurementPlanSummaryBox")
    summary_layout = QHBoxLayout(summary_box)
    summary_layout.setContentsMargins(12, 10, 12, 10)
    summary_layout.setSpacing(10)

    text_block = QVBoxLayout()
    text_block.setSpacing(3)

    plan_summary.setParent(summary_box)
    plan_summary.setStyleSheet("color: #A9C4D5; padding: 0px;")
    text_block.addWidget(plan_summary)

    helper = QLabel(
        "Review the full point table in the maximized workspace. The same plan is used for execution and live result updates."
    )
    helper.setObjectName("measurementEngineNote")
    helper.setWordWrap(True)
    text_block.addWidget(helper)
    summary_layout.addLayout(text_block, 1)

    build_button.setParent(summary_box)
    validate_button.setParent(summary_box)
    open_button = QPushButton("Open Test Plan")
    open_button.setObjectName("openTestPlanButton")

    summary_layout.addWidget(build_button)
    summary_layout.addWidget(validate_button)
    summary_layout.addWidget(open_button)

    root.addWidget(summary_box, 0)
    root.addStretch(1)

    workspace = TestPlanWorkspace(
        host_window=window,
        plan_table=plan_table,
        execution_box=execution_box,
        build_button=build_button,
        validate_button=validate_button,
    )
    open_button.clicked.connect(workspace.open_maximized)

    window.test_plan_workspace = workspace
    window.measurement_plan_summary_box = summary_box
    window.measurement_open_test_plan_button = open_button
