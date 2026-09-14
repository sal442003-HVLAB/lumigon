"""Safety refinements for the full P-9710 MIOL scan.

This module patches only the adaptive trigger/range behaviour used by the
full-grid MIOL workflow. The manual/single-plane P-9710 paths remain unchanged.

Full-scan rules:
- dark/off-state ?32 is a valid OFF baseline, not a reason to jump to R7;
- range changes are one step at a time and only after a complete search window;
- GP is diagnostic only and never changes range by itself;
- rising-edge timing prefers a real OFF -> ON transition and confirms the pulse
  with a second valid sample;
- selected range is locked for MI;
- an MI result that is essentially zero despite a clearly detected flash is
  rejected and the same point is reacquired once instead of writing a false zero.
"""

from __future__ import annotations

import math
import statistics
import time

from p9710 import P9710, P9710Error
from p9710_miol_grid_runtime import P9710MIOLGridWorker


MIN_RISE_LX = 0.002
NOISE_MULTIPLIER = 8.0
RELATIVE_RISE_FRACTION = 0.05
CONFIRM_FRACTION = 0.50
MIN_RANGE_WINDOW_S = 4.5
MISSED_MI_RATIO = 0.02
MISSED_MI_ABS_LX = 0.002

_ORIGINAL_SYNC_ADAPTIVE = P9710.synchronized_effective_adaptive


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
                    # Normal OFF phase for a flashing source. Do not change range.
                    saw_off_state = True
                    history.append(0.0)
                    if len(history) > 12:
                        history.pop(0)
                    last_value = 0.0
                    last_time = time.perf_counter()
                    candidate = None
                    continue

                if status == "overload" and range_id > 0:
                    # ON pulse really overloads this range: one step less sensitive.
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

            # Candidate must survive one following valid sample. This is the key
            # guard against noise/spikes being used as the timing reference.
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

            # Preferred case: we have explicitly seen the OFF state and now see
            # a valid positive sample. Otherwise use a conservative baseline rise.
            if saw_off_state:
                rising = value >= rise_floor
            else:
                rising = (
                    last_value is not None
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

        # Only after an entire range window failed do we try one more-sensitive
        # range. This prevents an OFF-state ?32 from cascading R5 -> R6 -> R7.
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
    """Acquire MI and reject a clearly missed pulse instead of saving ~zero.

    For the present MIOL workflow a detected flash followed by an MI result below
    both an absolute floor and 2% of the trigger sample is almost certainly a
    timing miss. Reacquire the same angular point once from a fresh reference
    flash. No averaging or interpolation is used.
    """

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


def install_p9710_fullscan_safety():
    """Install guarded trigger/range and missed-capture protection."""

    P9710.detect_reference_flash_adaptive = _safe_detect_reference_flash_adaptive
    P9710.synchronized_effective_adaptive = _verified_synchronized_effective_adaptive
    P9710MIOLGridWorker._next_range = staticmethod(_keep_selected_range)
