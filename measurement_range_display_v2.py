"""Compact P-9710 range-use indicator shared by Measurement and progress."""

import math

from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget


class MeasurementRangeDisplayV2(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.setToolTip(
            "Peak GP range utilization, not an uncertainty percentage. "
            "Target 10–90%; 90% is a software ceiling. Below 10%, the safer "
            "range is retained if the next gain would exceed 90%. "
            "GP alone has not been validated against the manufacturer's overload "
            "indication on this meter. Brief unsampled transients remain unverified."
        )
        self.reset()

    def reset(self):
        self.update_range({"state": "unverified", "phase": "Waiting for GP"})

    def update_range(self, payload):
        pct = payload.get("peak_pct")
        known = pct is not None and math.isfinite(float(pct))
        state = payload.get("state", "checking")
        phase = payload.get("phase", "")
        range_id = payload.get("range_id")
        prefix = f"R{range_id} • " if range_id is not None else ""
        number = f"{float(pct):.1f}% peak" if known else "—"
        captions = {
            "within_target": "GP within target • overload unverified",
            "low_utilization": "Low use • safer range retained",
            "over_limit": "Above 90% • acquisition rejected",
            "overload": "Overload • acquisition rejected",
            "unverified": "Unverified",
            "checking": phase or "Checking",
        }
        color = (
            "#EF6C6C" if state in {"overload", "over_limit"}
            else "#F2BE64" if state == "low_utilization"
            else "#9DD5F3"
        )
        self.label.setText(f"{prefix}{number} • {captions.get(state, phase)}")
        self.label.setStyleSheet(f"color:{color}; font-weight:600;")
        self.bar.setValue(min(1000, max(0, round(float(pct) * 10))) if known else 0)
        self.bar.setStyleSheet(
            "QProgressBar {background:#14212B; border:1px solid #34495E; border-radius:3px;}"
            f"QProgressBar::chunk {{background:{color}; border-radius:2px;}}"
        )
