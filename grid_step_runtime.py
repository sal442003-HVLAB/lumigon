"""C × Gamma Step Grid execution for Lumigon.

This runtime layer extends the proven Step Scan engine without changing
single-axis behaviour. Grid execution is deliberately stop/settle/acquire:
- both axes participate in one test,
- only one axis is commanded at a time,
- rows are traversed serpentine to avoid unnecessary return moves,
- both feedback angles are verified before every photometric acquisition,
- normal completion still uses the existing automatic Return Home workflow.

Continuous-row grid scanning is intentionally not enabled here; it is a later
phase after Step Grid is proven on the real mechanism.
"""

from __future__ import annotations

import time
from collections import OrderedDict

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from measurement_execution import MeasurementRunWorker
from motion_controller import C_AXIS, GAMMA
from test_plan_workspace import (
    CommissioningMotionWorker,
    FIXED_AXIS_TOLERANCE_DEG,
    INTER_SAMPLE_DELAY_MS,
    SCAN_GRID,
    TestPlanWorkspace,
    _readonly_item,
)
from test_plan_runtime_improvements import (
    ETA_MARGIN_FACTOR,
    FORMAL_MEASUREMENT_SETUP_S,
    MEASUREMENT_QUERY_OVERHEAD_S,
    _axis_motion_seconds,
)


GRID_POSITION_TOLERANCE_DEG = FIXED_AXIS_TOLERANCE_DEG
GRID_MAX_CORRECTION_PASSES = 3
GRID_MOVE_EPSILON_DEG = 0.01


def _group_serpentine(points, traversal_index: int):
    """Return existing table rows in a serpentine grid traversal."""

    groups = OrderedDict()
    if int(traversal_index) == 0:
        # Gamma sweep for each C position.
        for point in points:
            groups.setdefault(round(point[1], 6), []).append(point)
    else:
        # C sweep for each Gamma position.
        for point in points:
            groups.setdefault(round(point[2], 6), []).append(point)

    ordered = []
    for line_index, group in enumerate(groups.values()):
        line = list(group)
        if line_index % 2:
            line.reverse()
        ordered.extend(line)
    return ordered


def _nearest_end_order(workspace, points):
    """Allow a complete serpentine grid to start from its nearer end."""

    if len(points) <= 1:
        return points

    motion = getattr(workspace.host_window, "motion", None)
    modbus = getattr(workspace.host_window, "modbus", None)
    if motion is None or modbus is None or not modbus.is_connected:
        return points
    if motion.gamma_zero_puu is None or motion.c_zero_puu is None:
        return points

    try:
        current_c = motion.get_current_angle(C_AXIS)
        current_gamma = motion.get_current_angle(GAMMA)
    except Exception:
        return points

    def approach_seconds(target):
        _, c_deg, gamma_deg = target
        return (
            _axis_motion_seconds(motion, C_AXIS, c_deg - current_c)
            + _axis_motion_seconds(motion, GAMMA, gamma_deg - current_gamma)
        )

    if approach_seconds(points[-1]) + 0.05 < approach_seconds(points[0]):
        return list(reversed(points))
    return points


def _position_grid_pair(worker, c_target, gamma_target, *, prefix=""):
    """Sequentially position and verify both axes at one grid coordinate."""

    c_target = float(c_target)
    gamma_target = float(gamma_target)

    for correction_pass in range(GRID_MAX_CORRECTION_PASSES):
        if worker.isInterruptionRequested():
            return False

        c_actual = worker.motion.get_current_angle(C_AXIS)
        gamma_actual = worker.motion.get_current_angle(GAMMA)
        c_error = c_actual - c_target
        gamma_error = gamma_actual - gamma_target

        if (
            abs(c_error) <= GRID_POSITION_TOLERANCE_DEG
            and abs(gamma_error) <= GRID_POSITION_TOLERANCE_DEG
        ):
            return True

        # C first, Gamma second. A subsequent correction pass catches any small
        # mechanical coupling introduced by the second move.
        if abs(c_error) > GRID_POSITION_TOLERANCE_DEG:
            worker.progress.emit(
                f"{prefix}moving C: {c_actual:+.3f}° → {c_target:+.3f}°"
            )
            worker.motion.move_absolute(C_AXIS, c_target)
            if worker.isInterruptionRequested():
                return False

        gamma_actual = worker.motion.get_current_angle(GAMMA)
        gamma_error = gamma_actual - gamma_target
        if abs(gamma_error) > GRID_POSITION_TOLERANCE_DEG:
            worker.progress.emit(
                f"{prefix}moving Gamma: {gamma_actual:+.3f}° → {gamma_target:+.3f}°"
            )
            worker.motion.move_absolute(GAMMA, gamma_target)

    c_final = worker.motion.get_current_angle(C_AXIS)
    gamma_final = worker.motion.get_current_angle(GAMMA)
    c_error = c_final - c_target
    gamma_error = gamma_final - gamma_target
    if (
        abs(c_error) > GRID_POSITION_TOLERANCE_DEG
        or abs(gamma_error) > GRID_POSITION_TOLERANCE_DEG
    ):
        raise RuntimeError(
            "Grid position verification failed. "
            f"Target C {c_target:+.3f}°, Gamma {gamma_target:+.3f}°; "
            f"actual C {c_final:+.3f}°, Gamma {gamma_final:+.3f}°."
        )
    return True


