"""Smooth Test Plan progress and adaptive remaining-time estimation.

This refinement deliberately sits above ``test_plan_runtime_improvements`` so
we can keep the measurement/motion workers unchanged.  Progress is presented
as one continuous 0..100 % run, including automatic Return Home, while ETA is
allowed to learn from the actual point cadence instead of blindly counting an
initial estimate down to zero.
"""

from __future__ import annotations

import time

from test_plan_workspace import TestPlanWorkspace, _format_duration


PROGRESS_SCALE = 1000          # 0.1 % internal resolution
POINT_PHASE_FRACTION = 0.97    # reserve final 3 % for automatic Return Home
MIN_ACTIVE_ETA_S = 1.0
MIN_HOME_RESERVE_S = 2.0
MAX_HOME_RESERVE_S = 12.0


def install_run_progress_refinement():
    if getattr(TestPlanWorkspace, "_run_progress_refinement_installed", False):
        return
    TestPlanWorkspace._run_progress_refinement_installed = True

    previous_init = TestPlanWorkspace.__init__
    previous_begin_run = TestPlanWorkspace._begin_run
    previous_set_completed = TestPlanWorkspace._set_run_completed
    previous_restore = TestPlanWorkspace._restore_after_worker

    def refined_init(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)

        # A fast GUI-only refresh makes the bar visibly continuous without
        # increasing any hardware polling rate.
        self.run_clock.setInterval(100)
        self.run_progress.setObjectName("measurementRunProgress")
        self.run_progress.setRange(0, PROGRESS_SCALE)
        self.run_progress.setValue(0)
        self.run_progress.setFormat("Progress  %p%")
        self.run_progress.setTextVisible(True)
        self.run_progress.setStyleSheet(
            """
            QProgressBar#measurementRunProgress {
                border: 1px solid #365463;
                border-radius: 6px;
                background-color: #101C24;
                color: #EAF9FC;
                text-align: center;
                min-height: 24px;
                font-weight: 700;
            }
            QProgressBar#measurementRunProgress::chunk {
                background-color: #20A9C7;
                border-radius: 5px;
            }
            """
        )

        self._adaptive_active_elapsed_s = 0.0
        self._adaptive_last_tick = 0.0
        self._adaptive_model_remaining_s = 0.0
        self._adaptive_last_completion_active_s = 0.0
        self._adaptive_completed_intervals = []
        self._adaptive_progress_value = 0
        self._adaptive_home_started_active_s = None
        self._adaptive_home_reserve_s = MIN_HOME_RESERVE_S

    def refined_begin_run(self, *, mode_text, total, estimate_s, motion_only):
        previous_begin_run(
            self,
            mode_text=mode_text,
            total=total,
            estimate_s=estimate_s,
            motion_only=motion_only,
        )

        now = time.monotonic()
        self._adaptive_active_elapsed_s = 0.0
        self._adaptive_last_tick = now
        self._adaptive_model_remaining_s = max(0.0, float(estimate_s))
        self._adaptive_last_completion_active_s = 0.0
        self._adaptive_completed_intervals = []
        self._adaptive_progress_value = 0
        self._adaptive_home_started_active_s = None
        self._adaptive_home_reserve_s = min(
            MAX_HOME_RESERVE_S,
            max(MIN_HOME_RESERVE_S, float(estimate_s) * 0.06),
        )

        self.run_progress.setRange(0, PROGRESS_SCALE)
        self.run_progress.setValue(0)
        self.run_progress.setFormat("Progress  %p%")

    def _learned_point_seconds(self):
        intervals = [v for v in self._adaptive_completed_intervals if v > 0.05]
        if intervals:
            # Recent points describe current hardware conditions better, while a
            # short history prevents one slow serial transaction from dominating.
            recent = intervals[-5:]
            return sum(recent) / len(recent)

        point_budget = max(
            0.0,
            self.run_initial_estimate_s - self._adaptive_home_reserve_s,
        )
        return max(0.25, point_budget / max(1, self.run_total))

    def refined_set_completed(self, completed):
        old_completed = int(getattr(self, "run_completed", 0))
        previous_set_completed(self, completed)
        new_completed = int(getattr(self, "run_completed", 0))

        if new_completed > old_completed:
            active_now = float(self._adaptive_active_elapsed_s)
            interval = active_now - float(self._adaptive_last_completion_active_s)
            if interval > 0.05:
                # If several points are reported together, distribute the period
                # rather than treating the whole block as one point.
                gained = max(1, new_completed - old_completed)
                per_point = interval / gained
                self._adaptive_completed_intervals.extend([per_point] * gained)
            self._adaptive_last_completion_active_s = active_now

    def refined_refresh_run_clock(self):
        if self.run_started_at <= 0:
            return

        now = time.monotonic()
        wall_elapsed = max(0.0, now - self.run_started_at)
        last_tick = self._adaptive_last_tick or now
        delta = max(0.0, now - last_tick)
        self._adaptive_last_tick = now

        if not self.paused:
            self._adaptive_active_elapsed_s += delta
            self._adaptive_model_remaining_s = max(
                0.0,
                self._adaptive_model_remaining_s - delta,
            )

        remaining_points = max(0, self.run_total - self.run_completed)
        point_seconds = _learned_point_seconds(self)

        # Actual cadence is a lower bound on the remaining work.  Keep the
        # original physics-based estimate as another lower bound.  This allows
        # ETA to extend itself when the real system is slower than the model.
        cadence_remaining = remaining_points * point_seconds
        if remaining_points > 0:
            cadence_remaining += self._adaptive_home_reserve_s
        elif self._home_return_in_progress:
            cadence_remaining = self._adaptive_home_reserve_s
        else:
            cadence_remaining = 0.0

        eta = max(self._adaptive_model_remaining_s, cadence_remaining)

        run_still_active = bool(
            self.run_completed < self.run_total
            or self._home_return_in_progress
            or (
                self.active_worker is not None
                and self.active_worker.isRunning()
            )
        )
        if run_still_active:
            eta = max(MIN_ACTIVE_ETA_S, eta)

        self._eta_remaining_s = eta
        self.run_elapsed_label.setText(_format_duration(wall_elapsed))
        self.run_eta_label.setText(_format_duration(eta))

        # Smooth point-phase interpolation.  A completed-point event establishes
        # the floor; the 100 ms GUI timer then advances toward the next point.
        if self.run_completed < self.run_total:
            since_completion = max(
                0.0,
                self._adaptive_active_elapsed_s
                - self._adaptive_last_completion_active_s,
            )
            fractional_point = min(0.95, since_completion / max(0.25, point_seconds))
            point_fraction = (
                self.run_completed + fractional_point
            ) / max(1, self.run_total)
            target_fraction = min(
                POINT_PHASE_FRACTION,
                point_fraction * POINT_PHASE_FRACTION,
            )
        else:
            target_fraction = POINT_PHASE_FRACTION

        # Automatic Home occupies the final 3 %, so 100 % means operationally
        # complete rather than merely "last photometric point acquired".
        if self._home_return_in_progress:
            if self._adaptive_home_started_active_s is None:
                self._adaptive_home_started_active_s = self._adaptive_active_elapsed_s
            home_elapsed = max(
                0.0,
                self._adaptive_active_elapsed_s
                - self._adaptive_home_started_active_s,
            )
            home_fraction = min(
                0.95,
                home_elapsed / max(MIN_HOME_RESERVE_S, self._adaptive_home_reserve_s),
            )
            target_fraction = POINT_PHASE_FRACTION + (
                (1.0 - POINT_PHASE_FRACTION) * home_fraction
            )

        target_value = int(round(target_fraction * PROGRESS_SCALE))
        # Never move backwards if ETA adapts upward.  Never display 100 % until
        # the worker/Home cleanup confirms that the complete run is finished.
        if run_still_active:
            target_value = min(PROGRESS_SCALE - 1, target_value)
        self._adaptive_progress_value = max(
            int(self._adaptive_progress_value),
            target_value,
        )
        self.run_progress.setValue(self._adaptive_progress_value)

    def refined_restore_after_worker(self):
        previous_restore(self)

        # The first restore call may have launched ReturnHomeWorker; only the
        # second/final restore is allowed to declare 100 %.
        if (
            self.run_finished_normally
            and not self._home_return_in_progress
            and self.active_worker is None
        ):
            self._adaptive_progress_value = PROGRESS_SCALE
            self.run_progress.setValue(PROGRESS_SCALE)
            self._eta_remaining_s = 0.0
            self.run_eta_label.setText("0 s")

    TestPlanWorkspace.__init__ = refined_init
    TestPlanWorkspace._begin_run = refined_begin_run
    TestPlanWorkspace._set_run_completed = refined_set_completed
    TestPlanWorkspace._refresh_run_clock = refined_refresh_run_clock
    TestPlanWorkspace._restore_after_worker = refined_restore_after_worker
