"""LDT-style folded polar presentation for dual standard EULUMDAT planes.

This refines only the visual presentation of the dedicated
`Dual standard planes (C0/C180 + C90/C270)` mode for imported EULUMDAT/LDT
photometry. It does not modify stored data or the native Lumigon limited-angle
measurement views.
"""

from __future__ import annotations

import numpy as np

from eulumdat_dual_plane_refinements import (
    C0_C180_COLOR,
    C90_C270_COLOR,
    DUAL_STANDARD_DATA,
)
from eulumdat_results_refinements import _is_eulumdat_run, _nearest_index
from native_polar_template_refinements import install_native_polar_template_refinements
from results_grid_charts import GridResultsCharts


def _pair_halves(widget, base_c: float):
    grid = getattr(widget, "grid_data", None)
    if grid is None:
        return None

    bi = _nearest_index(grid.c_values, float(base_c) % 360.0)
    oi = _nearest_index(grid.c_values, (float(base_c) + 180.0) % 360.0)

    gammas = np.asarray(grid.gamma_values, dtype=float)
    right_values = np.asarray(grid.values[bi, :], dtype=float)
    left_values = np.asarray(grid.values[oi, :], dtype=float)

    finite = np.isfinite(gammas) & ((np.isfinite(left_values)) | (np.isfinite(right_values)))
    if not np.any(finite):
        return None

    gammas = gammas[finite]
    left_values = left_values[finite]
    right_values = right_values[finite]

    # LDT-style folded polar compares the conventional lower hemisphere.
    # Full 0..180 gamma data remain available in Heatmap, 3D and other plane
    # views; this standard comparison intentionally displays gamma 0..90 only.
    folded = gammas <= 90.0 + 1e-9
    gammas = gammas[folded]
    left_values = left_values[folded]
    right_values = right_values[folded]
    if gammas.size == 0:
        return None

    return {
        "gammas": gammas,
        "left_values": left_values,
        "right_values": right_values,
        "actual_base": float(grid.c_values[bi]),
        "actual_opposite": float(grid.c_values[oi]),
        "quantity_label": grid.quantity_label,
        "unit": grid.unit,
    }


def install_eulumdat_folded_standard_plane_refinements():
    if getattr(GridResultsCharts, "_lumigon_eulumdat_folded_polar", False):
        return
    GridResultsCharts._lumigon_eulumdat_folded_polar = True

    original_draw_plane = GridResultsCharts._draw_plane

    def _plot_half(axis, gammas, values, *, side: str, color: str, label: str, marker: bool):
        valid = np.isfinite(values)
        if not np.any(valid):
            return
        signed = gammas[valid] if side == "left" else -gammas[valid]
        theta = np.radians(signed)
        radius = values[valid]
        axis.plot(theta, radius, linewidth=2.2, color=color, label=label)
        if marker:
            i = int(np.argmax(radius))
            axis.scatter([theta[i]], [radius[i]], marker="*", s=95, color=color, zorder=5)

    def patched_draw_plane(self):
        if not (
            _is_eulumdat_run(self)
            and self.plane_family_combo.currentData() == DUAL_STANDARD_DATA
            and self.plane_view_combo.currentText() == "Polar"
        ):
            return original_draw_plane(self)

        first = _pair_halves(self, 0.0)
        second = _pair_halves(self, 90.0)
        if first is None or second is None:
            return original_draw_plane(self)

        self.plane_figure.clear()
        self.plane_figure.patch.set_facecolor("#101820")
        axis = self.plane_figure.add_subplot(111, projection="polar")
        axis.set_facecolor("#111B23")
        axis.set_theta_zero_location("S")
        axis.set_theta_direction(-1)

        # Standard folded C-plane presentation:
        # C0 and C90 on the right, their opposite planes C180 and C270 on left.
        _plot_half(
            axis,
            first["gammas"],
            first["right_values"],
            side="right",
            color=C0_C180_COLOR,
            label="C0 / C180",
            marker=False,
        )
        _plot_half(
            axis,
            first["gammas"],
            first["left_values"],
            side="left",
            color=C0_C180_COLOR,
            label="_nolegend_",
            marker=True,
        )
        _plot_half(
            axis,
            second["gammas"],
            second["right_values"],
            side="right",
            color=C90_C270_COLOR,
            label="C90 / C270",
            marker=False,
        )
        _plot_half(
            axis,
            second["gammas"],
            second["left_values"],
            side="left",
            color=C90_C270_COLOR,
            label="_nolegend_",
            marker=True,
        )

        ticks = [-90, -75, -60, -45, -30, -15, 0, 15, 30, 45, 60, 75, 90]
        labels = [f"{abs(v):g}°" if v else "0°" for v in ticks]
        axis.set_thetagrids(ticks, labels=labels)
        axis.set_thetamin(-90.0)
        axis.set_thetamax(90.0)
        axis.set_rmin(0.0)

        all_values = []
        for payload in (first, second):
            for arr in (payload["left_values"], payload["right_values"]):
                arr = np.asarray(arr, dtype=float)
                arr = arr[np.isfinite(arr)]
                if arr.size:
                    all_values.extend(arr.tolist())
        vmax = max(all_values) if all_values else 0.0
        if vmax > 0.0:
            axis.set_rmax(105.0 if first["unit"] == "% of Imax" else vmax * 1.10)

        axis.grid(True, alpha=0.30)
        axis.tick_params(colors="#B9CAD6")
        axis.spines["polar"].set_color("#40586A")
        legend = axis.legend(
            loc="upper right",
            bbox_to_anchor=(1.18, 1.08),
            framealpha=0.18,
        )
        for text in legend.get_texts():
            text.set_color("#D9E5ED")
        axis.set_title(
            f"Standard photometric planes • {first['quantity_label']}",
            color="#E4EEF5",
            pad=14,
            fontweight="bold",
        )
        self.plane_figure.subplots_adjust(left=0.04, right=0.92, bottom=0.06, top=0.90)
        self.plane_canvas.draw()

    GridResultsCharts._draw_plane = patched_draw_plane

    # Install the common Lumigon template after the EULUMDAT wrappers. The
    # native patch explicitly delegates imported LDT/EULUMDAT runs back to this
    # EULUMDAT path, while all native Lumigon Polar views use the shared fixed
    # template.
    install_native_polar_template_refinements()
