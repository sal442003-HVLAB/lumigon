"""Load previously saved Lumigon measurement CSV files back into the run model."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from measurement_run import MeasurementPoint, MeasurementRun


def _float_or_none(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    return float(text)


def _float(value, default=0.0):
    parsed = _float_or_none(value)
    return float(default) if parsed is None else parsed


def _int(value, default=0):
    text = "" if value is None else str(value).strip()
    if not text:
        return int(default)
    return int(float(text))


def _datetime(value):
    text = "" if value is None else str(value).strip()
    if not text:
        return datetime.now().astimezone()
    return datetime.fromisoformat(text)


def load_measurement_run_csv(path) -> MeasurementRun:
    """Load one CSV created by :func:`save_measurement_run_csv`.

    The file stores run metadata on every row so it remains self-contained and
    human-readable in Excel.  The loader takes metadata from the first row and
    rebuilds all measured points from the complete file.
    """

    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    if not rows:
        raise ValueError("The selected CSV contains no measurement rows.")

    first = rows[0]
    required = {
        "run_id",
        "point",
        "c_deg",
        "gamma_deg",
        "current_nA",
        "lux",
        "candela_cd",
    }
    missing = sorted(required.difference(first.keys()))
    if missing:
        raise ValueError(
            "This is not a supported Lumigon measurement CSV. Missing column(s): "
            + ", ".join(missing)
        )

    points = []
    for row in rows:
        points.append(
            MeasurementPoint(
                point=_int(row.get("point")),
                c_deg=_float(row.get("c_deg")),
                gamma_deg=_float(row.get("gamma_deg")),
                current_na=_float_or_none(row.get("current_nA")),
                lux=_float_or_none(row.get("lux")),
                candela_cd=_float_or_none(row.get("candela_cd")),
                stdev_lux=_float_or_none(row.get("stdev_lux")),
                distance_m=_float(row.get("distance_m")),
                samples=_int(row.get("samples_per_point"), 1),
                integration_ms=_int(row.get("integration_ms")),
                execution_mode=str(row.get("execution_mode", "")),
                status=str(row.get("status", "Measured")),
            )
        )

    run = MeasurementRun(
        run_id=str(first.get("run_id", "IMPORTED")).strip() or "IMPORTED",
        started_at=_datetime(first.get("started_at")),
        completed_at=_datetime(first.get("completed_at")),
        duration_s=_float(first.get("duration_s")),
        application=str(first.get("application", "")),
        product=str(first.get("product", "")),
        profile=str(first.get("profile", "")),
        standard=str(first.get("standard", "")),
        sample_id=str(first.get("sample_id", "Unspecified")) or "Unspecified",
        scan_mode=str(first.get("scan_mode", "")),
        execution_mode=str(first.get("execution_mode", "")),
        distance_m=_float(first.get("distance_m")),
        settle_s=_float(first.get("settle_s")),
        samples=_int(first.get("samples_per_point"), 1),
        integration_ms=_int(first.get("integration_ms")),
        home_status=str(first.get("home_status", "Unknown")),
        points=points,
        csv_path=path,
    )
    return run
