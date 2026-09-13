"""Live visualization for the P-9710 MIOL grid pilot.

The acquisition worker already flushes each completed point to CSV. This module
intentionally reads that CSV instead of touching the instrument thread, so plot
refreshes can never interfere with P-9710 timing or goniometer motion.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


PLOT_REFRESH_MS = 750


def _load_rows(path: Path):
    rows = []
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                try:
                    c_deg = float(row["C_deg"])
                    gamma_deg = float(row["Gamma_deg"])
                    intensity_cd = float(row["I_cd"])
                    e_lx = float(row["E_lx"])
                except (KeyError, TypeError, ValueError):
                    continue
                if all(math.isfinite(v) for v in (c_deg, gamma_deg, intensity_cd, e_lx)):
                    rows.append((c_deg, gamma_deg, intensity_cd, e_lx))
    except (OSError, PermissionError):
        return []
    return rows


def _unique(values, tol=1e-6):
    out = []
    for value in sorted(float(v) for v in values):
        if not out or abs(value - out[-1]) > tol:
            out.append(value)
    return out


def attach_p9710_miol_live_plot(window):
    """Attach a live Heatmap / Gamma-profile viewer below the MIOL pilot box."""

    if getattr(window, "p9710_miol_live_plot", None) is not None:
        return window.p9710_miol_live_plot

    box = getattr(window, "p9710_miol_grid_box", None)
    if box is None or box.layout() is None:
        return None

    container = QWidget(box)
    root = QVBoxLayout(container)
    root.setContentsMargins(0, 8, 0, 0)
    root.setSpacing(6)

    top = QHBoxLayout()
    title = QLabel("Live photometric view")
    title.setStyleSheet("font-weight:700; color:#DCEAF3;")
    top.addWidget(title)
    top.addStretch(1)

    heatmap_button = QPushButton("Intensity Map")
    profile_button = QPushButton("Gamma Profile")
    heatmap_button.setCheckable(True)
    profile_button.setCheckable(True)
    heatmap_button.setChecked(True)
    top.addWidget(heatmap_button)
    top.addWidget(profile_button)

    top.addWidget(QLabel("C plane:"))
    c_plane_combo = QComboBox()
    c_plane_combo.setMinimumWidth(110)
    top.addWidget(c_plane_combo)
    root.addLayout(top)

    status = QLabel("Waiting for MIOL data…")
    status.setStyleSheet("color:#8AA8BC;")
    root.addWidget(status)

    stack = QStackedWidget()
    stack.setMinimumHeight(360)
    stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
    root.addWidget(stack, 1)

    heatmap_figure = Figure(figsize=(7.2, 4.0))
    heatmap_canvas = FigureCanvasQTAgg(heatmap_figure)
    heatmap_canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
    heatmap_canvas.setMinimumSize(0, 0)
    heatmap_page = QWidget()
    hp_layout = QVBoxLayout(heatmap_page)
    hp_layout.setContentsMargins(0, 0, 0, 0)
    hp_layout.addWidget(heatmap_canvas)

    profile_figure = Figure(figsize=(7.2, 4.0))
    profile_canvas = FigureCanvasQTAgg(profile_figure)
    profile_canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
    profile_canvas.setMinimumSize(0, 0)
    profile_page = QWidget()
    pp_layout = QVBoxLayout(profile_page)
    pp_layout.setContentsMargins(0, 0, 0, 0)
    pp_layout.addWidget(profile_canvas)

    stack.addWidget(heatmap_page)
    stack.addWidget(profile_page)

    state = {
        "path": None,
        "rows": [],
        "last_size": None,
        "c_values": [],
    }

    def style_axis(ax):
        ax.set_facecolor("#111B23")
        ax.tick_params(colors="#B9CAD6")
        for spine in ax.spines.values():
            spine.set_color("#40586A")
        ax.grid(True, alpha=0.18)

    def clear_figure(figure, canvas, text):
        figure.clear()
        figure.patch.set_facecolor("#101820")
        ax = figure.add_subplot(111)
        ax.set_facecolor("#111B23")
        ax.text(0.5, 0.5, text, ha="center", va="center", color="#8EA6B6", transform=ax.transAxes)
        ax.set_axis_off()
        figure.subplots_adjust(left=0.08, right=0.96, bottom=0.12, top=0.90)
        canvas.draw_idle()

    def rebuild_c_planes(c_values):
        previous = c_plane_combo.currentData()
        c_plane_combo.blockSignals(True)
        c_plane_combo.clear()
        for value in c_values:
            c_plane_combo.addItem(f"C {value:+.2f}°", float(value))
        if c_values:
            if previous is None:
                index = min(range(len(c_values)), key=lambda i: abs(c_values[i]))
            else:
                index = min(range(len(c_values)), key=lambda i: abs(c_values[i] - float(previous)))
            c_plane_combo.setCurrentIndex(index)
        c_plane_combo.blockSignals(False)

    def draw_heatmap():
        rows = state["rows"]
        if not rows:
            clear_figure(heatmap_figure, heatmap_canvas, "Waiting for measured grid points")
            return

        c_values = _unique(r[0] for r in rows)
        g_values = _unique(r[1] for r in rows)
        matrix = np.full((len(g_values), len(c_values)), np.nan, dtype=float)
        c_index = {round(v, 6): i for i, v in enumerate(c_values)}
        g_index = {round(v, 6): i for i, v in enumerate(g_values)}
        for c_deg, gamma_deg, i_cd, _e_lx in rows:
            matrix[g_index[round(gamma_deg, 6)], c_index[round(c_deg, 6)]] = i_cd

        heatmap_figure.clear()
        heatmap_figure.patch.set_facecolor("#101820")
        ax = heatmap_figure.add_subplot(111)
        style_axis(ax)

        if len(c_values) > 1:
            dc = min(abs(b - a) for a, b in zip(c_values, c_values[1:]))
        else:
            dc = 1.0
        if len(g_values) > 1:
            dg = min(abs(b - a) for a, b in zip(g_values, g_values[1:]))
        else:
            dg = 1.0
        extent = [c_values[0] - dc / 2, c_values[-1] + dc / 2, g_values[0] - dg / 2, g_values[-1] + dg / 2]
        image = ax.imshow(
            matrix,
            origin="lower",
            aspect="auto",
            extent=extent,
            interpolation="nearest",
        )
        cbar = heatmap_figure.colorbar(image, ax=ax, pad=0.02)
        cbar.set_label("Luminous intensity [cd]", color="#DCEAF3")
        cbar.ax.tick_params(colors="#B9CAD6")

        ax.set_xlabel("C angle [deg]", color="#DCEAF3")
        ax.set_ylabel("Gamma angle [deg]", color="#DCEAF3")
        ax.set_title("MIOL intensity map — measured I [cd]", color="#E8F2F7", fontweight="bold")

        finite = matrix[np.isfinite(matrix)]
        if finite.size:
            peak = float(np.max(finite))
            positions = np.argwhere(matrix == peak)
            if positions.size:
                gi, ci = positions[0]
                ax.plot(c_values[ci], g_values[gi], marker="x", markersize=9, markeredgewidth=2)
                ax.annotate(
                    f"Peak {peak:.1f} cd",
                    (c_values[ci], g_values[gi]),
                    xytext=(8, 8),
                    textcoords="offset points",
                    color="#EAF4FA",
                    fontsize=9,
                )

        heatmap_figure.subplots_adjust(left=0.10, right=0.90, bottom=0.14, top=0.88)
        heatmap_canvas.draw_idle()

    def draw_profile():
        rows = state["rows"]
        selected_c = c_plane_combo.currentData()
        if not rows or selected_c is None:
            clear_figure(profile_figure, profile_canvas, "No C plane available yet")
            return

        plane = sorted(
            ((g, i_cd) for c, g, i_cd, _e in rows if abs(c - float(selected_c)) <= 1e-4),
            key=lambda item: item[0],
        )
        if not plane:
            clear_figure(profile_figure, profile_canvas, "Selected C plane has no measured points")
            return

        gamma = [p[0] for p in plane]
        intensity = [p[1] for p in plane]

        profile_figure.clear()
        profile_figure.patch.set_facecolor("#101820")
        ax = profile_figure.add_subplot(111)
        style_axis(ax)
        ax.plot(gamma, intensity, marker="o", linewidth=2.0, markersize=4.0)
        ax.fill_between(gamma, intensity, alpha=0.08)
        ax.set_xlabel("Gamma angle [deg]", color="#DCEAF3")
        ax.set_ylabel("Luminous intensity [cd]", color="#DCEAF3")
        ax.set_title(f"Gamma profile at C = {float(selected_c):+.2f}°", color="#E8F2F7", fontweight="bold")

        peak_index = max(range(len(intensity)), key=intensity.__getitem__)
        ax.plot(gamma[peak_index], intensity[peak_index], marker="x", markersize=9, markeredgewidth=2)
        ax.annotate(
            f"{intensity[peak_index]:.1f} cd @ {gamma[peak_index]:+.2f}°",
            (gamma[peak_index], intensity[peak_index]),
            xytext=(8, 8),
            textcoords="offset points",
            color="#EAF4FA",
            fontsize=9,
        )
        profile_figure.subplots_adjust(left=0.10, right=0.97, bottom=0.14, top=0.88)
        profile_canvas.draw_idle()

    def redraw():
        draw_heatmap()
        draw_profile()

    def refresh_from_csv():
        path_text = getattr(window, "p9710_miol_last_csv", None)
        if not path_text:
            return
        path = Path(path_text)
        if not path.exists():
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if state["path"] == path and state["last_size"] == size:
            return

        rows = _load_rows(path)
        state["path"] = path
        state["last_size"] = size
        state["rows"] = rows
        c_values = _unique(r[0] for r in rows)
        if c_values != state["c_values"]:
            state["c_values"] = c_values
            rebuild_c_planes(c_values)

        if rows:
            latest = rows[-1]
            status.setText(
                f"Live • {len(rows)} measured points • latest C {latest[0]:+.2f}°, "
                f"Gamma {latest[1]:+.2f}° • {latest[2]:.1f} cd"
            )
        else:
            status.setText("CSV created — waiting for first completed point…")
        redraw()

    def select_heatmap():
        heatmap_button.setChecked(True)
        profile_button.setChecked(False)
        stack.setCurrentIndex(0)
        draw_heatmap()

    def select_profile():
        profile_button.setChecked(True)
        heatmap_button.setChecked(False)
        stack.setCurrentIndex(1)
        draw_profile()

    heatmap_button.clicked.connect(select_heatmap)
    profile_button.clicked.connect(select_profile)
    c_plane_combo.currentIndexChanged.connect(lambda *_: draw_profile())

    box.layout().addWidget(container)

    timer = QTimer(container)
    timer.setInterval(PLOT_REFRESH_MS)
    timer.timeout.connect(refresh_from_csv)
    timer.start()

    clear_figure(heatmap_figure, heatmap_canvas, "Waiting for MIOL measurement")
    clear_figure(profile_figure, profile_canvas, "Waiting for MIOL measurement")

    window.p9710_miol_live_plot = container
    window.p9710_miol_live_plot_timer = timer
    return container
