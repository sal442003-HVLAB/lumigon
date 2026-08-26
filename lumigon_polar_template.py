"""Shared native Lumigon photometric polar-plot template.

This renderer intentionally does not use Matplotlib's polar projection. Dedicated
photometric software uses a report-style Cartesian viewport around a polar
construction: 0° is the optical axis at the bottom, ±90° are the horizontal
rays, construction lines continue beyond 90°, and the radial circles are clipped
by a rectangular frame. Keeping that geometry independent of the measured scan
range makes native Lumigon results directly comparable from run to run.
"""

from __future__ import annotations

import math

import numpy as np
from matplotlib.patches import Circle


BACKGROUND = "#101820"
AXIS_BACKGROUND = "#111B23"
GRID_COLOR = "#607482"
TICK_COLOR = "#C4D2DC"
SPINE_COLOR = "#4B6373"
TITLE_COLOR = "#E4EEF5"
UNIT_COLOR = "#CFDDE6"
CURVE_COLOR = "#2C91D1"

# Geometry chosen to reproduce the useful proportions of a conventional
# photometric polar report: the optical origin sits high in the viewport, the
# lower hemisphere gets most of the space, and >90° construction rays remain
# visible above the horizontal 90° line.
X_EXTENT_FRACTION = 0.82
UPPER_EXTENT_FRACTION = 0.18
CONSTRUCTION_ANGLES = tuple(range(-165, 166, 15))
LABEL_ANGLES = (0, 15, 30, 45, 60, 75, 90)


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


def _nice_radial_scale(values, *, relative=False):
    """Return a stable report-style radial maximum and ring values."""

    if relative:
        return 100.0, [20.0, 40.0, 60.0, 80.0, 100.0]

    finite = [value for value in _finite_values(values) if value >= 0.0]
    peak = max(finite, default=0.0)
    if peak <= 0.0:
        return 1.0, [0.2, 0.4, 0.6, 0.8, 1.0]

    # Aim for roughly 4–5 radial intervals. Choosing the next standard step
    # above the raw interval avoids crowded rings and gives useful numbers such
    # as 1000, 2000, 3000... for common candela ranges.
    raw_step = peak / 4.5
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    standard = (1.0, 2.0, 2.5, 5.0, 10.0)
    factor = next((candidate for candidate in standard if candidate >= normalized), 10.0)
    step = factor * magnitude

    radial_max = math.ceil((peak * 1.08) / step) * step
    radial_max = max(radial_max, step)
    count = max(1, int(round(radial_max / step)))
    rings = [step * index for index in range(1, count + 1)]
    return radial_max, rings


def _photometric_xy(angles, radii):
    """Convert native signed angles to the Lumigon photometric viewport."""

    angle_array = np.asarray(list(angles), dtype=float)
    radius_array = np.asarray(list(radii), dtype=float)
    radians = np.radians(angle_array)
    x = radius_array * np.sin(radians)
    y = -radius_array * np.cos(radians)
    return x, y


def _ray_frame_intersection(angle_deg: float, radial_max: float):
    """Find the visible lower-hemisphere frame point for an angle label."""

    theta = math.radians(float(angle_deg))
    dx = math.sin(theta)
    dy = -math.cos(theta)
    x_limit = X_EXTENT_FRACTION * radial_max

    candidates = []
    if abs(dx) > 1e-12:
        candidates.append(x_limit / abs(dx))
    if dy < -1e-12:
        candidates.append((-radial_max) / dy)

    distance = min(value for value in candidates if value > 0.0)
    # Keep labels just inside the rectangular report frame.
    distance *= 0.965
    return distance * dx, distance * dy


