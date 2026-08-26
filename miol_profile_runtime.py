"""Runtime UI and acquisition integration for ICAO Annex 14 MIOL profiles."""

from __future__ import annotations

import statistics
import time

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
)

from miol_icao import (
    ICAO_REFERENCE,
    MIOL_PROFILES,
    benchmark_for,
    blondel_rey_effective,
    intensity_basis_for,
    profile_type_from_text,
)
from phamp_mb7 import LuxReading, PhAmpMB7
from test_plan_workspace import TestPlanWorkspace


MIOL_CAPTURE_INTEGRATION_MS = 10
MIOL_CAPTURE_DURATION_DEFAULT_S = 4.2


def _capture_effective_lux(meter: PhAmpMB7) -> LuxReading:
    """Capture one flashing MIOL waveform and return Blondel-Rey effective Lux."""

    capture_s = max(
        1.0,
        float(getattr(
            PhAmpMB7,
            "_lumigon_miol_capture_duration_s",
            MIOL_CAPTURE_DURATION_DEFAULT_S,
        )),
    )
    previous_integration = int(meter.integration_time_ms)
    times: list[float] = []
    lux_values: list[float] = []

    try:
        if meter.integration_time_ms != MIOL_CAPTURE_INTEGRATION_MS:
            meter.set_integration_time(MIOL_CAPTURE_INTEGRATION_MS)
        meter.set_internal_trigger()
        time.sleep((MIOL_CAPTURE_INTEGRATION_MS + 10) / 1000.0)

        started = time.monotonic()
        deadline = started + capture_s
        while time.monotonic() < deadline:
            current_a = meter.read_current()
            now = time.monotonic()
            times.append(now - started)
            lux_values.append(meter.current_to_lux(current_a))
            # Do not hammer M? faster than the continuous 10 ms integration.
            time.sleep(0.004)

        if len(times) < 8:
            raise RuntimeError(
                "MIOL flash capture returned too few temporal samples. "
                "Check the Ph-Amp serial link and retry."
            )

        effective = blondel_rey_effective(
            times,
            lux_values,
            subtract_baseline=True,
        )
        effective_lux = float(effective.effective_value)
        effective_current_a = effective_lux * meter.sensitivity_a_per_lx

        sample_intervals = [b - a for a, b in zip(times, times[1:]) if b > a]
        meter.last_miol_capture = {
            "effective_lux": effective_lux,
            "peak_lux_net": effective.peak_value,
            "baseline_lux": effective.baseline_value,
            "effective_interval_s": effective.interval_duration_s,
            "samples": effective.sample_count,
            "capture_duration_s": (
                times[-1] - times[0] if len(times) > 1 else 0.0
            ),
            "median_sample_interval_ms": (
                1000.0 * statistics.median(sample_intervals)
                if sample_intervals
                else None
            ),
        }

        return LuxReading(
            lux=effective_lux,
            mean_current_a=effective_current_a,
            samples=effective.sample_count,
            # Temporal flash variation is intentional, not measurement scatter.
            stdev_lux=0.0,
        )
    finally:
        restore_errors = []
        try:
            meter.set_software_trigger()
        except Exception as exc:
            restore_errors.append(f"T1 restore: {exc}")
        if previous_integration != meter.integration_time_ms:
            try:
                meter.set_integration_time(previous_integration)
            except Exception as exc:
                restore_errors.append(f"integration restore: {exc}")
        if restore_errors:
            meter.last_miol_restore_warning = "; ".join(restore_errors)


def install_miol_flash_acquisition():
    """Return I-effective from PhAmpMB7.read_lux while flashing MIOL is active."""

    if getattr(PhAmpMB7, "_lumigon_miol_patch_installed", False):
        return
    PhAmpMB7._lumigon_miol_patch_installed = True
    PhAmpMB7._lumigon_miol_flash_enabled = False
    PhAmpMB7._lumigon_miol_capture_duration_s = MIOL_CAPTURE_DURATION_DEFAULT_S

    original_read_lux = PhAmpMB7.read_lux

    def patched_read_lux(self, samples=5, sample_delay_s=0.05):
        if not bool(getattr(PhAmpMB7, "_lumigon_miol_flash_enabled", False)):
            return original_read_lux(
                self,
                samples=samples,
                sample_delay_s=sample_delay_s,
            )
        return _capture_effective_lux(self)

    PhAmpMB7.read_lux = patched_read_lux


def _profile_code(window):
    combo = getattr(window, "measurement_profile_combo", None)
    if combo is None:
        return None
    return profile_type_from_text(combo.currentText())


