"""Shared native Lumigon photometric polar-plot template.

The template is intentionally independent of scan range. A native Lumigon run
may contain only a few degrees around the optical axis, while the surrounding
photometric grid remains fixed so results are visually comparable from run to
run and can later be reused by report generation.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.ticker import MaxNLocator


BACKGROUND = "#101820"
AXIS_BACKGROUND = "#111B23"
GRID_COLOR = "#607482"
TICK_COLOR = "#C4D2DC"
SPINE_COLOR = "#4B6373"
TITLE_COLOR = "#E4EEF5"
UNIT_COLOR = "#CFDDE6"

# The visual reference uses 0° on the optical axis at the bottom, ±90° at the
# horizontal sides, with construction lines continuing into the >90° region.
# Matplotlib needs only one of ±180° because both refer to the same ray.
PHOTOMETRIC_THETA_TICKS = tuple(range(-165, 181, 15))


def _theta_label(angle: float) -> str:
    """Return report-style angle labels while retaining all construction rays."""

    value = int(round(float(angle)))
    magnitude = abs(value)
    if value == 0:
        return "0°"
    if magnitude <= 90:
        return f"{magnitude}°"
    # Keep the >90° rays visible without cluttering the upper hemisphere.
    return ""


def _finite_values(values):
    result = []
    for value in values or []:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return result


def configure_photometric_polar(axis, values=(), *, relative=False):
    """Apply Lumigon's standard photometric polar geometry and grid.

    Geometry is fixed for all native measurements:
      * Gamma/scan 0° points downward along the optical axis.
      * Positive native angles are shown on the right; negative on the left.
      * ±90° are the horizontal rays.
      * Construction rays continue above 90° through the upper hemisphere.

    Only the radial scale follows the active data.
    """

    axis.set_facecolor(AXIS_BACKGROUND)
    axis.set_theta_zero_location("S")
    axis.set_theta_direction(1)
    axis.set_thetamin(-180.0)
    axis.set_thetamax(180.0)
    axis.set_thetagrids(
        PHOTOMETRIC_THETA_TICKS,
        labels=[_theta_label(value) for value in PHOTOMETRIC_THETA_TICKS],
    )

    axis.set_rmin(0.0)
    finite = _finite_values(values)
    if relative:
        axis.set_rmax(105.0)
    elif finite:
        peak = max(finite)
        if peak > 0.0:
            axis.set_rmax(peak * 1.10)

    # A small, consistent set of radial rings gives the report-like appearance
    # of dedicated photometric software and stays readable across cd/lx ranges.
    axis.yaxis.set_major_locator(MaxNLocator(nbins=5, prune="lower"))
    axis.set_rlabel_position(0.0)

    axis.grid(True, color=GRID_COLOR, linewidth=0.75, alpha=0.52)
    axis.tick_params(colors=TICK_COLOR, labelsize=10)
    axis.spines["polar"].set_color(SPINE_COLOR)
    axis.spines["polar"].set_linewidth(1.0)
    return axis


def draw_photometric_curve(axis, angles, values, *, color=None, label=None, linewidth=2.1):
    """Draw one measured photometric curve without altering the fixed template."""

    angle_array = np.asarray(list(angles), dtype=float)
    value_array = np.asarray(list(values), dtype=float)
    valid = np.isfinite(angle_array) & np.isfinite(value_array)
    if not np.any(valid):
        return None

    theta = np.radians(angle_array[valid])
    radial = value_array[valid]
    kwargs = {
        "linewidth": linewidth,
        "solid_capstyle": "round",
        "solid_joinstyle": "round",
    }
    if color is not None:
        kwargs["color"] = color
    if label is not None:
        kwargs["label"] = label
    return axis.plot(theta, radial, **kwargs)[0]


def finish_photometric_figure(figure, *, unit="", title=""):
    """Finish the shared figure framing used by native Polar views."""

    figure.patch.set_facecolor(BACKGROUND)
    if title:
        figure.suptitle(title, color=TITLE_COLOR, fontweight="bold", fontsize=12, y=0.965)
    if unit:
        figure.text(
            0.055,
            0.055,
            unit,
            color=UNIT_COLOR,
            fontsize=10,
            ha="left",
            va="bottom",
        )
    figure.subplots_adjust(left=0.06, right=0.94, bottom=0.07, top=0.90)
