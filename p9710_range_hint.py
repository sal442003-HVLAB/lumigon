"""Approximate lux-capacity hint for the P-9710 range selector.

The P-9710 electrical ranges are defined by detector current.  For the
currently characterised lux detector (~0.376 nA/lx), this helper presents the
approximate illuminance corresponding to full-scale current for each range.
It is a convenience hint only; GP remains the authoritative live utilization
indicator.
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


def _format_lux(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f} Mlx"
    if value >= 1_000:
        return f"{value / 1_000:.2f} klx"
    if value >= 10:
        return f"{value:.1f} lx"
    return f"{value:.3f} lx"


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

    hint = QLabel()
    hint.setWordWrap(True)
    hint.setStyleSheet("color:#8FA9B9;")
    hint.setToolTip(
        "Approximate full-scale illuminance calculated from the characterised "
        "detector sensitivity (~0.376 nA/lx). Use GP for actual range utilization."
    )

    def update_hint(*_args):
        range_id = int(range_spin.value())
        current_na = RANGE_MAX_CURRENT_NA[range_id]
        max_lux = current_na / DETECTOR_SENSITIVITY_NA_PER_LX
        hint.setText(
            f"R{range_id} approx. full scale: {_format_lux(max_lux)} "
            f"(detector ~{DETECTOR_SENSITIVITY_NA_PER_LX:.3f} nA/lx)"
        )

    # Put the hint directly beside the Range selector row.
    box.layout().addWidget(hint, 3, 2, 1, 4)
    range_spin.valueChanged.connect(update_hint)
    update_hint()

    window.p9710_effective_range_spin = range_spin
    window.p9710_range_hint_label = hint
    return hint
