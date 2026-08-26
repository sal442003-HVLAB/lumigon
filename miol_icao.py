"""ICAO Annex 14 Medium-Intensity Obstacle Light (MIOL) analysis.

This module contains only standards/profile mathematics and is deliberately
independent of Qt. Lumigon uses it for profile configuration, flashing-light
effective-intensity capture, and Results compliance reporting.

Reference basis:
- ICAO Annex 14, Volume I, 9th Edition (2022), Chapter 6, Tables 6-1 and 6-3.
- ICAO Doc 9157, Aerodrome Design Manual, Part 4, 5th Edition (2021),
  section 19.3 for flashing-light effective intensity (Blondel-Rey method).

Lumigon mechanical convention currently has positive Gamma downward. ICAO
vertical elevation is positive upward, therefore ICAO elevation = -Gamma.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import statistics
from typing import Iterable, Optional, Sequence


ICAO_REFERENCE = (
    "ICAO Annex 14, Volume I, 9th Ed. (2022), Chapter 6, Tables 6-1 & 6-3"
)
BLONDEL_REY_A_S = 0.2
ICAO_ELEVATION_GAMMA_SIGN = -1.0


@dataclass(frozen=True)
class MiolBenchmark:
    nominal_cd: float
    min_average_0_cd: float
    min_0_cd: float
    min_minus1_cd: float
    min_beam_spread_deg: float
    beam_threshold_cd: float
    rec_max_0_cd: float
    rec_max_minus1_cd: float
    rec_max_minus10_cd: float


BENCHMARK_2000 = MiolBenchmark(
    nominal_cd=2000.0,
    min_average_0_cd=2000.0,
    min_0_cd=1500.0,
    min_minus1_cd=750.0,
    min_beam_spread_deg=3.0,
    beam_threshold_cd=750.0,
    rec_max_0_cd=2500.0,
    rec_max_minus1_cd=1125.0,
    rec_max_minus10_cd=75.0,
)

BENCHMARK_20000 = MiolBenchmark(
    nominal_cd=20000.0,
    min_average_0_cd=20000.0,
    min_0_cd=15000.0,
    min_minus1_cd=7500.0,
    min_beam_spread_deg=3.0,
    beam_threshold_cd=7500.0,
    rec_max_0_cd=25000.0,
    rec_max_minus1_cd=11250.0,
    rec_max_minus10_cd=750.0,
)


@dataclass(frozen=True)
class MiolProfileSpec:
    type_code: str
    display_name: str
    colour: str
    flashing: bool
    flash_rate_min_fpm: Optional[float]
    flash_rate_max_fpm: Optional[float]
    allowed_conditions: tuple[str, ...]


MIOL_PROFILES = {
    "A": MiolProfileSpec(
        type_code="A",
        display_name="MIOL Type A",
        colour="White",
        flashing=True,
        flash_rate_min_fpm=20.0,
        flash_rate_max_fpm=60.0,
        allowed_conditions=("Day", "Twilight", "Night"),
    ),
    "B": MiolProfileSpec(
        type_code="B",
        display_name="MIOL Type B",
        colour="Red",
        flashing=True,
        flash_rate_min_fpm=20.0,
        flash_rate_max_fpm=60.0,
        allowed_conditions=("Night",),
    ),
    "C": MiolProfileSpec(
        type_code="C",
        display_name="MIOL Type C",
        colour="Red",
        flashing=False,
        flash_rate_min_fpm=None,
        flash_rate_max_fpm=None,
        allowed_conditions=("Night",),
    ),
}


@dataclass(frozen=True)
class EffectiveIntensityResult:
    effective_value: float
    peak_value: float
    baseline_value: float
    interval_start_s: float
    interval_end_s: float
    interval_duration_s: float
    sample_count: int


@dataclass(frozen=True)
class ComplianceRow:
    item: str
    measured: str
    requirement: str
    status: str
    mandatory: bool = True


@dataclass(frozen=True)
class MiolComplianceResult:
    profile_type: str
    condition: str
    intensity_basis: str
    benchmark: MiolBenchmark
    c_coverage_deg: float
    full_360: bool
    rows: tuple[ComplianceRow, ...]
    overall: str
    selected_plane_c_deg: Optional[float]
    plane_i0_cd: Optional[float]
    plane_i_minus1_cd: Optional[float]
    plane_i_minus10_cd: Optional[float]
    plane_beam_spread_deg: Optional[float]


def profile_type_from_text(text: str) -> Optional[str]:
    upper = str(text or "").upper()
    for code in ("A", "B", "C"):
        if f"TYPE {code}" in upper:
            return code
    if "MIOL" in upper:
        # Historical Lumigon development profile migration fallback only.
        return "B"
    return None


def condition_from_standard(text: str, profile_type: str) -> str:
    upper = str(text or "").upper()
    for condition in ("TWILIGHT", "NIGHT", "DAY"):
        if f"CONDITION: {condition}" in upper or f"— {condition}" in upper:
            return condition.title()
    if profile_type == "A":
        return "Day"
    return "Night"


def benchmark_for(profile_type: str, condition: str) -> MiolBenchmark:
    code = str(profile_type).upper()
    cond = str(condition).title()
    if code == "A" and cond in ("Day", "Twilight"):
        return BENCHMARK_20000
    return BENCHMARK_2000


def intensity_basis_for(profile_type: str) -> str:
    spec = MIOL_PROFILES[str(profile_type).upper()]
    return "I-effective (Blondel-Rey)" if spec.flashing else "Steady luminous intensity"


def icao_elevation_from_gamma(gamma_deg: float) -> float:
    return ICAO_ELEVATION_GAMMA_SIGN * float(gamma_deg)


def blondel_rey_effective(
    times_s: Sequence[float],
    values: Sequence[float],
    *,
    a_s: float = BLONDEL_REY_A_S,
    subtract_baseline: bool = True,
) -> EffectiveIntensityResult:
    """Numerically maximize the ICAO/Blondel-Rey effective-intensity equation.

    Ie = integral(I(t) dt) / (0.2 + (t2 - t1))

    The maximization is performed over all measured interval endpoints. This is
    robust for arbitrary pulse shapes and irregular serial-sampling intervals.
    For a flashing source, the off-state baseline is estimated from the lower
    decile and removed before the integral; this rejects ambient/dark offset.
    """

    if a_s <= 0.0:
        raise ValueError("Blondel-Rey a must be positive")
    if len(times_s) != len(values):
        raise ValueError("times and values must have the same length")
    if len(times_s) < 3:
        raise ValueError("at least three temporal samples are required")

    pairs = []
    for t, value in zip(times_s, values):
        try:
            t = float(t)
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(t) and math.isfinite(value):
            pairs.append((t, value))
    if len(pairs) < 3:
        raise ValueError("not enough finite temporal samples")

    pairs.sort(key=lambda item: item[0])
    t0 = pairs[0][0]
    times = [item[0] - t0 for item in pairs]
    raw = [item[1] for item in pairs]

    if times[-1] <= times[0]:
        raise ValueError("temporal sample span must be greater than zero")

    baseline = 0.0
    if subtract_baseline:
        ordered = sorted(raw)
        count = max(1, int(math.ceil(0.10 * len(ordered))))
        baseline = statistics.fmean(ordered[:count])

    signal = [max(0.0, value - baseline) for value in raw]
    peak = max(signal)
    if peak <= 0.0:
        raise ValueError("no positive flash signal was detected")

    cumulative = [0.0] * len(times)
    for index in range(1, len(times)):
        dt = times[index] - times[index - 1]
        if dt <= 0.0:
            cumulative[index] = cumulative[index - 1]
            continue
        cumulative[index] = (
            cumulative[index - 1]
            + 0.5 * (signal[index - 1] + signal[index]) * dt
        )

    best_ie = 0.0
    best_i = 0
    best_j = 1
    for i in range(len(times) - 1):
        for j in range(i + 1, len(times)):
            duration = times[j] - times[i]
            if duration <= 0.0:
                continue
            area = cumulative[j] - cumulative[i]
            ie = area / (a_s + duration)
            if ie > best_ie:
                best_ie = ie
                best_i = i
                best_j = j

    if best_ie <= 0.0:
        raise ValueError("effective intensity could not be resolved from capture")

    return EffectiveIntensityResult(
        effective_value=best_ie,
        peak_value=peak,
        baseline_value=baseline,
        interval_start_s=times[best_i],
        interval_end_s=times[best_j],
        interval_duration_s=times[best_j] - times[best_i],
        sample_count=len(times),
    )


def _interpolate(xs: Sequence[float], ys: Sequence[float], target: float) -> Optional[float]:
    pairs = sorted(
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if math.isfinite(float(x)) and math.isfinite(float(y))
    )
    if not pairs or target < pairs[0][0] or target > pairs[-1][0]:
        return None
    for x, y in pairs:
        if abs(x - target) <= 1e-9:
            return y
    for (x0, y0), (x1, y1) in zip(pairs, pairs[1:]):
        if x0 <= target <= x1 and x1 > x0:
            f = (target - x0) / (x1 - x0)
            return y0 + f * (y1 - y0)
    return None


def _beam_spread(xs: Sequence[float], ys: Sequence[float], threshold: float) -> Optional[float]:
    """Return the widest contiguous angular interval at/above threshold."""

    pairs = sorted(
        (float(x), float(y))
        for x, y in zip(xs, ys)
        if math.isfinite(float(x)) and math.isfinite(float(y))
    )
    if len(pairs) < 2:
        return None

    intervals = []
    active_start = None
    for index, (x, y) in enumerate(pairs):
        above = y >= threshold
        if index == 0:
            if above:
                active_start = x
            continue

        x0, y0 = pairs[index - 1]
        prev_above = y0 >= threshold
        if above == prev_above:
            continue

        if abs(y - y0) < 1e-12:
            crossing = (x0 + x) / 2.0
        else:
            crossing = x0 + (threshold - y0) * (x - x0) / (y - y0)

        if above and not prev_above:
            active_start = crossing
        elif prev_above and not above and active_start is not None:
            intervals.append((active_start, crossing))
            active_start = None

    if active_start is not None:
        intervals.append((active_start, pairs[-1][0]))
    if not intervals:
        return 0.0
    return max(end - start for start, end in intervals)


def _c_coverage(c_values: Iterable[float]) -> tuple[float, bool]:
    values = sorted({float(value) % 360.0 for value in c_values})
    if len(values) < 2:
        return 0.0, False
    gaps = [b - a for a, b in zip(values, values[1:])]
    gaps.append(values[0] + 360.0 - values[-1])
    largest_gap = max(gaps)
    coverage = max(0.0, 360.0 - largest_gap)
    return coverage, coverage >= 350.0


def _series_for_c(points, c_target: float):
    usable = [p for p in points if getattr(p, "candela_cd", None) is not None]
    if not usable:
        return [], []
    c_nearest = min(
        {float(p.c_deg) for p in usable},
        key=lambda value: abs(value - c_target),
    )
    selected = [p for p in usable if abs(float(p.c_deg) - c_nearest) <= 1e-4]
    selected.sort(key=lambda p: icao_elevation_from_gamma(p.gamma_deg))
    return (
        [icao_elevation_from_gamma(p.gamma_deg) for p in selected],
        [float(p.candela_cd) for p in selected],
    )


def analyse_miol_run(run, *, selected_c_deg: Optional[float] = None) -> Optional[MiolComplianceResult]:
    profile_type = profile_type_from_text(getattr(run, "profile", ""))
    if profile_type is None:
        return None

    condition = condition_from_standard(getattr(run, "standard", ""), profile_type)
    benchmark = benchmark_for(profile_type, condition)
    basis = intensity_basis_for(profile_type)

    usable = [
        p for p in getattr(run, "points", [])
        if getattr(p, "candela_cd", None) is not None
    ]
    if not usable:
        return MiolComplianceResult(
            profile_type, condition, basis, benchmark, 0.0, False, tuple(),
            "NO PHOTOMETRIC DATA", None, None, None, None, None,
        )

    c_values = sorted({float(p.c_deg) for p in usable})
    coverage, full_360 = _c_coverage(c_values)
    if selected_c_deg is None:
        selected_c_deg = min(c_values, key=abs)

    elevations, plane_values = _series_for_c(usable, selected_c_deg)
    plane_i0 = _interpolate(elevations, plane_values, 0.0)
    plane_im1 = _interpolate(elevations, plane_values, -1.0)
    plane_im10 = _interpolate(elevations, plane_values, -10.0)
    plane_spread = _beam_spread(
        elevations, plane_values, benchmark.beam_threshold_cd
    )

    rows: list[ComplianceRow] = []

    def local_min_row(name, measured, limit):
        status = "N/E" if measured is None else (
            "LOCAL PASS" if measured >= limit else "LOCAL FAIL"
        )
        rows.append(ComplianceRow(
            name,
            "—" if measured is None else f"{measured:.1f} cd",
            f"≥ {limit:.0f} cd",
            status,
            True,
        ))

    local_min_row("Selected plane intensity @ 0°", plane_i0, benchmark.min_0_cd)
    local_min_row("Selected plane intensity @ -1°", plane_im1, benchmark.min_minus1_cd)

    for name, measured, limit in (
        ("Selected plane intensity @ 0° — recommended max", plane_i0, benchmark.rec_max_0_cd),
        ("Selected plane intensity @ -1° — recommended max", plane_im1, benchmark.rec_max_minus1_cd),
    ):
        status = "N/E" if measured is None else (
            "REC PASS" if measured <= limit else "REC HIGH"
        )
        rows.append(ComplianceRow(
            name,
            "—" if measured is None else f"{measured:.1f} cd",
            f"≤ {limit:.0f} cd (Recommendation)",
            status,
            False,
        ))

    spread_status = "N/E"
    if plane_spread is not None:
        spread_status = (
            "LOCAL PASS"
            if plane_spread >= benchmark.min_beam_spread_deg
            else "LOCAL FAIL"
        )
    rows.append(ComplianceRow(
        "Selected plane vertical beam spread",
        "—" if plane_spread is None else f"{plane_spread:.2f}°",
        f"≥ {benchmark.min_beam_spread_deg:.0f}° at ≥ {benchmark.beam_threshold_cd:.0f} cd",
        spread_status,
        True,
    ))

    rec_status = "N/E" if plane_im10 is None else (
        "REC PASS" if plane_im10 <= benchmark.rec_max_minus10_cd else "REC HIGH"
    )
    rows.append(ComplianceRow(
        "Selected plane intensity @ -10°",
        "—" if plane_im10 is None else f"{plane_im10:.1f} cd",
        f"≤ {benchmark.rec_max_minus10_cd:.0f} cd (Recommendation)",
        rec_status,
        False,
    ))

    c_i0 = []
    c_im1 = []
    c_im10 = []
    for c in c_values:
        xs, ys = _series_for_c(usable, c)
        v0 = _interpolate(xs, ys, 0.0)
        vm1 = _interpolate(xs, ys, -1.0)
        vm10 = _interpolate(xs, ys, -10.0)
        if v0 is not None:
            c_i0.append(v0)
        if vm1 is not None:
            c_im1.append(vm1)
        if vm10 is not None:
            c_im10.append(vm10)

    def full_row(name, measured_value, requirement, pass_test, mandatory=True):
        if not full_360 or measured_value is None:
            measured = f"N/E — C coverage {coverage:.1f}° / 360°"
            status = "N/E"
        else:
            measured = f"{measured_value:.1f} cd"
            if mandatory:
                status = "PASS" if pass_test(measured_value) else "FAIL"
            else:
                status = "REC PASS" if pass_test(measured_value) else "REC HIGH"
        rows.append(ComplianceRow(name, measured, requirement, status, mandatory))

    full_row(
        "360° average intensity @ 0°",
        statistics.fmean(c_i0) if c_i0 else None,
        f"≥ {benchmark.min_average_0_cd:.0f} cd",
        lambda value: value >= benchmark.min_average_0_cd,
    )
    full_row(
        "360° minimum intensity @ 0°",
        min(c_i0) if c_i0 else None,
        f"≥ {benchmark.min_0_cd:.0f} cd",
        lambda value: value >= benchmark.min_0_cd,
    )
    full_row(
        "360° minimum intensity @ -1°",
        min(c_im1) if c_im1 else None,
        f"≥ {benchmark.min_minus1_cd:.0f} cd",
        lambda value: value >= benchmark.min_minus1_cd,
    )
    full_row(
        "360° maximum intensity @ 0°",
        max(c_i0) if c_i0 else None,
        f"≤ {benchmark.rec_max_0_cd:.0f} cd (Recommendation)",
        lambda value: value <= benchmark.rec_max_0_cd,
        False,
    )
    full_row(
        "360° maximum intensity @ -1°",
        max(c_im1) if c_im1 else None,
        f"≤ {benchmark.rec_max_minus1_cd:.0f} cd (Recommendation)",
        lambda value: value <= benchmark.rec_max_minus1_cd,
        False,
    )
    full_row(
        "360° maximum intensity @ -10°",
        max(c_im10) if c_im10 else None,
        f"≤ {benchmark.rec_max_minus10_cd:.0f} cd (Recommendation)",
        lambda value: value <= benchmark.rec_max_minus10_cd,
        False,
    )

    mandatory_local = [
        row for row in rows
        if row.mandatory and row.status.startswith("LOCAL")
    ]
    local_fail = any(row.status == "LOCAL FAIL" for row in mandatory_local)
    full_mandatory = [
        row for row in rows
        if row.mandatory and row.status in ("PASS", "FAIL")
    ]
    full_fail = any(row.status == "FAIL" for row in full_mandatory)

    if full_360:
        overall = "FAIL" if full_fail or local_fail else "PASS"
    elif local_fail:
        overall = "PARTIAL — LOCAL VERTICAL CHECK FAILED; 360° NOT EVALUATED"
    else:
        overall = "PARTIAL — LOCAL VERTICAL CHECK ONLY; 360° AZIMUTH NOT EVALUATED"

    return MiolComplianceResult(
        profile_type=profile_type,
        condition=condition,
        intensity_basis=basis,
        benchmark=benchmark,
        c_coverage_deg=coverage,
        full_360=full_360,
        rows=tuple(rows),
        overall=overall,
        selected_plane_c_deg=float(selected_c_deg),
        plane_i0_cd=plane_i0,
        plane_i_minus1_cd=plane_im1,
        plane_i_minus10_cd=plane_im10,
        plane_beam_spread_deg=plane_spread,
    )
