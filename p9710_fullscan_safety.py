"""Safety and scan refinements for the full P-9710 MIOL scan.

This module patches only the adaptive trigger/range behaviour used by the
full-grid MIOL workflow and the C-plane generation used by that workflow.
The manual/single-plane P-9710 paths remain unchanged.

Full-scan rules:
- dark/off-state ?32 is a valid OFF baseline, not a reason to jump to R7;
- range changes are one step at a time and only after a complete search window;
- GP is diagnostic only and never changes range by itself;
- rising-edge timing prefers a real OFF -> ON transition and confirms the pulse
  with a second valid sample;
- tiny sub-0.05 lx noise excursions are never accepted as an ON pulse;
- selected range is locked for MI;
- an MI result that is essentially zero despite a clearly detected flash is
  rejected and the same point is reacquired once instead of writing a false zero;
- when the requested C range crosses zero, C planes are anchored at 0 degrees;
- the outer C plane is the largest exact step multiple inside the requested
  envelope (for example ±45 with 10-degree planes becomes ±40);
- default C-plane spacing is 5 degrees and default distance is 5.00 m.
"""

from __future__ import annotations

import math
import statistics
import time

import p9710_miol_grid_runtime as grid_runtime
from p9710 import P9710, P9710Error
from p9710_miol_grid_runtime import P9710MIOLGridWorker


MIN_RISE_LX = 0.002
MIN_VALID_ON_LX = 0.05
NOISE_MULTIPLIER = 8.0
RELATIVE_RISE_FRACTION = 0.05
CONFIRM_FRACTION = 0.50
MIN_RANGE_WINDOW_S = 4.5
MISSED_MI_RATIO = 0.02
MISSED_MI_ABS_LX = 0.002

DEFAULT_C_PLANE_STEP_DEG = 5.0
DEFAULT_MEASUREMENT_DISTANCE_M = 5.00

_ORIGINAL_SYNC_ADAPTIVE = P9710.synchronized_effective_adaptive
_ORIGINAL_BUILD_GRID = grid_runtime._build_grid


def _safe_detect_reference_flash_adaptive(
    self: P9710,
    *,
    start_range_id: int = 5,
    timeout_s: float = 12.0,
    gp_low_pct: float = 15.0,
    gp_high_pct: float = 85.0,
):
    """Find a real flash edge with conservative range selection.

    The strongest timing cue is an instrument under-range during the OFF phase
    followed by two valid ON samples. If the baseline is already measurable,
    a statistically and relatively significant positive rise is required.
    GP is returned for diagnostics only.
    """

    del gp_low_pct, gp_high_pct

    range_id = max(0, min(7, int(start_range_id)))
    timeout_s = max(MIN_RANGE_WINDOW_S, float(timeout_s))
    global_deadline = time.perf_counter() + timeout_s
    last_error = None

    while time.perf_counter() < global_deadline:
        self.configure_flash_detection(range_id=range_id)
        remaining_total = global_deadline - time.perf_counter()
        if remaining_total <= 0.0:
            break

        range_window_s = min(MIN_RANGE_WINDOW_S, remaining_total)
        range_deadline = time.perf_counter() + range_window_s

        history: list[float] = []
        last_value = None
        last_time = None
        candidate = None
        saw_off_state = False
        restart_with_new_range = False

        while time.perf_counter() < range_deadline:
            try:
                value, _raw, t1, t2 = self.read_mv()
            except P9710Error as exc:
                status = self._status_code(exc)
                last_error = exc

                if status == "underload":
                    saw_off_state = True
                    history.append(0.0)
                    if len(history) > 12:
                        history.pop(0)
                    last_value = 0.0
                    last_time = time.perf_counter()
                    candidate = None
                    continue

                if status == "overload" and range_id > 0:
                    range_id -= 1
                    restart_with_new_range = True
                    break

                raise

            t_mid = (t1 + t2) / 2.0
            if not math.isfinite(value):
                continue

            recent = history[-8:]
            baseline = statistics.median(recent) if recent else 0.0
            deviations = [abs(v - baseline) for v in recent] if recent else []
            noise = statistics.median(deviations) if deviations else 0.0
            rise_floor = max(
                MIN_RISE_LX,
                NOISE_MULTIPLIER * noise,
                abs(baseline) * RELATIVE_RISE_FRACTION,
            )

            if candidate is not None:
                edge_time, candidate_value, candidate_baseline, candidate_floor = candidate
                confirm_level = max(
                    MIN_VALID_ON_LX,
                    candidate_baseline + 0.5 * candidate_floor,
                    CONFIRM_FRACTION * candidate_value,
                )
                if value >= confirm_level:
                    try:
                        gp = self.read_range_utilization()
                    except Exception:
                        gp = None
                    return edge_time, max(candidate_value, value), range_id, gp
                candidate = None

            if saw_off_state:
                rising = value >= max(MIN_VALID_ON_LX, rise_floor)
            else:
                rising = (
                    last_value is not None
                    and value >= MIN_VALID_ON_LX
                    and value > last_value
                    and value - baseline >= rise_floor
                )

            if rising:
                edge_time = t_mid if last_time is None else (last_time + t_mid) / 2.0
                candidate = (edge_time, value, baseline, rise_floor)

            history.append(value)
            if len(history) > 12:
                history.pop(0)
            last_value = value
            last_time = t_mid

        if restart_with_new_range:
            continue

        if range_id < 7:
            range_id += 1
            continue
        break

    detail = ""
    if last_error is not None:
        detail = f" Last instrument status: {last_error}."
    raise P9710Error(
        "No reliable OFF-to-ON flash edge was detected after guarded one-step range search."
        f"{detail} Check source flashing, detector alignment, and signal level."
    )


