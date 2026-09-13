"""Approximate lux-capacity helpers for the P-9710 range selector.

The P-9710 electrical ranges are defined by detector current. For the
currently characterised lux detector (~0.376 nA/lx), this module converts the
nominal electrical full-scale values to approximate illuminance ranges.

These lux values are convenience hints only. GP remains the authoritative live
utilization indicator.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QSpinBox


DETECTOR_SENSITIVITY_NA_PER_LX = 0.376

# P-9710 full-scale detector current, expressed in nA.
RANGE_MAX_CURRENT_NA = {
    0: 2_000_000.0,   # 2 mA
    1: 200_000.0,     # 200 uA
    2: 20_000.0,      # 20 uA
    3: 2_000.0,       # 2 uA
    4: 200.0,         # 200 nA
    5: 20.0,          # 20 nA
    6: 2.0,           # 2 nA
    7: 0.2,           # 200 pA
}


def format_lux(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mlx"
    if value >= 1_000:
        return f"{value / 1_000:.2f} klx"
    if value >= 10:
        return f"{value:.1f} lx"
    return f"{value:.3f} lx"


def range_full_scale_lux(range_id: int) -> float:
    return RANGE_MAX_CURRENT_NA[int(range_id)] / DETECTOR_SENSITIVITY_NA_PER_LX


def range_nominal_span_lux(range_id: int) -> tuple[float, float]:
    """Return an approximate nominal lux span for a manual range.

    The lower bound is taken as the full-scale value of the next more-sensitive
    range, giving the operator a practical decade-to-decade span. R7 has no
    more-sensitive hardware range, so its lower bound is shown as zero.
    """
    range_id = int(range_id)
    upper = range_full_scale_lux(range_id)
    lower = 0.0 if range_id >= 7 else range_full_scale_lux(range_id + 1)
    return lower, upper


def range_span_text(range_id: int) -> str:
    lower, upper = range_nominal_span_lux(range_id)
    return f"{format_lux(lower)} – {format_lux(upper)}"


def attach_p9710_range_hint(window):
    box = getattr(window, "p9710_effective_box", None)
    if box is None or box.layout() is None:
        return None

    # Identify the dedicated Range spin box by its unique 0..7 limits.
    range_spin = None
    for spin in box.findChildren(QSpinBox):
        if spin.minimum() == 0 and spin.maximum() == 7:
            range_spin = spin
            break

    if range_spin is None:
        return None

    selected_label = None
    for label in box.findChildren(QLabel):
        if label.text().startswith("Selected range:"):
            selected_label = label
            break

    if selected_label is None:
        return None

    selected_label.setToolTip(
        "Approximate illuminance span inferred from the characterised detector "
        "sensitivity (~0.376 nA/lx). Use GP for actual range utilization."
    )

    def update_hint(*_args):
        range_id = int(range_spin.value())
        selected_label.setText(
            f"Selected range: R{range_id}  •  approx. {range_span_text(range_id)}"
        )

    range_spin.valueChanged.connect(update_hint)
    update_hint()

    window.p9710_effective_range_spin = range_spin
    window.p9710_range_hint_label = selected_label
    return selected_label
