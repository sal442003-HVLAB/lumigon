"""Live Cartesian C-plane graph for Lumigon Version 2 Measurement."""

from __future__ import annotations

from collections import defaultdict

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget


MODE_I_EFFECTIVE = "i_effective"
MODE_CW_MAXIMUM = "cw_maximum"


class CPlaneGraphV2(QWidget):
    """Fixed-frame live graph showing the latest measured C plane."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = MODE_I_EFFECTIVE
        self._distance_m = 5.0
        self._gamma_min = -5.0
        self._gamma_max = 5.0
        self._planes = defaultdict(list)
        self._active_c = None

        # Keep the graph frame stable while values/labels change.
        self.setFixedSize(680, 500)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.figure = Figure(figsize=(6.8, 5.0))
        self.figure.patch.set_facecolor("#101820")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.canvas)

        self._draw_empty()

    def reset(self, *, mode: str, distance_m: float, gamma_min: float, gamma_max: float):
        self._mode = str(mode)
        self._distance_m = float(distance_m)
        self._gamma_min = min(float(gamma_min), float(gamma_max))
        self._gamma_max = max(float(gamma_min), float(gamma_max))
        self._planes.clear()
        self._active_c = None
        self._draw_empty("Waiting for first measured point")

    def add_point(self, result: dict):
        c_deg = float(result.get("c_deg", 0.0))
        gamma_deg = float(result.get("gamma_deg", 0.0))

        if self._mode == MODE_CW_MAXIMUM:
            value = result.get("accepted_cw_maximum_lx")
        else:
            value = result.get("accepted_i_effective_cd")

        if value is None:
            return

        value = float(value)
        points = self._planes[c_deg]

        # Replace a repeated Gamma point instead of duplicating it.
        replaced = False
        for index, (old_gamma, _old_value) in enumerate(points):
            if abs(old_gamma - gamma_deg) <= 1e-9:
                points[index] = (gamma_deg, value)
                replaced = True
                break
        if not replaced:
            points.append((gamma_deg, value))

        self._active_c = c_deg
        self._draw_plane(c_deg)

    def _styled_axis(self):
        self.figure.clear()
        self.figure.patch.set_facecolor("#101820")
        axis = self.figure.add_subplot(111)
        axis.set_facecolor("#111B23")
        axis.tick_params(colors="#B9CAD6")
        axis.grid(True, alpha=0.30)
        for spine in axis.spines.values():
            spine.set_color("#40586A")
        return axis

    def _draw_empty(self, text="No measurement data"):
        axis = self._styled_axis()
        axis.text(
            0.5,
            0.5,
            text,
            ha="center",
            va="center",
            color="#8EA6B6",
            transform=axis.transAxes,
        )
        axis.set_axis_off()
        self.figure.subplots_adjust(left=0.11, right=0.97, bottom=0.13, top=0.90)
        self.canvas.draw_idle()

    def _draw_plane(self, c_deg: float):
        points = sorted(self._planes.get(c_deg, []), key=lambda item: item[0])
        if not points:
            self._draw_empty()
            return

        gamma = [item[0] for item in points]
        values = [item[1] for item in points]

        axis = self._styled_axis()
        axis.plot(gamma, values, marker="o", linewidth=2.0, markersize=5.0)

        # X geometry is locked to the requested Gamma range for the full run.
        pad = max(0.5, 0.04 * max(1.0, self._gamma_max - self._gamma_min))
        axis.set_xlim(self._gamma_min - pad, self._gamma_max + pad)
        axis.axvline(0.0, linewidth=0.8, alpha=0.35)

        if self._mode == MODE_CW_MAXIMUM:
            quantity = "CW maximum"
            unit = "lx"
        else:
            quantity = "I-effective"
            unit = "cd"

        axis.set_xlabel("Gamma angle (°)", color="#CFDDE6")
        axis.set_ylabel(f"{quantity} ({unit})", color="#CFDDE6")
        axis.set_title(
            f"C-plane {c_deg:+.1f}°  •  {quantity}",
            color="#E4EEF5",
            fontweight="bold",
        )

        self.figure.subplots_adjust(left=0.13, right=0.97, bottom=0.14, top=0.89)
        self.canvas.draw_idle()