def attach_miol_profile_runtime(window):
    """Replace the development MIOL placeholder with Annex 14 A/B/C profiles."""

    install_miol_flash_acquisition()

    profile_combo = getattr(window, "measurement_profile_combo", None)
    standard_edit = getattr(window, "measurement_standard_edit", None)
    workspace = getattr(window, "measurement_workspace", None)
    if profile_combo is None or standard_edit is None or workspace is None:
        raise RuntimeError(
            "Measurement workspace is not ready for MIOL profile integration."
        )
    if getattr(window, "measurement_miol_profile_box", None) is not None:
        return window.measurement_miol_profile_box

    previous = profile_combo.currentText()
    profile_combo.blockSignals(True)
    profile_combo.clear()
    profile_combo.addItems([
        "MIOL Type A — ICAO Annex 14",
        "MIOL Type B — ICAO Annex 14",
        "MIOL Type C — ICAO Annex 14",
        "Custom Photometric Scan",
    ])
    if "CUSTOM" in previous.upper():
        profile_combo.setCurrentIndex(3)
    else:
        # Migration from the historical development profile: default to
        # flashing-red Type B so I-effective acquisition is exercised.
        profile_combo.setCurrentIndex(1)
    profile_combo.blockSignals(False)

    box = QGroupBox("ICAO MIOL Profile")
    form = QFormLayout(box)
    form.setContentsMargins(10, 8, 10, 8)
    form.setSpacing(7)

    condition_combo = QComboBox()
    signal_label = QLabel("—")
    benchmark_label = QLabel("—")
    basis_label = QLabel("—")
    capture_spin = QDoubleSpinBox()
    capture_spin.setRange(3.2, 10.0)
    capture_spin.setDecimals(1)
    capture_spin.setSingleStep(0.5)
    capture_spin.setSuffix(" s")
    capture_spin.setValue(MIOL_CAPTURE_DURATION_DEFAULT_S)
    capture_spin.setToolTip(
        "Temporal capture per angular point for flashing Types A/B. "
        "4.2 s covers at least one complete interval at the minimum 20 fpm rate."
    )

    mapping_label = QLabel(
        "Lumigon Gamma + is downward; ICAO elevation = −Gamma. "
        "Default MIOL scan: Gamma −10°…+10° at 0.5° steps."
    )
    mapping_label.setWordWrap(True)
    mapping_label.setStyleSheet("color: #8AA8BC;")

    form.addRow("Operating condition:", condition_combo)
    form.addRow("Signal:", signal_label)
    form.addRow("ICAO benchmark:", benchmark_label)
    form.addRow("Intensity basis:", basis_label)
    form.addRow("Flash capture / point:", capture_spin)
    form.addRow("", mapping_label)

    layout = workspace.layout()
    # Title row and three-card settings row precede the Test Plan preview.
    layout.insertWidget(min(2, layout.count()), box)

    window.measurement_miol_profile_box = box
    window.measurement_miol_condition_combo = condition_combo
    window.measurement_miol_capture_spin = capture_spin
    window.measurement_miol_signal_label = signal_label
    window.measurement_miol_benchmark_label = benchmark_label
    window.measurement_miol_basis_label = basis_label

    def sync_meter_mode():
        code = _profile_code(window)
        flashing = bool(code and MIOL_PROFILES[code].flashing)
        PhAmpMB7._lumigon_miol_flash_enabled = flashing
        PhAmpMB7._lumigon_miol_capture_duration_s = capture_spin.value()
        meter = getattr(window, "luxmeter", None)
        if meter is not None:
            meter.last_miol_capture = None

    def set_miol_defaults(code):
        scan_mode = getattr(window, "measurement_scan_mode_combo", None)
        c_start = getattr(window, "measurement_c_start", None)
        c_end = getattr(window, "measurement_c_end", None)
        gamma_start = getattr(window, "measurement_gamma_start", None)
        gamma_end = getattr(window, "measurement_gamma_end", None)
        gamma_step = getattr(window, "measurement_gamma_step", None)
        integration = getattr(window, "measurement_integration_spin", None)
        samples = getattr(window, "measurement_samples_spin", None)

        if scan_mode is not None:
            scan_mode.setCurrentIndex(0)  # C fixed / Gamma sweep
        if c_start is not None:
            c_start.setValue(0.0)
        if c_end is not None:
            c_end.setValue(0.0)
        if gamma_start is not None:
            gamma_start.setValue(-10.0)
        if gamma_end is not None:
            gamma_end.setValue(10.0)
        if gamma_step is not None:
            gamma_step.setValue(0.5)
        if integration is not None:
            integration.setValue(
                MIOL_CAPTURE_INTEGRATION_MS
                if MIOL_PROFILES[code].flashing
                else 100
            )
        if samples is not None:
            samples.setValue(1 if MIOL_PROFILES[code].flashing else 5)

    def refresh_profile(*_args, apply_defaults=False):
        code = _profile_code(window)
        is_miol = code is not None
        box.setVisible(is_miol)

        if not is_miol:
            standard_edit.setText(
                "Custom photometric scan — no compliance profile assigned"
            )
            PhAmpMB7._lumigon_miol_flash_enabled = False
            continuous_mode = getattr(
                window,
                "measurement_continuous_mode_button",
                None,
            )
            if continuous_mode is not None:
                continuous_mode.setEnabled(True)
                continuous_mode.setToolTip("")
            return

        spec = MIOL_PROFILES[code]
        old_condition = condition_combo.currentText()
        condition_combo.blockSignals(True)
        condition_combo.clear()
        condition_combo.addItems(list(spec.allowed_conditions))
        if old_condition in spec.allowed_conditions:
            condition_combo.setCurrentText(old_condition)
        elif code == "A":
            condition_combo.setCurrentText("Day")
        else:
            condition_combo.setCurrentText("Night")
        condition_combo.blockSignals(False)

        condition = condition_combo.currentText()
        benchmark = benchmark_for(code, condition)
        signal = (
            f"{spec.colour} • Flashing "
            f"{spec.flash_rate_min_fpm:.0f}–{spec.flash_rate_max_fpm:.0f} fpm"
            if spec.flashing
            else f"{spec.colour} • Fixed"
        )
        signal_label.setText(signal)
        benchmark_label.setText(f"{benchmark.nominal_cd:,.0f} cd")
        basis_label.setText(intensity_basis_for(code))
        capture_spin.setEnabled(spec.flashing)
        standard_edit.setText(
            f"{ICAO_REFERENCE} | Condition: {condition} | "
            f"Intensity: {intensity_basis_for(code)}"
        )

        if apply_defaults:
            set_miol_defaults(code)

        # Annex 14 flashing-light checks need a stationary waveform capture at
        # each angle, therefore MIOL runs use Step Scan rather than fly scan.
        step_mode = getattr(window, "measurement_step_mode_button", None)
        continuous_mode = getattr(
            window,
            "measurement_continuous_mode_button",
            None,
        )
        continuous_start = getattr(
            window,
            "measurement_continuous_start_button",
            None,
        )
        if continuous_mode is not None:
            continuous_mode.setEnabled(False)
            continuous_mode.setToolTip(
                "ICAO MIOL uses stationary Step Scan so I-effective can be "
                "captured at each angle."
            )
        if continuous_start is not None:
            continuous_start.setEnabled(False)
        if step_mode is not None and not step_mode.isChecked():
            step_mode.click()

        sync_meter_mode()

    def profile_changed(*_args):
        refresh_profile(apply_defaults=True)

    def condition_changed(*_args):
        refresh_profile(apply_defaults=False)

    profile_combo.currentIndexChanged.connect(profile_changed)
    condition_combo.currentIndexChanged.connect(condition_changed)
    capture_spin.valueChanged.connect(lambda *_: sync_meter_mode())

    # Add temporal flash capture to Step ETA so the displayed countdown includes
    # the dominant per-point acquisition time for Types A/B.
    if not getattr(TestPlanWorkspace, "_lumigon_miol_eta_patch", False):
        TestPlanWorkspace._lumigon_miol_eta_patch = True
        original_step_estimate = TestPlanWorkspace._step_estimate_seconds

        def miol_step_estimate(self, point_count, motion_only=False):
            estimate = original_step_estimate(self, point_count, motion_only)
            code = _profile_code(self.host_window)
            if (
                not motion_only
                and code is not None
                and MIOL_PROFILES[code].flashing
            ):
                duration = getattr(
                    self.host_window,
                    "measurement_miol_capture_spin",
                    None,
                )
                capture_s = (
                    duration.value()
                    if duration is not None
                    else MIOL_CAPTURE_DURATION_DEFAULT_S
                )
                estimate += float(point_count) * float(capture_s)
            return estimate

        TestPlanWorkspace._step_estimate_seconds = miol_step_estimate

    refresh_profile(apply_defaults=True)
    return box
