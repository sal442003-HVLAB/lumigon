"""Safety refinements for the full P-9710 MIOL scan.

This module patches only the adaptive trigger/range behaviour used by the
full-grid MIOL workflow.  It deliberately keeps the proven single-plane and
manual P-9710 paths unchanged.

Key rules:
- A dark/off-state ?32 during flash search is treated as a valid baseline state,
  not as an immediate reason to jump to a more sensitive range.
- Range changes during flash search are limited to one step at a time.
- GP never changes the next point's starting range by itself; GP remains a
  diagnostic/warning quantity.
- A more sensitive range is tried only after a complete search window produced
  no reliable rising edge on the current range.
- Once the edge is found, the selected range stays fixed for the MI capture.
"""

from __future__ import annotations

import math
import statistics
import time

from p9710 import P9710, P9710Error
from p9710_miol_grid_runtime import P9710MIOLGridWorker


MIN_RISE_LX = 0.002
NOISE_MULTIPLIER = 6.0
CONFIRM_FRACTION = 0.40
MIN_RANGE_WINDOW_S = 4.5


def _safe_detect_reference_flash_adaptive(
    self: P9710,
    *,
    start_range_id: int = 5,
    timeout_s: float = 12.0,
    gp_low_pct: float = 15.0,
    gp_high_pct: float = 85.0,
):
    """Find a real rising edge without letting dark-state underload force R7.

    ``gp_low_pct`` and ``gp_high_pct`` are accepted for API compatibility but
    intentionally do not cause a range change.  GP is returned as diagnostics.
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

        # Give the current range enough time to see at least one normal flash
        # cycle in the present laboratory setup before considering more gain.
        range_window_s = min(MIN_RANGE_WINDOW_S, remaining_total)
        range_deadline = time.perf_counter() + range_window_s

        history: list[float] = []
        last_value = 0.0
        last_time = None
        candidate = None
        saw_any_valid = False
        saw_underload = False
        restart_with_new_range = False

        while time.perf_counter() < range_deadline:
            try:
                value, _raw, t1, t2 = self.read_mv()
            except P9710Error as exc:
                status = self._status_code(exc)
                last_error = exc

                if status == "underload":
                    # During a flashing source the OFF interval can legitimately
                    # under-range. Treat it as a near-zero baseline sample.
                    saw_underload = True
                    history.append(0.0)
                    if len(history) > 12:
                        history.pop(0)
                    last_value = 0.0
                    last_time = time.perf_counter()
                    candidate = None
                    continue

                if status == "overload" and range_id > 0:
                    # Genuine overload: one step less sensitive, then reacquire
                    # the same point from scratch.
                    range_id -= 1
                    restart_with_new_range = True
                    break

                raise

            t_mid = (t1 + t2) / 2.0
            if not math.isfinite(value):
                continue

            saw_any_valid = True
            recent = history[-8:]
            baseline = statistics.median(recent) if recent else 0.0
            if recent:
                deviations = [abs(v - baseline) for v in recent]
                noise = statistics.median(deviations) if deviations else 0.0
            else:
                noise = 0.0
            rise_floor = max(MIN_RISE_LX, NOISE_MULTIPLIER * noise)

            # Confirm a candidate on the following valid sample. This rejects a
            # single serial/noise spike from becoming the timing reference.
            if candidate is not None:
                edge_time, candidate_value, candidate_baseline, candidate_floor = candidate
                confirm_level = max(
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

            rising = (
                value > last_value
                and value - baseline >= rise_floor
            )
            if saw_underload and value >= rise_floor:
                rising = True

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

        # No reliable edge on this range. Only now, after a full search window,
        # is one step more sensitivity allowed. This prevents dark ?32 samples
        # from causing an immediate R5 -> R6 -> R7 cascade.
        if range_id < 7:
            range_id += 1
            continue
        break

    detail = ""
    if last_error is not None:
        detail = f" Last instrument status: {last_error}."
    raise P9710Error(
        "No reliable rising edge was detected after guarded one-step range search."
        f"{detail} Check that the source is flashing and that the detector receives modulated light."
    )


def _keep_selected_range(selected_range: int, gp_pct):
    """Do not let GP alone change the next point's starting range."""

    del gp_pct
    return max(0, min(7, int(selected_range)))


def install_p9710_fullscan_safety():
    """Install guarded adaptive trigger/range logic for the full MIOL scan."""

    P9710.detect_reference_flash_adaptive = _safe_detect_reference_flash_adaptive
    P9710MIOLGridWorker._next_range = staticmethod(_keep_selected_range)