def _grid_measurement_run(worker):
    try:
        if not worker.points:
            raise RuntimeError("No Ready grid points were supplied.")
        if worker.distance_m <= 0.0:
            raise RuntimeError("Measurement distance must be greater than zero.")

        if worker.apply_measurement_settings:
            if worker.meter.integration_time_ms != worker.integration_ms:
                worker.progress.emit(
                    f"Applying luxmeter integration: {worker.integration_ms} ms"
                )
                worker.meter.set_integration_time(worker.integration_ms)
        worker.meter.set_software_trigger()

        total = len(worker.points)
        first_row, first_c, first_gamma = worker.points[0]
        worker.progress.emit(
            "Preparing C × Gamma Grid start position — no acquisition until both axes are verified…"
        )
        if not _position_grid_pair(
            worker,
            first_c,
            first_gamma,
            prefix="Grid start: ",
        ):
            worker.aborted.emit(
                "Grid scan stopped after safe start-position motion; no acquisition was started."
            )
            return

        for sequence, (row, c_target, gamma_target) in enumerate(
            worker.points,
            start=1,
        ):
            if worker.isInterruptionRequested():
                worker.aborted.emit("Grid measurement stopped before the next point.")
                return
            if not worker._wait_while_paused():
                worker.aborted.emit("Grid measurement stopped while paused.")
                return

            worker.point_started.emit(
                row,
                sequence,
                total,
                c_target,
                gamma_target,
            )

            if sequence == 1:
                worker.progress.emit(
                    f"Grid point 1/{total}: start coordinate verified — "
                    f"C {c_target:+.3f}°, Gamma {gamma_target:+.3f}°"
                )
            else:
                ok = _position_grid_pair(
                    worker,
                    c_target,
                    gamma_target,
                    prefix=f"Grid point {sequence}/{total}: ",
                )
                if not ok:
                    worker.aborted.emit(
                        "Stop requested. Active servo motion completed safely; "
                        "no further grid acquisition was started."
                    )
                    return

            if worker.isInterruptionRequested():
                worker.aborted.emit(
                    "Stop requested after positioning; Lux acquisition was skipped."
                )
                return
            if not worker._wait_while_paused():
                worker.aborted.emit("Grid measurement stopped after positioning.")
                return

            worker.progress.emit(
                f"Grid point {sequence}/{total}: settling for {worker.settle_time_s:.1f} s"
            )
            if not worker._wait_interruptible(worker.settle_time_s):
                worker.aborted.emit("Grid measurement stopped during settling.")
                return

            # Final pair check immediately before reading Lux.
            c_actual = worker.motion.get_current_angle(C_AXIS)
            gamma_actual = worker.motion.get_current_angle(GAMMA)
            if (
                abs(c_actual - c_target) > GRID_POSITION_TOLERANCE_DEG
                or abs(gamma_actual - gamma_target) > GRID_POSITION_TOLERANCE_DEG
            ):
                if not _position_grid_pair(
                    worker,
                    c_target,
                    gamma_target,
                    prefix=f"Grid point {sequence}/{total} correction: ",
                ):
                    worker.aborted.emit("Grid measurement stopped before acquisition.")
                    return

            worker.progress.emit(
                f"Grid point {sequence}/{total}: acquiring {worker.samples} Lux samples"
            )
            reading = worker.meter.read_lux(samples=worker.samples)
            if worker.isInterruptionRequested():
                worker.aborted.emit(
                    "Stop requested during acquisition; completed reading was discarded."
                )
                return

            candela = reading.lux * (worker.distance_m ** 2)
            current_na = reading.mean_current_a * 1e9
            worker.point_result.emit(
                row,
                current_na,
                reading.lux,
                reading.stdev_lux,
                candela,
            )

        worker.run_completed.emit()
    except Exception as exc:
        worker.failed.emit(str(exc))


