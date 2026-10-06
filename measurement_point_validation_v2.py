"""Triplicate validation for one Version 2 photometric measurement point.

At every C/Gamma coordinate Lumigon will acquire three independent effective
measurements. The point is accepted only when all three values remain inside a
relative tolerance band around their median. The stored point value is then the
mean of the three accepted measurements.

The tolerance is an engineering default for commissioning and can be tuned
later without changing the measurement UI.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


DEFAULT_SAMPLE_COUNT = 3
DEFAULT_TOLERANCE_PCT = 5.0


@dataclass(frozen=True)
class TriplicateValidation:
    values: tuple[float, float, float]
    median: float
    mean: float
    max_deviation_pct: float
    tolerance_pct: float
    valid: bool


def validate_triplicate(
    values,
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> TriplicateValidation:
    samples = tuple(float(v) for v in values)

    if len(samples) != DEFAULT_SAMPLE_COUNT:
        raise ValueError(
            f"Exactly {DEFAULT_SAMPLE_COUNT} measurements are required per point."
        )

    if any(not math.isfinite(v) or v < 0.0 for v in samples):
        raise ValueError("Measurements must be finite, non-negative values.")

    tolerance_pct = float(tolerance_pct)
    if tolerance_pct <= 0.0:
        raise ValueError("Tolerance must be positive.")

    median = statistics.median(samples)
    mean = statistics.mean(samples)

    if median <= 0.0:
        max_deviation_pct = 0.0 if max(samples) == 0.0 else float("inf")
    else:
        max_deviation_pct = max(
            abs(value - median) / median * 100.0
            for value in samples
        )

    return TriplicateValidation(
        values=samples,
        median=median,
        mean=mean,
        max_deviation_pct=max_deviation_pct,
        tolerance_pct=tolerance_pct,
        valid=bool(
            math.isfinite(max_deviation_pct)
            and max_deviation_pct <= tolerance_pct
        ),
    )
