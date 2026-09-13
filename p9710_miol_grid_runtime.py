"""P-9710 MIOL full-grid acquisition for Lumigon Measurement.

Validated pilot behaviour is extended to a full local C x Gamma scan:
- C: -45 deg .. +45 deg, 0.5 deg resolution
- Gamma: -10 deg .. +10 deg, 0.5 deg resolution
- Type A/B: adaptive rising-edge detection + fixed-range Schmidt-Clausen MI
- Type C: CW with simple adaptive range recovery
- every completed point is flushed immediately to CSV
"""

from __future__ import annotations

import csv
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from machine_config import C_LIMIT_DEG, GAMMA_LIMIT_DEG
from miol_icao import MIOL_PROFILES, icao_elevation_from_gamma, profile_type_from_text
from motion_controller import C_AXIS, GAMMA


DEFAULT_C_START_DEG = -45.0
DEFAULT_C_END_DEG = 45.0
DEFAULT_C_STEP_DEG = 0.5
DEFAULT_GAMMA_START_DEG = -10.0
DEFAULT_GAMMA_END_DEG = 10.0
DEFAULT_GAMMA_STEP_DEG = 0.5
DEFAULT_DISTANCE_M = 5.17

DEFAULT_RANGE = 5
DEFAULT_PERIOD_S = 3.170
DEFAULT_PRETRIGGER_MS = 100
DEFAULT_WINDOW_MS = 600
DEFAULT_SC_C_S = 0.2
DEFAULT_CW_INTEGRATION_MS = 0.1
ANGLE_TOLERANCE_DEG = 0.05
GP_LOW_PCT = 15.0
GP_HIGH_PCT = 85.0


def _axis_values(start: float, end: float, step: float):
    start = float(start)
    end = float(end)
    step = abs(float(step))
    if step <= 0.0:
        raise ValueError("Angular step must be greater than zero.")
    direction = 1.0 if end >= start else -1.0
    signed = direction * step
    values = []
    value = start
    epsilon = max(1e-9, step * 1e-6)
    if direction > 0:
        while value <= end + epsilon:
            values.append(round(value, 6))
            value += signed
    else:
        while value >= end - epsilon:
            values.append(round(value, 6))
            value += signed
    if values and abs(values[-1] - end) > epsilon:
        values.append(round(end, 6))
    return values


def _build_grid(c_start, c_end, c_step, gamma_start, gamma_end, gamma_step):
    c_values = _axis_values(c_start, c_end, c_step)
    gamma_values = _axis_values(gamma_start, gamma_end, gamma_step)
    return [(c, gamma) for c in c_values for gamma in gamma_values]


