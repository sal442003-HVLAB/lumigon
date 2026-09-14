"""Bridge completed P-9710 MIOL scans into the Results workspace.

The MIOL acquisition writer uses its own compact CSV schema.  The Results loader
normalizes that schema into MeasurementRun.  This bridge makes the handoff
automatic at the end of a successful run, so the operator can switch to Results
and analyse the just-completed scan without manually browsing for the CSV.
"""

from __future__ import annotations

from measurement_run_io import load_measurement_run_csv
from miol_zero_plane_results_patch import install_miol_zero_plane_results_patch
from p9710_miol_grid_runtime import P9710MIOLGridWorker


_INSTALLED = False
_ORIGINAL_INIT = None


def _publish_run(window, path):
    try:
        run = load_measurement_run_csv(path)
    except Exception as exc:
        # Acquisition has already completed successfully; a Results import
        # problem must not invalidate or delete the measurement CSV.
        window.p9710_results_import_error = str(exc)
        return

    runs = getattr(window, "measurement_runs", None)
    if runs is None:
        runs = []
        window.measurement_runs = runs
    runs.append(run)
    window.latest_measurement_run = run
    window.p9710_results_import_error = None

    controller = getattr(window, "results_workspace_controller", None)
    if controller is not None:
        controller.set_run(run)


def install_p9710_results_bridge():
    """Connect future P9710MIOLGridWorker completions to Results automatically."""
    global _INSTALLED, _ORIGINAL_INIT
    if _INSTALLED:
        return

    # Install MIOL scan/result refinements before any Measurement run is built.
    install_miol_zero_plane_results_patch()

    _ORIGINAL_INIT = P9710MIOLGridWorker.__init__

    def patched_init(self, *args, **kwargs):
        _ORIGINAL_INIT(self, *args, **kwargs)
        window = kwargs.get("parent")
        if window is None:
            return

        def on_completed(path):
            _publish_run(window, path)

        self.completed.connect(on_completed)

    P9710MIOLGridWorker.__init__ = patched_init
    _INSTALLED = True
