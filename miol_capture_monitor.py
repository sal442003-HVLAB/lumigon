"""Live diagnostics and labels for ICAO MIOL temporal acquisition."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QTableWidgetItem

from measurement_profile_catalog import attach_measurement_profile_catalog
from miol_icao import MIOL_PROFILES, profile_type_from_text


def attach_miol_capture_monitor(window):
    box = getattr(window, "measurement_miol_profile_box", None)
    if box is None or box.layout() is None:
        raise RuntimeError("MIOL profile UI is not ready for capture diagnostics.")
    if getattr(window, "measurement_miol_capture_status_label", None) is not None:
        return window.measurement_miol_capture_status_label

    # Finalize the Test Definition catalog after the MIOL runtime has created
    # its A/B/C profiles and operating-condition selector. This keeps Product,
    # Profile and Standard scoped to the selected Measurement application.
    attach_measurement_profile_catalog(window)

    label = QLabel("—")
    label.setWordWrap(True)
    label.setStyleSheet("color: #8AA8BC;")
    label.setToolTip(
        "Diagnostic values from the most recent temporal flash capture. "
        "Median Δt is the actual serial sampling interval and should be checked "
        "during commissioning before relying on formal I-effective results."
    )
    box.layout().addRow("Last I-effective capture:", label)

    def sync_table_labels(*_args):
        profile_combo = getattr(window, "measurement_profile_combo", None)
        table = getattr(window, "measurement_plan_table", None)
        if profile_combo is None or table is None:
            return
        code = profile_type_from_text(profile_combo.currentText())
        flashing = bool(code and MIOL_PROFILES[code].flashing)
        # Change only the two photometric result columns so the plan clearly
        # states the ICAO quantity being stored.
        if flashing:
            table.setHorizontalHeaderItem(5, QTableWidgetItem("E-effective (lx)"))
            table.setHorizontalHeaderItem(6, QTableWidgetItem("I-effective (cd)"))
        else:
            table.setHorizontalHeaderItem(5, QTableWidgetItem("Lux"))
            table.setHorizontalHeaderItem(6, QTableWidgetItem("Candela"))

    profile_combo = getattr(window, "measurement_profile_combo", None)
    if profile_combo is not None:
        profile_combo.currentIndexChanged.connect(sync_table_labels)
    sync_table_labels()

    timer = QTimer(window)
    timer.setInterval(400)

    def refresh():
        meter = getattr(window, "luxmeter", None)
        data = (
            getattr(meter, "last_miol_capture", None)
            if meter is not None
            else None
        )
        if not data:
            label.setText("—")
            return

        interval_ms = 1000.0 * float(data.get("effective_interval_s", 0.0))
        median_ms = data.get("median_sample_interval_ms")
        median_text = (
            "—"
            if median_ms is None
            else f"{float(median_ms):.1f} ms"
        )
        label.setText(
            f"Ie {float(data.get('effective_lux', 0.0)):.3f} lx  •  "
            f"peak {float(data.get('peak_lux_net', 0.0)):.3f} lx  •  "
            f"baseline {float(data.get('baseline_lux', 0.0)):.3f} lx  •  "
            f"Te {interval_ms:.1f} ms  •  "
            f"N {int(data.get('samples', 0))}  •  median Δt {median_text}"
        )

    timer.timeout.connect(refresh)
    timer.start()

    window.measurement_miol_capture_status_label = label
    window.measurement_miol_capture_monitor_timer = timer
    return label
