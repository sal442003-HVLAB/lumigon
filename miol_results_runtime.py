"""ICAO Annex 14 MIOL compliance presentation in Lumigon Results."""

from __future__ import annotations

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHeaderView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from miol_icao import (
    ICAO_REFERENCE,
    analyse_miol_run,
    icao_elevation_from_gamma,
    profile_type_from_text,
)


class MiolComplianceWidget(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("ICAO Annex 14 — MIOL Compliance", parent)
        self.run = None
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 9, 10, 10)
        root.setSpacing(7)

        header = QGridLayout()
        header.setHorizontalSpacing(12)
        header.setVerticalSpacing(4)
        self.reference_label = QLabel(ICAO_REFERENCE)
        self.reference_label.setWordWrap(True)
        self.profile_label = QLabel("—")
        self.basis_label = QLabel("—")
        self.coverage_label = QLabel("—")
        self.overall_label = QLabel("—")
        self.overall_label.setWordWrap(True)

        header.addWidget(QLabel("Reference:"), 0, 0)
        header.addWidget(self.reference_label, 0, 1, 1, 3)
        header.addWidget(QLabel("Profile:"), 1, 0)
        header.addWidget(self.profile_label, 1, 1)
        header.addWidget(QLabel("Intensity basis:"), 1, 2)
        header.addWidget(self.basis_label, 1, 3)
        header.addWidget(QLabel("C coverage:"), 2, 0)
        header.addWidget(self.coverage_label, 2, 1)
        header.addWidget(QLabel("Overall:"), 2, 2)
        header.addWidget(self.overall_label, 2, 3)
        header.setColumnStretch(1, 2)
        header.setColumnStretch(3, 3)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Displayed C plane:"))
        self.c_plane_combo = QComboBox()
        self.c_plane_combo.currentIndexChanged.connect(self.refresh)
        controls.addWidget(self.c_plane_combo)
        self.plane_summary = QLabel("—")
        self.plane_summary.setMinimumWidth(0)
        self.plane_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        controls.addWidget(self.plane_summary, 1)
        root.addLayout(controls)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            "ICAO Table 6-3 item",
            "Measured",
            "Requirement",
            "Status",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setMinimumHeight(330)
        self.table.setMinimumWidth(0)
        self.table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeToContents,
        )
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(
            3,
            QHeaderView.ResizeToContents,
        )
        body.addWidget(self.table, 3)

        self.figure = Figure(figsize=(6.0, 4.0))
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumSize(0, 330)
        self.canvas.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        body.addWidget(self.canvas, 2)
        root.addLayout(body)

        note = QLabel(
            "Annex 14 Table 6-3 requires 360° horizontal coverage. With "
            "Lumigon's current limited C envelope, the selected vertical plane "
            "can be checked locally, but overall 360° compliance remains Not Evaluated."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #8AA8BC;")
        root.addWidget(note)

        self.setStyleSheet(
            """
            QGroupBox { border: 1px solid #34495E; margin-top: 8px; }
            QGroupBox::title { color: #DDEAF3; subcontrol-origin: margin; left: 10px; }
            QTableWidget { background-color: #111B23; alternate-background-color: #14212B; }
            """
        )

    def set_run(self, run):
        self.run = run
        self.c_plane_combo.blockSignals(True)
        self.c_plane_combo.clear()
        if run is not None:
            c_values = sorted({
                float(point.c_deg)
                for point in run.points
                if getattr(point, "candela_cd", None) is not None
            })
            for value in c_values:
                self.c_plane_combo.addItem(f"C {value:+.3f}°", value)
            if c_values:
                zero_index = min(
                    range(len(c_values)),
                    key=lambda i: abs(c_values[i]),
                )
                self.c_plane_combo.setCurrentIndex(zero_index)
        self.c_plane_combo.blockSignals(False)
        self.refresh()

    def _selected_c(self):
        data = self.c_plane_combo.currentData()
        return None if data is None else float(data)

    def _plane_series(self, c_target):
        if self.run is None or c_target is None:
            return [], []
        usable = [
            p for p in self.run.points
            if getattr(p, "candela_cd", None) is not None
        ]
        if not usable:
            return [], []
        c_nearest = min(
            {float(p.c_deg) for p in usable},
            key=lambda value: abs(value - c_target),
        )
        pairs = sorted(
            (
                icao_elevation_from_gamma(p.gamma_deg),
                float(p.candela_cd),
            )
            for p in usable
            if abs(float(p.c_deg) - c_nearest) <= 1e-4
        )
        return [p[0] for p in pairs], [p[1] for p in pairs]

    @staticmethod
    def _item(text):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def refresh(self, *_args):
        if self.run is None:
            return
        result = analyse_miol_run(
            self.run,
            selected_c_deg=self._selected_c(),
        )
        if result is None:
            self.hide()
            return

        self.show()
        self.profile_label.setText(
            f"MIOL Type {result.profile_type} • {result.condition} • "
            f"{result.benchmark.nominal_cd:,.0f} cd benchmark"
        )
        self.basis_label.setText(result.intensity_basis)
        self.coverage_label.setText(
            f"{result.c_coverage_deg:.1f}° / 360°"
            + (" • FULL" if result.full_360 else " • PARTIAL")
        )
        self.overall_label.setText(result.overall)

        plane_bits = []
        if result.plane_i0_cd is not None:
            plane_bits.append(f"I(0°) {result.plane_i0_cd:.1f} cd")
        if result.plane_i_minus1_cd is not None:
            plane_bits.append(f"I(-1°) {result.plane_i_minus1_cd:.1f} cd")
        if result.plane_beam_spread_deg is not None:
            plane_bits.append(f"beam {result.plane_beam_spread_deg:.2f}°")
        self.plane_summary.setText(
            " • ".join(plane_bits) if plane_bits else "—"
        )

        self.table.setRowCount(len(result.rows))
        for row_index, row in enumerate(result.rows):
            self.table.setItem(row_index, 0, self._item(row.item))
            self.table.setItem(row_index, 1, self._item(row.measured))
            self.table.setItem(row_index, 2, self._item(row.requirement))
            status_item = self._item(row.status)
            if "FAIL" in row.status:
                status_item.setForeground(QColor("#FF6B6B"))
            elif "PASS" in row.status:
                status_item.setForeground(QColor("#64D98B"))
            self.table.setItem(row_index, 3, status_item)

        self._draw_chart(result)

    def _draw_chart(self, result):
        elevations, values = self._plane_series(result.selected_plane_c_deg)
        self.figure.clear()
        self.figure.patch.set_facecolor("#101820")
        axis = self.figure.add_subplot(111)
        axis.set_facecolor("#111B23")
        axis.tick_params(colors="#B9CAD6")
        for spine in axis.spines.values():
            spine.set_color("#40586A")
        axis.grid(True, alpha=0.25)

        if elevations and values:
            axis.plot(
                elevations,
                values,
                linewidth=2.0,
                marker="o",
                markersize=3.5,
                label="Measured",
            )

        b = result.benchmark
        axis.axhline(
            b.beam_threshold_cd,
            linestyle="--",
            linewidth=1.0,
            alpha=0.7,
            label=f"Beam threshold {b.beam_threshold_cd:.0f} cd",
        )
        axis.scatter(
            [0.0],
            [b.min_0_cd],
            marker="^",
            s=55,
            label=f"0° min {b.min_0_cd:.0f}",
        )
        axis.scatter(
            [-1.0],
            [b.min_minus1_cd],
            marker="^",
            s=55,
            label=f"-1° min {b.min_minus1_cd:.0f}",
        )
        axis.scatter(
            [-10.0],
            [b.rec_max_minus10_cd],
            marker="v",
            s=55,
            label=f"-10° rec max {b.rec_max_minus10_cd:.0f}",
        )
        for x in (0.0, -1.0, -10.0):
            axis.axvline(x, linewidth=0.75, alpha=0.25)

        axis.set_xlabel("ICAO vertical elevation (°)", color="#CFDDE6")
        axis.set_ylabel(
            "Effective intensity (cd)"
            if "effective" in result.intensity_basis.lower()
            else "Luminous intensity (cd)",
            color="#CFDDE6",
        )
        axis.set_title(
            (
                f"ICAO Table 6-3 • C {result.selected_plane_c_deg:+.3f}°"
                if result.selected_plane_c_deg is not None
                else "ICAO Table 6-3"
            ),
            color="#E4EEF5",
            fontweight="bold",
        )
        axis.legend(fontsize=8, framealpha=0.20)
        self.figure.subplots_adjust(
            left=0.12,
            right=0.97,
            bottom=0.16,
            top=0.86,
        )
        self.canvas.draw()


def attach_miol_results_runtime(window):
    workspace = getattr(window, "results_workspace_controller", None)
    if workspace is None:
        raise RuntimeError(
            "Results workspace is not available for MIOL results integration."
        )
    if getattr(workspace, "miol_compliance_widget", None) is not None:
        return workspace.miol_compliance_widget

    widget = MiolComplianceWidget(workspace)
    widget.hide()
    layout = workspace.layout()
    chart = getattr(workspace, "charts", None)
    index = layout.indexOf(chart) if chart is not None else layout.count()
    layout.insertWidget(max(0, index), widget)
    workspace.miol_compliance_widget = widget

    original_set_run = workspace.set_run

    def set_run_with_miol(run):
        original_set_run(run)
        if profile_type_from_text(getattr(run, "profile", "")) is None:
            widget.hide()
            return
        widget.set_run(run)

    workspace.set_run = set_run_with_miol
    return widget