def _grid_commissioning_run(worker):
    try:
        if not worker.points:
            raise RuntimeError("No Ready grid points were supplied.")

        total = len(worker.points)
        _, first_c, first_gamma = worker.points[0]
        worker.progress.emit("Preparing motion-only C × Gamma Grid start position…")
        if not _position_grid_pair(
            worker,
            first_c,
            first_gamma,
            prefix="Grid start: ",
        ):
            worker.aborted.emit("Motion-only grid stopped before point 1.")
            return

        for sequence, (row, c_target, gamma_target) in enumerate(
            worker.points,
            start=1,
        ):
            if worker.isInterruptionRequested():
                worker.aborted.emit("Motion-only grid stopped before the next point.")
                return
            if not worker._wait_while_paused():
                worker.aborted.emit("Motion-only grid stopped while paused.")
                return

            worker.point_started.emit(
                row,
                sequence,
                total,
                c_target,
                gamma_target,
            )
            if sequence > 1:
                if not _position_grid_pair(
                    worker,
                    c_target,
                    gamma_target,
                    prefix=f"Grid point {sequence}/{total}: ",
                ):
                    worker.aborted.emit("Motion-only grid stopped safely.")
                    return

            if worker.settle_time_s > 0.0:
                if not worker._wait_interruptible(worker.settle_time_s):
                    worker.aborted.emit("Motion-only grid stopped during settling.")
                    return

            worker.point_done.emit(
                row,
                sequence,
                total,
                c_target,
                gamma_target,
            )

        worker.run_completed.emit()
    except Exception as exc:
        worker.failed.emit(str(exc))


def _grid_eta(workspace, points, *, motion_only=False):
    if not points:
        return 0.0

    motion = workspace.host_window.motion
    try:
        current_c = motion.get_current_angle(C_AXIS)
        current_gamma = motion.get_current_angle(GAMMA)
    except Exception:
        current_c = points[0][1]
        current_gamma = points[0][2]

    seconds = 0.0
    previous_c = current_c
    previous_gamma = current_gamma
    for _, c_target, gamma_target in points:
        seconds += _axis_motion_seconds(motion, C_AXIS, c_target - previous_c)
        seconds += _axis_motion_seconds(motion, GAMMA, gamma_target - previous_gamma)
        previous_c = c_target
        previous_gamma = gamma_target

    # Normal completion includes automatic Home return.
    seconds += _axis_motion_seconds(motion, C_AXIS, -previous_c)
    seconds += _axis_motion_seconds(motion, GAMMA, -previous_gamma)

    settle = workspace.host_window.measurement_settle_spin.value()
    seconds += len(points) * settle

    if not motion_only:
        samples = workspace.host_window.measurement_samples_spin.value()
        integration_s = workspace.host_window.measurement_integration_spin.value() / 1000.0
        sample_block_s = samples * (integration_s + MEASUREMENT_QUERY_OVERHEAD_S)
        if samples > 1:
            sample_block_s += (samples - 1) * (INTER_SAMPLE_DELAY_MS / 1000.0)
        seconds += len(points) * sample_block_s
        seconds += FORMAL_MEASUREMENT_SETUP_S

    return seconds * ETA_MARGIN_FACTOR