class P9710MIOLGridWorker(QThread):
    progress = Signal(str)
    point_started = Signal(int, int, float, float)
    point_result = Signal(object)
    completed = Signal(str)
    aborted = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        *,
        motion,
        meter,
        points,
        profile_code: str,
        distance_m: float,
        settle_time_s: float,
        range_id: int,
        period_s: float,
        pretrigger_ms: int,
        window_ms: int,
        sc_c_s: float,
        cw_integration_ms: float,
        output_path: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.motion = motion
        self.meter = meter
        self.points = [(float(c), float(g)) for c, g in points]
        self.profile_code = str(profile_code).upper()
        self.distance_m = float(distance_m)
        self.settle_time_s = max(0.0, float(settle_time_s))
        self.start_range_id = max(0, min(7, int(range_id)))
        self.next_range_id = self.start_range_id
        self.period_s = float(period_s)
        self.pretrigger_ms = int(pretrigger_ms)
        self.window_ms = int(window_ms)
        self.sc_c_s = float(sc_c_s)
        self.cw_integration_ms = float(cw_integration_ms)
        self.output_path = Path(output_path)

    def _wait_interruptible(self, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return False
            remaining = deadline - time.monotonic()
            self.msleep(max(1, min(50, int(remaining * 1000.0))))
        return not self.isInterruptionRequested()

    def _move_if_needed(self, axis, target: float):
        actual = float(self.motion.get_current_angle(axis))
        if abs(actual - target) <= ANGLE_TOLERANCE_DEG:
            return
        self.motion.move_absolute(axis, target)

    @staticmethod
    def _next_range(selected_range: int, gp_pct):
        selected_range = max(0, min(7, int(selected_range)))
        if gp_pct is None:
            return selected_range
        gp = float(gp_pct)
        if gp < GP_LOW_PCT and selected_range < 7:
            return selected_range + 1
        if gp > GP_HIGH_PCT and selected_range > 0:
            return selected_range - 1
        return selected_range

    def _read_cw_adaptive(self):
        range_id = self.next_range_id
        last_exc = None
        for _ in range(8):
            try:
                reading = self.meter.read_cw_snapshot(
                    integration_ms=self.cw_integration_ms,
                    range_id=range_id,
                    sync_enabled=False,
                )
                self.next_range_id = self._next_range(range_id, reading.range_utilization_pct)
                return {
                    "basis": "CW illuminance",
                    "e_lx": float(reading.cw_lx),
                    "gp_pct": reading.range_utilization_pct,
                    "trigger_lx": None,
                    "start_error_ms": None,
                    "range_id": range_id,
                }
            except Exception as exc:
                last_exc = exc
                text = str(exc)
                if "?32" in text and range_id < 7:
                    range_id += 1
                    continue
                if "?16" in text and range_id > 0:
                    range_id -= 1
                    continue
                raise
        raise RuntimeError(f"CW adaptive range selection failed: {last_exc}")

    def _read_point(self):
        spec = MIOL_PROFILES[self.profile_code]
        if not spec.flashing:
            return self._read_cw_adaptive()

        trigger_timeout_s = max(8.0, 2.5 * self.period_s)
        reading = self.meter.synchronized_effective_adaptive(
            period_s=self.period_s,
            pretrigger_ms=self.pretrigger_ms,
            window_ms=self.window_ms,
            start_range_id=self.next_range_id,
            c_s=self.sc_c_s,
            trigger_timeout_s=trigger_timeout_s,
        )
        self.next_range_id = self._next_range(
            reading.range_id,
            reading.range_utilization_pct,
        )
        return {
            "basis": "E-effective (Schmidt-Clausen)",
            "e_lx": float(reading.e_effective_lx),
            "gp_pct": reading.range_utilization_pct,
            "trigger_lx": float(reading.trigger_sample_lx),
            "start_error_ms": float(reading.software_start_error_ms),
            "range_id": int(reading.range_id),
        }

    def run(self):
        try:
            if self.profile_code not in MIOL_PROFILES:
                raise RuntimeError("Select an ICAO MIOL Type A, B or C profile.")
            if not self.points:
                raise RuntimeError("No C x Gamma points were generated.")
            if self.distance_m <= 0.0:
                raise RuntimeError("Measurement distance must be greater than zero.")

            self.output_path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = [
                "point", "timestamp", "profile", "basis", "C_deg", "Gamma_deg",
                "ICAO_elevation_deg", "E_lx", "I_cd", "GP_pct", "range_id",
                "next_range_id", "trigger_sample_lx", "software_start_error_ms",
                "distance_m",
            ]

            total = len(self.points)
            with self.output_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                handle.flush()

                for index, (c_deg, gamma_deg) in enumerate(self.points, start=1):
                    if self.isInterruptionRequested():
                        self.aborted.emit(
                            f"Stopped after {index - 1}/{total} points. Partial CSV was preserved."
                        )
                        return

                    self.point_started.emit(index, total, c_deg, gamma_deg)
                    self.progress.emit(
                        f"Point {index}/{total}: moving to C {c_deg:+.2f}°, Gamma {gamma_deg:+.2f}°"
                    )
                    self._move_if_needed(C_AXIS, c_deg)
                    if self.isInterruptionRequested():
                        self.aborted.emit("Stopped after C move. Partial CSV was preserved.")
                        return
                    self._move_if_needed(GAMMA, gamma_deg)

                    if not self._wait_interruptible(self.settle_time_s):
                        self.aborted.emit("Stopped during settling. Partial CSV was preserved.")
                        return

                    self.progress.emit(
                        f"Point {index}/{total}: acquiring P-9710 • start R{self.next_range_id}"
                    )
                    try:
                        measured = self._read_point()
                    except Exception as exc:
                        raise RuntimeError(
                            f"Acquisition failed at C={c_deg:+.3f}°, Gamma={gamma_deg:+.3f}°: {exc}"
                        ) from exc

                    e_lx = float(measured["e_lx"])
                    i_cd = e_lx * self.distance_m * self.distance_m
                    selected_range = int(measured["range_id"])
                    row = {
                        "point": index,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                        "profile": f"MIOL Type {self.profile_code}",
                        "basis": measured["basis"],
                        "C_deg": f"{c_deg:.3f}",
                        "Gamma_deg": f"{gamma_deg:.3f}",
                        "ICAO_elevation_deg": f"{icao_elevation_from_gamma(gamma_deg):.3f}",
                        "E_lx": f"{e_lx:.6f}",
                        "I_cd": f"{i_cd:.3f}",
                        "GP_pct": "" if measured["gp_pct"] is None else f"{float(measured['gp_pct']):.2f}",
                        "range_id": selected_range,
                        "next_range_id": self.next_range_id,
                        "trigger_sample_lx": "" if measured["trigger_lx"] is None else f"{float(measured['trigger_lx']):.6f}",
                        "software_start_error_ms": "" if measured["start_error_ms"] is None else f"{float(measured['start_error_ms']):.3f}",
                        "distance_m": f"{self.distance_m:.3f}",
                    }
                    writer.writerow(row)
                    handle.flush()
                    self.point_result.emit(row)

            self.progress.emit("Measurement complete — returning C to Home…")
            self.motion.return_to_zero(C_AXIS)
            self.progress.emit("Returning Gamma to Home…")
            self.motion.return_to_zero(GAMMA)
            self.completed.emit(str(self.output_path))

        except Exception as exc:
            self.failed.emit(str(exc))


def attach_p9710_miol_grid_runtime(window):
    if getattr(window, "p9710_miol_grid_box", None) is not None:
        return window.p9710_miol_grid_box

    workspace = getattr(window, "measurement_workspace", None)
    if workspace is None or workspace.layout() is None:
        raise RuntimeError("Measurement workspace must exist before MIOL grid runtime.")

    box = QGroupBox("P-9710 MIOL — Full C × Gamma Scan")
    root = QVBoxLayout(box)
    form = QGridLayout()

    range_spin = QSpinBox()
    range_spin.setRange(0, 7)
    range_spin.setValue(DEFAULT_RANGE)

    period_spin = QDoubleSpinBox()
    period_spin.setRange(0.05, 120.0)
    period_spin.setDecimals(4)
    period_spin.setSuffix(" s")
    period_spin.setValue(DEFAULT_PERIOD_S)

    pre_spin = QSpinBox()
    pre_spin.setRange(0, 5000)
    pre_spin.setSuffix(" ms")
    pre_spin.setValue(DEFAULT_PRETRIGGER_MS)

    window_spin = QSpinBox()
    window_spin.setRange(1, 10000)
    window_spin.setSuffix(" ms")
    window_spin.setValue(DEFAULT_WINDOW_MS)

    sc_c_spin = QDoubleSpinBox()
    sc_c_spin.setRange(0.001, 10.0)
    sc_c_spin.setDecimals(3)
    sc_c_spin.setSuffix(" s")
    sc_c_spin.setValue(DEFAULT_SC_C_S)

    cw_integration = QDoubleSpinBox()
    cw_integration.setRange(0.1, 6000.0)
    cw_integration.setDecimals(1)
    cw_integration.setSuffix(" ms")
    cw_integration.setValue(DEFAULT_CW_INTEGRATION_MS)

    form.addWidget(QLabel("Starting P-9710 range:"), 0, 0)
    form.addWidget(range_spin, 0, 1)
    form.addWidget(QLabel("Flash period:"), 0, 2)
    form.addWidget(period_spin, 0, 3)
    form.addWidget(QLabel("Pre-trigger:"), 1, 0)
    form.addWidget(pre_spin, 1, 1)
    form.addWidget(QLabel("MI window:"), 1, 2)
    form.addWidget(window_spin, 1, 3)
    form.addWidget(QLabel("Trigger:"), 2, 0)
    form.addWidget(QLabel("Adaptive rising edge"), 2, 1)
    form.addWidget(QLabel("Schmidt-Clausen C:"), 2, 2)
    form.addWidget(sc_c_spin, 2, 3)
    form.addWidget(QLabel("Type C CW integration:"), 3, 0)
    form.addWidget(cw_integration, 3, 1)
    root.addLayout(form)

    note = QLabel(
        "Full local scan: C −45°…+45° at 0.5° and Gamma −10°…+10° at 0.5°. "
        "Type A/B has no fixed lux trigger threshold: Lumigon detects a rising edge, "
        "adapts P-9710 range before the pulse, then locks that range for MI. "
        "Every completed point is flushed immediately to CSV."
    )
    note.setWordWrap(True)
    note.setStyleSheet("color:#8AA8BC;")
    root.addWidget(note)

    status = QLabel("Ready — connect P-9710 and both servo drives before starting.")
    status.setWordWrap(True)
    progress = QProgressBar()
    progress.setRange(0, 1)
    progress.setValue(0)
    progress.setFormat("0 / 0")
    start_button = QPushButton("Start Full P-9710 MIOL Scan")
    stop_button = QPushButton("Stop safely")
    stop_button.setEnabled(False)
    root.addWidget(status)
    root.addWidget(progress)
    root.addWidget(start_button)
    root.addWidget(stop_button)

    layout = workspace.layout()
    miol_box = getattr(window, "measurement_miol_profile_box", None)
    insert_at = layout.indexOf(miol_box) + 1 if miol_box is not None else 2
    layout.insertWidget(max(0, insert_at), box)

    worker_holder = {"worker": None}
    polling_state = {"main_timer_was_active": False}

    def apply_defaults():
        profile = getattr(window, "measurement_profile_combo", None)
        if profile is None or profile_type_from_text(profile.currentText()) is None:
            box.setVisible(False)
            return
        box.setVisible(True)
        scan = getattr(window, "measurement_scan_mode_combo", None)
        if scan is not None:
            scan.setCurrentIndex(2)
        window.measurement_c_start.setValue(max(-C_LIMIT_DEG, DEFAULT_C_START_DEG))
        window.measurement_c_end.setValue(min(C_LIMIT_DEG, DEFAULT_C_END_DEG))
        window.measurement_c_step.setValue(DEFAULT_C_STEP_DEG)
        window.measurement_gamma_start.setValue(max(-GAMMA_LIMIT_DEG, DEFAULT_GAMMA_START_DEG))
        window.measurement_gamma_end.setValue(min(GAMMA_LIMIT_DEG, DEFAULT_GAMMA_END_DEG))
        window.measurement_gamma_step.setValue(DEFAULT_GAMMA_STEP_DEG)
        distance = getattr(window, "measurement_distance_spin", None)
        if distance is not None:
            distance.setSingleStep(0.01)
            distance.setValue(DEFAULT_DISTANCE_M)
        order = getattr(window, "measurement_scan_order_combo", None)
        if order is not None:
            order.setCurrentIndex(0)

    def current_profile_code():
        combo = getattr(window, "measurement_profile_combo", None)
        return None if combo is None else profile_type_from_text(combo.currentText())

    def prerequisites():
        code = current_profile_code()
        if code is None:
            return "Select MIOL Type A, B or C."
        modbus = getattr(window, "modbus", None)
        if modbus is None or not modbus.is_connected:
            return "Connect the servo drives first."
        motion = getattr(window, "motion", None)
        if motion is None:
            return "Motion controller is not available."
        if motion.gamma_zero_puu is None or motion.c_zero_puu is None:
            return "Capture a valid Session Zero for both axes first."
        holder = getattr(window, "p9710_meter_holder", None)
        meter = None if holder is None else holder.get("meter")
        if meter is None or not meter.is_connected:
            return "Connect the P-9710 in Luxmeter > Gigahertz-Optik P-9710 first."
        if worker_holder["worker"] is not None:
            return "A P-9710 MIOL scan is already running."
        return None

    def build_points():
        c0 = window.measurement_c_start.value()
        c1 = window.measurement_c_end.value()
        g0 = window.measurement_gamma_start.value()
        g1 = window.measurement_gamma_end.value()
        if min(c0, c1) < -C_LIMIT_DEG or max(c0, c1) > C_LIMIT_DEG:
            raise ValueError(f"C scan must remain inside ±{C_LIMIT_DEG:g}°.")
        if min(g0, g1) < -GAMMA_LIMIT_DEG or max(g0, g1) > GAMMA_LIMIT_DEG:
            raise ValueError(f"Gamma scan must remain inside ±{GAMMA_LIMIT_DEG:g}°.")
        return _build_grid(
            c0, c1, window.measurement_c_step.value(),
            g0, g1, window.measurement_gamma_step.value(),
        )

    def finish_ui():
        worker = worker_holder["worker"]
        if worker is not None:
            worker.deleteLater()
        worker_holder["worker"] = None
        window.p9710_miol_grid_worker = None
        start_button.setEnabled(True)
        stop_button.setEnabled(False)
        timer = getattr(window, "timer", None)
        modbus = getattr(window, "modbus", None)
        if (
            polling_state["main_timer_was_active"]
            and timer is not None
            and modbus is not None
            and modbus.is_connected
        ):
            timer.start()
        polling_state["main_timer_was_active"] = False

    def start():
        problem = prerequisites()
        if problem:
            QMessageBox.warning(window, "P-9710 MIOL Scan", problem)
            return
        try:
            points = build_points()
        except Exception as exc:
            QMessageBox.warning(window, "P-9710 MIOL Scan", str(exc))
            return

        code = current_profile_code()
        spec = MIOL_PROFILES[code]
        distance = window.measurement_distance_spin.value()
        settle = window.measurement_settle_spin.value()
        basis = "E-effective (SC, adaptive trigger/range)" if spec.flashing else "CW adaptive range"

        answer = QMessageBox.question(
            window,
            "Confirm Full P-9710 MIOL Scan",
            f"Start {len(points)} points?\n\n"
            f"C: {window.measurement_c_start.value():+.1f}° → {window.measurement_c_end.value():+.1f}° "
            f"step {window.measurement_c_step.value():g}°\n"
            f"Gamma: {window.measurement_gamma_start.value():+.1f}° → {window.measurement_gamma_end.value():+.1f}° "
            f"step {window.measurement_gamma_step.value():g}°\n"
            f"Profile: MIOL Type {code}\nBasis: {basis}\nDistance: {distance:.2f} m\n\n"
            "Both axes will move. P-9710 range may adapt before each flash, but remains fixed during MI. "
            "The CSV is flushed after every completed point.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        stop_continuous = getattr(window, "p9710_stop_continuous", None)
        if callable(stop_continuous):
            stop_continuous()

        timer = getattr(window, "timer", None)
        polling_state["main_timer_was_active"] = bool(timer is not None and timer.isActive())
        if polling_state["main_timer_was_active"]:
            timer.stop()

        sample_id = getattr(window, "measurement_sample_id_edit", None)
        sample_text = "sample" if sample_id is None else (sample_id.text().strip() or "sample")
        safe_sample = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in sample_text)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = Path.cwd() / "measurement_data" / f"MIOL_{code}_FULL_{safe_sample}_{stamp}.csv"

        meter = window.p9710_meter_holder["meter"]
        worker = P9710MIOLGridWorker(
            motion=window.motion,
            meter=meter,
            points=points,
            profile_code=code,
            distance_m=distance,
            settle_time_s=settle,
            range_id=range_spin.value(),
            period_s=period_spin.value(),
            pretrigger_ms=pre_spin.value(),
            window_ms=window_spin.value(),
            sc_c_s=sc_c_spin.value(),
            cw_integration_ms=cw_integration.value(),
            output_path=output_path,
            parent=window,
        )
        worker_holder["worker"] = worker
        window.p9710_miol_grid_worker = worker
        window.p9710_miol_last_csv = str(output_path)

        progress.setRange(0, len(points))
        progress.setValue(0)
        progress.setFormat(f"0 / {len(points)}")
        status.setText(f"Starting full scan — output: {output_path}")
        start_button.setEnabled(False)
        stop_button.setEnabled(True)

        def on_progress(text):
            status.setText(text)

        def on_started(index, total, c_deg, gamma_deg):
            progress.setValue(index - 1)
            progress.setFormat(
                f"{index - 1} / {total} • C {c_deg:+.1f}° • Gamma {gamma_deg:+.1f}°"
            )

        def on_result(row):
            point = int(row["point"])
            progress.setValue(point)
            gp_text = "—" if not row["GP_pct"] else f"{float(row['GP_pct']):.1f}%"
            progress.setFormat(
                f"{point} / {len(points)} • {float(row['I_cd']):.1f} cd • R{row['range_id']} • GP {gp_text}"
            )

        def on_completed(path):
            status.setText(f"Complete — axes returned Home — CSV: {path}")
            QMessageBox.information(
                window,
                "P-9710 MIOL Scan",
                f"Full scan complete.\n\nCSV:\n{path}",
            )

        def on_aborted(message):
            status.setText(message)
            QMessageBox.information(window, "P-9710 MIOL Scan", message)

        def on_failed(message):
            status.setText("Scan stopped due to an error — partial CSV is preserved.")
            QMessageBox.critical(window, "P-9710 MIOL Scan", message)

        worker.progress.connect(on_progress)
        worker.point_started.connect(on_started)
        worker.point_result.connect(on_result)
        worker.completed.connect(on_completed)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.finished.connect(finish_ui)
        worker.start()

    def stop():
        worker = worker_holder["worker"]
        if worker is None:
            return
        stop_button.setEnabled(False)
        status.setText(
            "Stop requested — current instrument read/move will finish, then the run stops safely."
        )
        worker.requestInterruption()

    start_button.clicked.connect(start)
    stop_button.clicked.connect(stop)

    profile_combo = getattr(window, "measurement_profile_combo", None)
    if profile_combo is not None:
        profile_combo.currentIndexChanged.connect(lambda *_: apply_defaults())

    window.p9710_miol_grid_box = box
    window.p9710_miol_grid_worker = None
    window.p9710_miol_last_csv = None

    apply_defaults()
    return box