def configure_photometric_polar(axis, values=(), *, relative=False):
    """Draw Lumigon's fixed report-style photometric polar construction.

    The supplied ``axis`` must be a normal Cartesian Matplotlib axis. Only the
    radial scale follows the active data; the angular geometry is fixed.
    """

    radial_max, rings = _nice_radial_scale(values, relative=relative)
    x_extent = X_EXTENT_FRACTION * radial_max
    upper_extent = UPPER_EXTENT_FRACTION * radial_max

    axis.set_facecolor(AXIS_BACKGROUND)
    axis.set_xlim(-x_extent, x_extent)
    axis.set_ylim(-radial_max, upper_extent)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xticks([])
    axis.set_yticks([])
    axis.tick_params(length=0)

    for spine in axis.spines.values():
        spine.set_visible(True)
        spine.set_color(SPINE_COLOR)
        spine.set_linewidth(1.0)

    # Radial circles are deliberately full circles; the rectangular axes clip
    # them naturally, which creates the familiar upper >90° construction arcs.
    for radius in rings:
        axis.add_patch(
            Circle(
                (0.0, 0.0),
                radius,
                fill=False,
                edgecolor=GRID_COLOR,
                linewidth=0.75,
                alpha=0.58,
                zorder=1,
            )
        )

    # Construction rays every 15° extend through both the measured lower region
    # and the unmeasured >90° region above the horizontal axis.
    ray_length = radial_max * 2.2
    for angle in CONSTRUCTION_ANGLES:
        theta = math.radians(angle)
        x = ray_length * math.sin(theta)
        y = -ray_length * math.cos(theta)
        axis.plot(
            [0.0, x],
            [0.0, y],
            color=GRID_COLOR,
            linewidth=0.72,
            alpha=0.58,
            zorder=1,
        )

    # Angle labels follow the report convention: no +/- signs, duplicated left
    # and right, with the 90° labels sitting on the horizontal optical-origin
    # line. Upper >90° construction rays intentionally remain unlabeled.
    for magnitude in LABEL_ANGLES:
        if magnitude == 0:
            x, y = _ray_frame_intersection(0.0, radial_max)
            axis.text(
                x,
                y,
                "0°",
                color=TICK_COLOR,
                fontsize=10,
                ha="center",
                va="bottom",
                zorder=4,
            )
            continue

        for sign in (-1, 1):
            signed_angle = sign * magnitude
            x, y = _ray_frame_intersection(signed_angle, radial_max)
            if magnitude >= 45:
                ha = "right" if sign < 0 else "left"
                va = "center"
            else:
                ha = "center"
                va = "bottom"
            axis.text(
                x,
                y,
                f"{magnitude}°",
                color=TICK_COLOR,
                fontsize=10,
                ha=ha,
                va=va,
                zorder=4,
            )

    # Radial values are placed on the optical axis with a background patch so
    # they remain readable and do not collide with construction lines. The
    # smallest and outermost rings are omitted when possible, matching common
    # photometric-report practice and avoiding the clutter seen in raw polar axes.
    label_rings = rings[1:-1] if len(rings) >= 4 else rings[:-1]
    for radius in label_rings:
        axis.text(
            0.0,
            -radius,
            f"{radius:g}",
            color=TICK_COLOR,
            fontsize=10,
            ha="center",
            va="center",
            bbox={
                "boxstyle": "square,pad=0.10",
                "facecolor": AXIS_BACKGROUND,
                "edgecolor": "none",
                "alpha": 0.96,
            },
            zorder=4,
        )

    axis._lumigon_radial_max = radial_max
    axis._lumigon_radial_rings = tuple(rings)
    return axis


def draw_photometric_curve(
    axis,
    angles,
    values,
    *,
    color=None,
    label=None,
    linewidth=2.1,
):
    """Draw one measured photometric curve on the fixed Cartesian template."""

    angle_array = np.asarray(list(angles), dtype=float)
    value_array = np.asarray(list(values), dtype=float)
    valid = np.isfinite(angle_array) & np.isfinite(value_array)
    if not np.any(valid):
        return None

    x, y = _photometric_xy(angle_array[valid], value_array[valid])
    kwargs = {
        "linewidth": linewidth,
        "solid_capstyle": "round",
        "solid_joinstyle": "round",
        "zorder": 5,
    }
    kwargs["color"] = color or CURVE_COLOR
    if label is not None:
        kwargs["label"] = label
    return axis.plot(x, y, **kwargs)[0]


def finish_photometric_figure(figure, *, unit="", title=""):
    """Finish the shared figure framing used by native Polar views."""

    figure.patch.set_facecolor(BACKGROUND)
    if title:
        figure.suptitle(
            title,
            color=TITLE_COLOR,
            fontweight="bold",
            fontsize=12,
            y=0.965,
        )
    if unit:
        figure.text(
            0.058,
            0.072,
            unit,
            color=UNIT_COLOR,
            fontsize=10,
            ha="left",
            va="bottom",
            bbox={
                "boxstyle": "square,pad=0.18",
                "facecolor": AXIS_BACKGROUND,
                "edgecolor": SPINE_COLOR,
                "linewidth": 0.8,
            },
        )
    # Wide report framing gives the custom polar construction enough horizontal
    # space without allowing the canvas to dictate the HMI window geometry.
    figure.subplots_adjust(left=0.055, right=0.965, bottom=0.105, top=0.90)
