"""Test Plan reuse cleanup and Virtual Hardware ETA refinement.

Two deliberately narrow behaviours live here:
1. Building a new plan clears/hides the completed Live Measurement Run panel so
   stale point counts and progress never crowd the next plan.
2. Virtual Hardware uses a virtual timing model.  Mechanical travel is
   intentionally near-instant in the simulator, so the physical servo motion
   estimator must not be included in its initial ETA.

Real-hardware ETA remains unchanged and continues to use the physical/adaptive
runtime model.
"""

from __future__ import annotations

from machine_config import VIRTUAL_HARDWARE
from test_plan_workspace import INTER_SAMPLE_DELAY_MS, TestPlanWorkspace
from test_plan_runtime_improvements import (
    FORMAL_MEASUREMENT_SETUP_S,
    MEASUREMENT_QUERY_OVERHEAD_S,
)


VIRTUAL_ETA_MARGIN_FACTOR = 1.02
VIRTUAL_POINT_UI_OVERHEAD_S = 0.01


def install_test_plan_reuse_eta_refinement():
    if getattr(TestPlanWorkspace, "_reuse_eta_refinement_installed", False):
        return
    TestPlanWorkspace._reuse_eta_refinement_installed = True

    previous_init = TestPlanWorkspace.__init__
    previous_step_estimate = TestPlanWorkspace._step_estimate_seconds

    def refined_init(self, *args, **kwargs):
        previous_init(self, *args, **kwargs)

        def reset_completed_run_for_new_plan(*_args):
            worker = getattr(self, "active_worker", None)
            if worker is not None and worker.isRunning():
                return

            self.run_clock.stop()
            self.run_started_at = 0.0
            self.run_total = 0
            self.run_completed = 0
            self.run_initial_estimate_s = 0.0
            self.run_finished_normally = False
            self.paused = False

            self.run_status_label.setText("Ready")
            self.run_point_label.setText("—")
            self.run_target_label.setText("—")
            self.run_live_angle_label.setText("—")
            self.run_photometry_label.setText("—")
            self.run_completed_label.setText("0")
            self.run_remaining_label.setText("0")
            self.run_elapsed_label.setText("0 s")
            self.run_eta_label.setText("—")

            # Progress refinements use a 0..1000 range; legacy workspace uses
            # point count.  Reset to the active range without assuming either.
            self.run_progress.setValue(self.run_progress.minimum())
            self.run_box.hide()

            # Reset adaptive runtime fields when that refinement is installed.
            if hasattr(self, "_adaptive_active_elapsed_s"):
                self._adaptive_active_elapsed_s = 0.0
                self._adaptive_last_tick = 0.0
                self._adaptive_model_remaining_s = 0.0
                self._adaptive_last_completion_active_s = 0.0
                self._adaptive_completed_intervals = []
                self._adaptive_progress_value = 0
                self._adaptive_home_started_active_s = None

            self.plan_table.updateGeometry()
            self.execution_box.updateGeometry()
            self.centralWidget().updateGeometry()

        # The workspace Rebuild button forwards to this source Build button, so
        # one hook covers rebuilding from either Measurement or Test Plan view.
        self.build_button.clicked.connect(reset_completed_run_for_new_plan)
        self._reset_completed_run_for_new_plan = reset_completed_run_for_new_plan

    def refined_step_estimate_seconds(self, point_count, motion_only=False):
        if not VIRTUAL_HARDWARE:
            return previous_step_estimate(
                self,
                point_count,
                motion_only=motion_only,
            )

        count = max(0, int(point_count))
        if count <= 0:
            return 0.0

        settle_s = max(0.0, self.host_window.measurement_settle_spin.value())
        total = count * (settle_s + VIRTUAL_POINT_UI_OVERHEAD_S)

        if not motion_only:
            samples = max(1, self.host_window.measurement_samples_spin.value())
            integration_s = max(
                0.0,
                self.host_window.measurement_integration_spin.value() / 1000.0,
            )
            sample_block_s = samples * (
                integration_s + MEASUREMENT_QUERY_OVERHEAD_S
            )
            if samples > 1:
                sample_block_s += (
                    samples - 1
                ) * (INTER_SAMPLE_DELAY_MS / 1000.0)
            total += count * sample_block_s
            total += FORMAL_MEASUREMENT_SETUP_S

        return total * VIRTUAL_ETA_MARGIN_FACTOR

    TestPlanWorkspace.__init__ = refined_init
    TestPlanWorkspace._step_estimate_seconds = refined_step_estimate_seconds
