"""Attach persistent Results handling to the Test Plan runtime.

This module intentionally observes the completed run rather than changing the
measurement engines.  A successful photometric run is archived only after the
normal post-test Home sequence has finished.
"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtWidgets import QMessageBox

from measurement_run import build_measurement_run, save_measurement_run_csv
from test_plan_workspace import TestPlanWorkspace


def _fmt_optional(value, unit="", decimals=3):
    if value is None:
        return "—"
    return f"{value:.{decimals}f}{unit}"


def install_measurement_results_runtime():
    if getattr(TestPlanWorkspace, "_results_runtime_installed", False):
        return
    TestPlanWorkspace._results_runtime_installed = True

    original_begin_run = TestPlanWorkspace._begin_run
    original_restore_after_worker = TestPlanWorkspace._restore_after_worker

    def patched_begin_run(self, *, mode_text, total, estimate_s, motion_only):
        self._archive_started_wall = datetime.now().astimezone()
        self._archive_started_monotonic = time.monotonic()
        self._archive_results_index = len(
            getattr(self.host_window, "measurement_results", [])
        )
        self._archive_execution_mode = mode_text
        self._archive_motion_only = bool(motion_only)
        self._archive_done = False

        # A Home warning belongs only to the run that produced it.
        if hasattr(self, "_home_return_failed"):
            self._home_return_failed = None

        return original_begin_run(
            self,
            mode_text=mode_text,
            total=total,
            estimate_s=estimate_s,
            motion_only=motion_only,
        )

    def _show_complete_dialog(self, run):
        peak = run.peak_candela_point
        peak_text = "—"
        if peak is not None and peak.candela_cd is not None:
            peak_text = (
                f"{peak.candela_cd:.1f} cd at "
                f"C {peak.c_deg:+.2f}°, Gamma {peak.gamma_deg:+.2f}°"
            )

        csv_text = str(run.csv_path) if run.csv_path is not None else "Not saved"
        if run.save_error:
            csv_text += f"\nCSV error: {run.save_error}"

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle("Measurement Complete")
        box.setText("Measurement completed successfully.")
        box.setInformativeText(
            f"Measured points: {run.point_count}\n"
            f"Duration: {run.duration_s:.1f} s\n"
            f"Maximum Lux: {_fmt_optional(run.max_lux, ' lx', 3)}\n"
            f"Peak Candela: {peak_text}\n"
            f"Home: {run.home_status}\n\n"
            f"CSV: {csv_text}"
        )
        view_button = box.addButton("View Results", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()

        if box.clickedButton() is view_button:
            tabs = getattr(self.host_window, "main_tabs", None)
            results_tab = getattr(self.host_window, "results_tab", None)
            if tabs is not None and results_tab is not None:
                tabs.setCurrentWidget(results_tab)

    def _archive_completed_run(self):
        if getattr(self, "_archive_done", False):
            return
        self._archive_done = True

        # Motion-only commissioning is not a photometric result set.
        if getattr(self, "_archive_motion_only", False):
            return

        all_results = getattr(self.host_window, "measurement_results", [])
        start_index = int(getattr(self, "_archive_results_index", 0))
        raw_results = list(all_results[start_index:])
        if not raw_results:
            return

        started_at = getattr(
            self,
            "_archive_started_wall",
            datetime.now().astimezone(),
        )
        started_monotonic = float(
            getattr(self, "_archive_started_monotonic", time.monotonic())
        )
        duration_s = max(0.0, time.monotonic() - started_monotonic)

        home_error = getattr(self, "_home_return_failed", None)
        home_status = (
            f"Warning — {home_error}"
            if home_error
            else "C and Gamma Home verified"
        )

        run = build_measurement_run(
            self.host_window,
            raw_results,
            started_at=started_at,
            duration_s=duration_s,
            execution_mode=getattr(self, "_archive_execution_mode", "Measurement"),
            home_status=home_status,
        )

        try:
            save_measurement_run_csv(run)
        except Exception as exc:
            # The completed measurements remain available in memory/Results even
            # if Windows denies the automatic CSV write for any reason.
            run.save_error = str(exc)

        runs = getattr(self.host_window, "measurement_runs", None)
        if runs is None:
            runs = []
            self.host_window.measurement_runs = runs
        runs.append(run)
        self.host_window.latest_measurement_run = run

        results_workspace = getattr(
            self.host_window,
            "results_workspace_controller",
            None,
        )
        if results_workspace is not None:
            results_workspace.set_run(run)

        _show_complete_dialog(self, run)

    def patched_restore_after_worker(self):
        original_restore_after_worker(self)

        # First return from the measurement worker may have launched the Home
        # worker.  Archive only after that worker has also finished.
        if getattr(self, "_home_return_in_progress", False):
            return
        if self.active_worker is not None:
            return
        if not getattr(self, "run_finished_normally", False):
            return

        _archive_completed_run(self)

    TestPlanWorkspace._begin_run = patched_begin_run
    TestPlanWorkspace._restore_after_worker = patched_restore_after_worker