def _verified_synchronized_effective_adaptive(self: P9710, **kwargs):
    """Acquire MI and reject a clearly missed pulse instead of saving ~zero."""

    last = None
    for attempt in range(2):
        reading = _ORIGINAL_SYNC_ADAPTIVE(self, **kwargs)
        last = reading
        floor = max(MISSED_MI_ABS_LX, abs(reading.trigger_sample_lx) * MISSED_MI_RATIO)
        if reading.e_effective_lx > floor:
            return reading
        if attempt == 0:
            time.sleep(0.05)

    raise P9710Error(
        "MI capture was near zero twice despite a detected flash. "
        f"Last E-effective={last.e_effective_lx:.6g} lx, "
        f"trigger sample={last.trigger_sample_lx:.6g} lx. "
        "Point rejected instead of writing a false zero."
    )


def _keep_selected_range(selected_range: int, gp_pct):
    """Keep the proven range for the next nearby point; GP is diagnostic only."""

    del gp_pct
    return max(0, min(7, int(selected_range)))


def _zero_anchored_c_values(start: float, end: float, step: float):
    """Generate C planes on an exact step grid anchored at 0 degrees.

    When the requested interval crosses zero, 0 degrees is always the first C
    plane. Subsequent positive planes are contiguous, followed by negative
    planes. Endpoints that are not exact step multiples are intentionally not
    added. Thus a ±45-degree envelope with 10-degree spacing uses ±40 degrees,
    while 5-degree spacing reaches ±45 degrees exactly.

    For one-sided scans that do not cross zero, the original axis generator is
    retained so custom engineering scans keep their established behaviour.
    """

    start = float(start)
    end = float(end)
    step = abs(float(step))
    if step <= 0.0:
        raise ValueError("C-plane step must be greater than zero.")

    lower = min(start, end)
    upper = max(start, end)
    epsilon = max(1e-9, step * 1e-6)

    if lower > epsilon or upper < -epsilon:
        return grid_runtime._axis_values(start, end, step)

    positive_count = int(math.floor((max(0.0, upper) + epsilon) / step))
    negative_count = int(math.floor((max(0.0, -lower) + epsilon) / step))

    positive = [round(index * step, 6) for index in range(1, positive_count + 1)]
    negative = [round(-index * step, 6) for index in range(1, negative_count + 1)]

    if start <= end:
        return [0.0, *positive, *negative]
    return [0.0, *negative, *positive]


def _build_zero_anchored_grid(
    c_start,
    c_end,
    c_step,
    gamma_start,
    gamma_end,
    gamma_step,
):
    """Build the MIOL grid with zero-anchored C planes and Gamma serpentine."""

    c_values = _zero_anchored_c_values(c_start, c_end, c_step)
    gamma_values = grid_runtime._axis_values(gamma_start, gamma_end, gamma_step)
    points = []
    for plane_index, c_deg in enumerate(c_values):
        sweep = gamma_values if plane_index % 2 == 0 else reversed(gamma_values)
        points.extend((c_deg, gamma_deg) for gamma_deg in sweep)
    return points


def install_p9710_fullscan_safety():
    """Install guarded acquisition plus zero-anchored C-plane generation."""

    P9710.detect_reference_flash_adaptive = _safe_detect_reference_flash_adaptive
    P9710.synchronized_effective_adaptive = _verified_synchronized_effective_adaptive
    P9710MIOLGridWorker._next_range = staticmethod(_keep_selected_range)

    # These globals are read by attach_p9710_miol_grid_runtime() when the
    # Measurement controls are created, so changing them here updates the visible
    # defaults without changing the standalone/manual P-9710 workspaces.
    grid_runtime.DEFAULT_C_STEP_DEG = DEFAULT_C_PLANE_STEP_DEG
    grid_runtime.DEFAULT_DISTANCE_M = DEFAULT_MEASUREMENT_DISTANCE_M
    grid_runtime._build_grid = _build_zero_anchored_grid