def install_grid_step_runtime():
    """Patch worker/workspace behaviour before TestPlanWorkspace is created."""

    if getattr(TestPlanWorkspace, "_grid_step_runtime_installed", False):
        return
    TestPlanWorkspace._grid_step_runtime_installed = True

    previous_measurement_run = MeasurementRunWorker.run
    previous_commissioning_run = CommissioningMotionWorker.run
    previous_ready_points = TestPlanWorkspace._ready_points
    previous_problem = TestPlanWorkspace._validated_single_axis_problem
    previous_start_step = TestPlanWorkspace.start_step_scan
    previous_start_continuous = TestPlanWorkspace.start_continuous_scan
    previous_step_estimate = TestPlanWorkspace._step_estimate_seconds

    def measurement_run(worker):
        if worker.scan_mode == SCAN_GRID:
            return _grid_measurement_run(worker)
        return previous_measurement_run(worker)

    def commissioning_run(worker):
        if worker.scan_mode == SCAN_GRID:
            return _grid_commissioning_run(worker)
        return previous_commissioning_run(worker)

    def ready_points(workspace):
        points = previous_ready_points(workspace)
        if workspace.host_window.measurement_scan_mode_combo.currentIndex() != SCAN_GRID:
            return points
        traversal = workspace.host_window.measurement_scan_order_combo.currentIndex()
        points = _group_serpentine(points, traversal)
        return _nearest_end_order(workspace, points)

    def validated_problem(workspace):
        if workspace.host_window.measurement_scan_mode_combo.currentIndex() != SCAN_GRID:
            return previous_problem(workspace)

        if workspace.step_start_button is None or not workspace.step_start_button.isEnabled():
            return "Build and Validate the C × Gamma Test Plan before starting."
        modbus = getattr(workspace.host_window, "modbus", None)
        if modbus is None or not modbus.is_connected:
            return "Connect the servo drives before measuring."
        motion = getattr(workspace.host_window, "motion", None)
        if motion is None:
            return "Motion controller is not available."
        if motion.gamma_zero_puu is None or motion.c_zero_puu is None:
            return "Capture a valid Session Zero for both axes before measuring."
        if not workspace._ready_points():
            return "There are no Ready grid points remaining in this plan."
        return None

    def start_step(workspace):
        if workspace.host_window.measurement_scan_mode_combo.currentIndex() != SCAN_GRID:
            return previous_start_step(workspace)

        problem = workspace._validated_single_axis_problem()
        if problem:
            QMessageBox.warning(workspace, "C × Gamma Grid", problem)
            return

        points = workspace._ready_points()
        meter = getattr(workspace.host_window, "luxmeter", None)
        meter_connected = bool(meter is not None and meter.is_connected)
        live_worker = getattr(workspace.host_window, "luxmeter_live_worker", None)
        if meter_connected and live_worker is not None and live_worker.isRunning():
            QMessageBox.warning(
                workspace,
                "C × Gamma Grid",
                "Stop Luxmeter Live acquisition before starting the formal grid measurement.",
            )
            return

        unique_c = len({round(point[1], 6) for point in points})
        unique_gamma = len({round(point[2], 6) for point in points})
        traversal = workspace.host_window.measurement_scan_order_combo.currentText()
        first = points[0]
        last = points[-1]
        commissioning_note = (
            "\n\nLuxmeter is not connected. The grid will run MOTION ONLY; Lux/Candela will not be recorded."
            if not meter_connected
            else ""
        )
        answer = QMessageBox.question(
            workspace,
            "Confirm C × Gamma Step Grid",
            f"Start C × Gamma Step Grid of {len(points)} Ready points?\n\n"
            f"Grid: {unique_c} C positions × {unique_gamma} Gamma positions\n"
            f"Traversal: serpentine — {traversal}\n"
            f"First coordinate: C {first[1]:+.3f}°, Gamma {first[2]:+.3f}°\n"
            f"Final coordinate: C {last[1]:+.3f}°, Gamma {last[2]:+.3f}°\n\n"
            "At every point Lumigon will position and verify BOTH axes before acquisition.\n"
            f"Settling: {workspace.host_window.measurement_settle_spin.value():.1f} s / point\n"
            f"Samples: {workspace.host_window.measurement_samples_spin.value()} / point\n"
            f"Distance: {workspace.host_window.measurement_distance_spin.value():.2f} m"
            f"{commissioning_note}",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if meter_connected and hasattr(workspace.host_window, "luxmeter_sensitivity_spin"):
            meter.sensitivity_na_per_lx = workspace.host_window.luxmeter_sensitivity_spin.value()

        if meter_connected:
            worker = MeasurementRunWorker(
                motion=workspace.host_window.motion,
                meter=meter,
                scan_mode=SCAN_GRID,
                points=points,
                settle_time_s=workspace.host_window.measurement_settle_spin.value(),
                samples=workspace.host_window.measurement_samples_spin.value(),
                integration_ms=workspace.host_window.measurement_integration_spin.value(),
                apply_measurement_settings=True,
                distance_m=workspace.host_window.measurement_distance_spin.value(),
                parent=workspace,
            )
        else:
            worker = CommissioningMotionWorker(
                motion=workspace.host_window.motion,
                scan_mode=SCAN_GRID,
                points=points,
                settle_time_s=workspace.host_window.measurement_settle_spin.value(),
                parent=workspace,
            )

        workspace.active_worker = worker
        workspace.host_window.measurement_worker = worker
        workspace._stop_main_timer()
        workspace._begin_run(
            mode_text="C × Gamma Step Grid",
            total=len(points),
            estimate_s=_grid_eta(workspace, points, motion_only=not meter_connected),
            motion_only=not meter_connected,
        )
        workspace._set_source_state(
            f"GRID RUNNING  •  0/{len(points)}",
            "measurementStateDraft",
        )

        completed = 0
        point_by_row = {row: (c_deg, gamma_deg) for row, c_deg, gamma_deg in points}

        def on_progress(text):
            workspace.run_status_label.setText(text)

        def on_point_started(row, sequence, total, c_deg, gamma_deg):
            workspace.plan_table.setItem(row, 8, _readonly_item("Running"))
            workspace.plan_table.selectRow(row)
            first_item = workspace.plan_table.item(row, 0)
            if first_item is not None:
                workspace.plan_table.scrollToItem(first_item)
            workspace._set_current_point(sequence, total, c_deg, gamma_deg)
            workspace._set_source_state(
                f"GRID RUNNING  •  POINT {sequence}/{total}",
                "measurementStateDraft",
            )

        def on_pause_state(is_paused):
            workspace.paused = bool(is_paused)
            if hasattr(workspace, "run_pause_button"):
                workspace.run_pause_button.setText("Resume" if workspace.paused else "Pause")
            if workspace.paused:
                workspace.run_status_label.setText("Grid measurement paused at a safe checkpoint.")

        def on_result(row, current_na, lux, stdev_lux, candela):
            nonlocal completed
            completed += 1
            c_deg, gamma_deg = point_by_row[row]
            workspace.plan_table.setItem(row, 5, _readonly_item(f"{lux:.3f}"))
            workspace.plan_table.setItem(row, 6, _readonly_item(f"{candela:.1f}"))
            workspace.plan_table.setItem(row, 8, _readonly_item("Measured"))
            workspace._set_live_position(c_deg, gamma_deg)
            workspace._set_photometry(current_na, lux, candela, stdev_lux)
            workspace._set_run_completed(completed)

            host = workspace.host_window
            if hasattr(host, "luxmeter_current_label"):
                host.luxmeter_current_label.setText(f"Current: {current_na:.2f} nA")
            if hasattr(host, "luxmeter_lux_label"):
                host.luxmeter_lux_label.setText(f"Lux: {lux:.3f} lx")
            if hasattr(host, "luxmeter_stability_label"):
                host.luxmeter_stability_label.setText(f"Std. dev.: {stdev_lux:.3f} lx")
            host.luxmeter_last_current_a = current_na * 1e-9
            host.luxmeter_last_lux = lux
            host.measurement_results.append(
                {
                    "point": row + 1,
                    "c_deg": c_deg,
                    "gamma_deg": gamma_deg,
                    "lux": lux,
                    "candela": candela,
                    "stdev_lux": stdev_lux,
                    "mean_current_na": current_na,
                    "distance_m": host.measurement_distance_spin.value(),
                    "samples": host.measurement_samples_spin.value(),
                    "integration_ms": meter.integration_time_ms,
                    "execution_mode": "step-grid",
                }
            )

        def on_motion_done(row, sequence, total, c_deg, gamma_deg):
            nonlocal completed
            completed += 1
            workspace.plan_table.setItem(row, 8, _readonly_item("Motion OK"))
            workspace._set_current_point(sequence, total, c_deg, gamma_deg)
            workspace._set_live_position(c_deg, gamma_deg)
            workspace.run_photometry_label.setText("Motion-only grid — no Lux acquisition")
            workspace._set_run_completed(completed)

        def reset_running_row():
            for row, *_ in points:
                item = workspace.plan_table.item(row, 8)
                if item is not None and item.text() == "Running":
                    workspace.plan_table.setItem(row, 8, _readonly_item("Ready"))

        def on_aborted(message):
            reset_running_row()
            workspace._finish_run_monitor(message)
            workspace._set_source_state(
                f"VALIDATED GRID  •  {completed}/{len(points)} COMPLETE",
                "measurementStateValid",
            )

        def on_failed(message):
            reset_running_row()
            workspace._finish_run_monitor("C × Gamma Grid failed.")
            workspace._set_source_state("GRID FAILED", "measurementStateInvalid")
            QMessageBox.critical(workspace, "C × Gamma Grid Error", message)

        def on_completed():
            workspace.run_finished_normally = True
            workspace._set_run_completed(len(points))
            if workspace.motion_only:
                workspace._finish_run_monitor(
                    "Motion-only C × Gamma Grid complete — all requested coordinate pairs verified."
                )
                workspace._set_source_state(
                    f"GRID MOTION CHECK COMPLETE  •  {len(points)}/{len(points)}",
                    "measurementStateValid",
                )
            else:
                workspace._finish_run_monitor("C × Gamma Step Grid complete.")
                workspace._set_source_state(
                    f"GRID COMPLETE  •  {len(points)}/{len(points)} MEASURED",
                    "measurementStateValid",
                )

        worker.progress.connect(on_progress)
        worker.point_started.connect(on_point_started)
        worker.pause_state.connect(on_pause_state)
        worker.aborted.connect(on_aborted)
        worker.failed.connect(on_failed)
        worker.run_completed.connect(on_completed)
        if meter_connected:
            worker.point_result.connect(on_result)
        else:
            worker.point_done.connect(on_motion_done)
        worker.finished.connect(workspace._restore_after_worker)
        worker.start()

    def start_continuous(workspace):
        if workspace.host_window.measurement_scan_mode_combo.currentIndex() == SCAN_GRID:
            QMessageBox.information(
                workspace,
                "Continuous C × Gamma Grid",
                "Step Grid is enabled first for hardware validation. Continuous-row Grid "
                "will be enabled after the two-axis Step Grid is proven on the mechanism.",
            )
            return
        return previous_start_continuous(workspace)

    def step_estimate(workspace, point_count, motion_only=False):
        if workspace.host_window.measurement_scan_mode_combo.currentIndex() == SCAN_GRID:
            return _grid_eta(
                workspace,
                workspace._ready_points(),
                motion_only=motion_only,
            )
        return previous_step_estimate(workspace, point_count, motion_only=motion_only)

    MeasurementRunWorker.run = measurement_run
    CommissioningMotionWorker.run = commissioning_run
    TestPlanWorkspace._ready_points = ready_points
    TestPlanWorkspace._validated_single_axis_problem = validated_problem
    TestPlanWorkspace.start_step_scan = start_step
    TestPlanWorkspace.start_continuous_scan = start_continuous
    TestPlanWorkspace._step_estimate_seconds = step_estimate


def attach_grid_step_runtime(window):
    """Enable a validated Grid plan after the legacy validator finishes."""

    if getattr(window, "_grid_step_ui_attached", False):
        return
    window._grid_step_ui_attached = True

    validate_button = getattr(window, "measurement_validate_plan_button", None)
    start_button = getattr(window, "measurement_start_button", None)
    scan_mode = getattr(window, "measurement_scan_mode_combo", None)
    state = getattr(window, "measurement_state_label", None)
    if validate_button is None or start_button is None or scan_mode is None or state is None:
        raise RuntimeError("Measurement Grid controls are not available.")

    def enable_grid_if_valid():
        if scan_mode.currentIndex() != SCAN_GRID:
            return
        if "VALIDATED" not in state.text().upper():
            return
        table = getattr(window, "measurement_plan_table", None)
        if table is None or table.rowCount() <= 0:
            return
        ready = 0
        for row in range(table.rowCount()):
            item = table.item(row, 8)
            if item is not None and item.text() == "Ready":
                ready += 1
        if ready:
            start_button.setEnabled(True)
            state.setText(f"VALIDATED GRID  •  {ready} POINTS")

    def after_validate(*_args):
        QTimer.singleShot(0, enable_grid_if_valid)

    validate_button.clicked.connect(after_validate)
