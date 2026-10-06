"""Empirical GP guard for this laboratory meter, not factory calibration."""

import math

# Operator observed GP stopping at 50 during known overload on R5 and R6.
# Keep raw GP in diagnostics/CSV. This reference is NOT an optical correction.
GP_SATURATION_REFERENCE = 50.0
GP_REFERENCE_BASIS = "Operator observed GP=50 ceiling on overloaded R5/R6"


def normalized_range_use(raw_gp, reference=GP_SATURATION_REFERENCE):
    raw_gp = abs(float(raw_gp))
    reference = float(reference)
    if not math.isfinite(raw_gp) or not math.isfinite(reference) or reference <= 0:
        raise ValueError("GP and its saturation reference must be finite; reference must be positive.")
    return 100.0 * raw_gp / reference
