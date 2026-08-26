"""Profile-driven ICAO obstacle-light workflow for Lumigon Measurement.

Selecting an Aviation / Obstacle Light profile should configure the angular
scan and acquisition basis instead of merely changing a label.  This module
keeps those workflow defaults in one place for LIOL, MIOL and HIOL families.

The profile workflow is intentionally separate from family-specific compliance
analysis.  MIOL compliance already exists; LIOL/HIOL Results checks can be
added incrementally without changing the profile-selection contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel

from phamp_mb7 import PhAmpMB7


@dataclass(frozen=True)
class ObstacleProfileWorkflow:
    key: str
    family: str
    type_code: str
    distribution_table: str
    colour: str
    signal: str
    intensity_basis: str
    benchmark: str
    elevation_start_deg: float
    elevation_end_deg: float
    step_deg: float
    key_angles: str
    note: str
    flashing: bool
    capture_duration_s: float = 4.2


# ICAO elevation is positive upward. Lumigon Gamma positive is downward, so
# Gamma command = -ICAO elevation.  The selected ranges below are practical
# characterization ranges that include the tabulated checkpoints/beam-spread
# region. LIOL's full Annex distribution extends to +90° elevation; with the
# present Gamma ±60° mechanical envelope that part is necessarily only partial.
OBSTACLE_PROFILE_WORKFLOWS = {
    "LIOL-A": ObstacleProfileWorkflow(
        "LIOL-A", "LIOL", "A", "Table 6-2", "Red", "Fixed",
        "Steady luminous intensity",
        "≥10 cd between +2° and +10°; beam spread ≥10° at ≥5 cd",
        -3.0, 20.0, 0.5,
        "+2°…+10°; beam threshold 5 cd",
        "Full Annex vertical-distribution check continues to +90° elevation; current Lumigon Gamma envelope cannot cover +90°.",
        False,
    ),
    "LIOL-B": ObstacleProfileWorkflow(
        "LIOL-B", "LIOL", "B", "Table 6-2", "Red", "Fixed",
        "Steady luminous intensity",
        "≥32 cd between +2° and +10°; beam spread ≥10° at ≥16 cd",
        -3.0, 20.0, 0.5,
        "+2°…+10°; beam threshold 16 cd",
        "Full Annex vertical-distribution check continues to +90° elevation; current Lumigon Gamma envelope cannot cover +90°.",
        False,
    ),
    "LIOL-C": ObstacleProfileWorkflow(
        "LIOL-C", "LIOL", "C", "Table 6-2", "Yellow / Blue", "Flashing 60–90 fpm",
        "I-effective (Blondel-Rey)",
        "≥40 cd between +2° and +10°; ≤400 cd; beam spread ≥12° at ≥20 cd",
        -3.0, 20.0, 0.5,
        "Peak approximately +2.5°; beam threshold 20 cd",
        "Temporal effective intensity is captured at every stationary angular point.",
        True, 2.2,
    ),
    "LIOL-D": ObstacleProfileWorkflow(
        "LIOL-D", "LIOL", "D", "Table 6-2", "Yellow", "Flashing 60–90 fpm",
        "I-effective (Blondel-Rey)",
        "≥200 cd between +2° and +20°; ≤400 cd",
        -3.0, 30.0, 0.5,
        "Peak approximately +17°",
        "The wider scan range is used to capture the approximately +17° peak location.",
        True, 2.2,
    ),
    "LIOL-E": ObstacleProfileWorkflow(
        "LIOL-E", "LIOL", "E", "Table 6-2 (Type B distribution)", "Red", "Flashing",
        "I-effective (Blondel-Rey)",
        "Type B distribution: ≥32 cd between +2° and +10°; beam spread ≥10° at ≥16 cd",
        -3.0, 20.0, 0.5,
        "+2°…+10°; beam threshold 16 cd",
        "Wind-turbine Type E uses the Type B light-distribution requirement.",
        True, 4.2,
    ),
    "MIOL TYPE A": ObstacleProfileWorkflow(
        "MIOL Type A", "MIOL", "A", "Table 6-3", "White", "Flashing 20–60 fpm",
        "I-effective (Blondel-Rey)",
        "20,000 cd Day/Twilight; 2,000 cd Night",
        -10.0, 10.0, 0.5,
        "0°, −1°, −10°; minimum beam spread 3°",
        "Stationary temporal capture at every angular point; operating condition selects the benchmark.",
        True, 4.2,
    ),
    "MIOL TYPE B": ObstacleProfileWorkflow(
        "MIOL Type B", "MIOL", "B", "Table 6-3", "Red", "Flashing 20–60 fpm",
        "I-effective (Blondel-Rey)",
        "2,000 cd Night",
        -10.0, 10.0, 0.5,
        "0°, −1°, −10°; minimum beam spread 3°",
        "Stationary temporal capture at every angular point.",
        True, 4.2,
    ),
    "MIOL TYPE C": ObstacleProfileWorkflow(
        "MIOL Type C", "MIOL", "C", "Table 6-3", "Red", "Fixed",
        "Steady luminous intensity",
        "2,000 cd Night",
        -10.0, 10.0, 0.5,
        "0°, −1°, −10°; minimum beam spread 3°",
        "Fixed-light photometry; no temporal I-effective capture required.",
        False,
    ),
    "HIOL-A": ObstacleProfileWorkflow(
        "HIOL-A", "HIOL", "A", "Table 6-3", "White", "Flashing 40–60 fpm",
        "I-effective (Blondel-Rey)",
        "200,000 cd Day; 20,000 cd Twilight; 2,000 cd Night",
        -10.0, 10.0, 0.5,
        "0°, −1°, −10°; minimum beam spread 3°",
        "Installation peak setting angle is separately determined by installation height (ICAO Table 6-2).",
        True, 3.2,
    ),
    "HIOL-B": ObstacleProfileWorkflow(
        "HIOL-B", "HIOL", "B", "Table 6-3", "White", "Flashing 40–60 fpm",
        "I-effective (Blondel-Rey)",
        "100,000 cd Day; 20,000 cd Twilight; 2,000 cd Night",
        -10.0, 10.0, 0.5,
        "0°, −1°, −10°; minimum beam spread 3°",
        "Installation peak setting angle is separately determined by installation height (ICAO Table 6-2).",
        True, 3.2,
    ),
}


def workflow_from_profile_text(text: str) -> Optional[ObstacleProfileWorkflow]:
    upper = str(text or "").upper()
    for key, workflow in OBSTACLE_PROFILE_WORKFLOWS.items():
        if key in upper:
            return workflow
    return None


def attach_obstacle_profile_workflow(window):
    """Show and apply the selected ICAO obstacle-light profile workflow."""

    if getattr(window, "measurement_obstacle_workflow_box", None) is not None:
        return window.measurement_obstacle_workflow_box

    profile_combo = getattr(window, "measurement_profile_combo", None)
    application_combo = getattr(window, "measurement_application_combo", None)
    product_combo = getattr(window, "measurement_product_combo", None)
    workspace = getattr(window, "measurement_workspace", None)
    if any(x is None for x in (profile_combo, application_combo, product_combo, workspace)):
        raise RuntimeError("Measurement profile controls are not ready for obstacle workflow integration.")

    box = QGroupBox("ICAO Obstacle Light Profile Workflow")
    form = QFormLayout(box)
    form.setContentsMargins(10, 8, 10, 8)
    form.setSpacing(6)

    family_label = QLabel("—")
    distribution_label = QLabel("—")
    signal_label = QLabel("—")
    benchmark_label = QLabel("—")
    basis_label = QLabel("—")
    scan_label = QLabel("—")
    checkpoints_label = QLabel("—")
    note_label = QLabel("—")
    for label in (benchmark_label, scan_label, checkpoints_label, note_label):
        label.setWordWrap(True)
    note_label.setStyleSheet("color: #8AA8BC;")

    form.addRow("Family / Type:", family_label)
    form.addRow("ICAO distribution:", distribution_label)
    form.addRow("Signal:", signal_label)
    form.addRow("Benchmark / limits:", benchmark_label)
    form.addRow("Intensity basis:", basis_label)
    form.addRow("Applied angular scan:", scan_label)
    form.addRow("Key ICAO angles:", checkpoints_label)
    form.addRow("", note_label)

    layout = workspace.layout()
    # Keep this immediately below the Test Definition / Angular Scan / Acquisition
    # cards. Family-specific MIOL controls may follow it.
    layout.insertWidget(min(2, layout.count()), box)

    window.measurement_obstacle_workflow_box = box
    window.measurement_obstacle_workflow_scan_label = scan_label

    syncing = False

    def set_value(name, value):
        control = getattr(window, name, None)
        if control is not None:
            control.setValue(value)

    def apply_workflow(*_args):
        nonlocal syncing
        if syncing:
            return

        is_obstacle = (
            application_combo.currentText() == "Aviation"
            and product_combo.currentText() == "Obstacle Light"
        )
        workflow = workflow_from_profile_text(profile_combo.currentText()) if is_obstacle else None
        box.setVisible(workflow is not None)
        if workflow is None:
            return

        syncing = True
        try:
            scan_mode = getattr(window, "measurement_scan_mode_combo", None)
            if scan_mode is not None:
                scan_mode.setCurrentIndex(0)  # C fixed / Gamma sweep

            # ICAO elevation = -Gamma.
            gamma_start = -workflow.elevation_end_deg
            gamma_end = -workflow.elevation_start_deg
            set_value("measurement_c_start", 0.0)
            set_value("measurement_c_end", 0.0)
            set_value("measurement_gamma_start", gamma_start)
            set_value("measurement_gamma_end", gamma_end)
            set_value("measurement_gamma_step", workflow.step_deg)

            family_label.setText(f"{workflow.family} Type {workflow.type_code}")
            distribution_label.setText(f"ICAO Annex 14 • {workflow.distribution_table}")
            signal_label.setText(f"{workflow.colour} • {workflow.signal}")
            benchmark_label.setText(workflow.benchmark)
            basis_label.setText(workflow.intensity_basis)
            scan_label.setText(
                f"ICAO elevation {workflow.elevation_start_deg:+g}° → {workflow.elevation_end_deg:+g}° "
                f"at {workflow.step_deg:g}° steps  •  Lumigon Gamma {gamma_start:+g}° → {gamma_end:+g}°  •  C = 0°"
            )
            checkpoints_label.setText(workflow.key_angles)
            note_label.setText(workflow.note)

            # All flashing obstacle-light families use effective intensity.
            PhAmpMB7._lumigon_miol_flash_enabled = workflow.flashing
            PhAmpMB7._lumigon_miol_capture_duration_s = workflow.capture_duration_s

            integration = getattr(window, "measurement_integration_spin", None)
            samples = getattr(window, "measurement_samples_spin", None)
            capture = getattr(window, "measurement_miol_capture_spin", None)
            if workflow.flashing:
                if integration is not None:
                    integration.setValue(10)
                if samples is not None:
                    samples.setValue(1)
                if capture is not None:
                    capture.setValue(workflow.capture_duration_s)
            else:
                if integration is not None:
                    integration.setValue(100)
                if samples is not None:
                    samples.setValue(5)
        finally:
            syncing = False

    application_combo.currentIndexChanged.connect(apply_workflow)
    product_combo.currentIndexChanged.connect(apply_workflow)
    profile_combo.currentIndexChanged.connect(apply_workflow)
    profile_combo.currentTextChanged.connect(apply_workflow)

    apply_workflow()
    return box
