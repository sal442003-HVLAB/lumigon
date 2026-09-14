"""Load previously saved Lumigon measurement CSV files back into the run model.

This loader accepts both the original MeasurementRun CSV schema and the newer
P-9710 MIOL acquisition CSV written by ``p9710_miol_grid_runtime.py``.  Both are
normalized into MeasurementRun so the Results workspace can analyse them with
the same charts and summary tools.
"""

from __future__ import annotations

import csv
import re
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
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _looks_like_miol_csv(fieldnames) -> bool:
    names = set(fieldnames or [])
    required = {"point", "C_deg", "Gamma_deg", "E_lx", "I_cd", "distance_m"}
    return required.issubset(names)


def _sample_from_miol_filename(path: Path) -> str:
    """Best-effort sample id from MIOL_<type>_FULL_<sample>_<timestamp>.csv."""
    stem = path.stem
    match = re.match(
        r"^MIOL_[A-Za-z0-9]+_(?:FULL|C0)_?(.*?)_\d{8}_\d{6}$",
        stem,
        flags=re.IGNORECASE,
    )
    if match:
        text = match.group(1).strip("_ ")
        return text or "Unspecified"
    return stem


def _load_p9710_miol_csv(path: Path, rows: list[dict]) -> MeasurementRun:
    first = rows[0]
    points = []
    timestamps = []

    for row in rows:
        timestamp_text = str(row.get("timestamp", "")).strip()
        if timestamp_text:
            try:
                timestamps.append(_datetime(timestamp_text))
            except Exception:
                pass

        points.append(
            MeasurementPoint(
                point=_int(row.get("point")),
                c_deg=_float(row.get("C_deg")),
                gamma_deg=_float(row.get("Gamma_deg")),
                current_na=None,
                # For flashing MIOL A/B this is E-effective [lx].  Results keeps
                # it in the common lux field so all existing maps/planes work.
                lux=_float_or_none(row.get("E_lx")),
                candela_cd=_float_or_none(row.get("I_cd")),
                stdev_lux=None,
                distance_m=_float(row.get("distance_m")),
                samples=1,
                integration_ms=0,
                execution_mode="Step Scan",
                status="Measured",
            )
        )

    now = datetime.now().astimezone()
    started_at = min(timestamps) if timestamps else now
    completed_at = max(timestamps) if timestamps else started_at
    duration_s = max(0.0, (completed_at - started_at).total_seconds())

    c_values = {round(p.c_deg, 6) for p in points}
    gamma_values = {round(p.gamma_deg, 6) for p in points}
    if len(c_values) > 1 and len(gamma_values) > 1:
        scan_mode = "C × Gamma Grid (serpentine compatible)"
    elif len(c_values) == 1:
        scan_mode = "Gamma Sweep"
    elif len(gamma_values) == 1:
        scan_mode = "C Sweep"
    else:
        scan_mode = "Single Point"

    profile = str(first.get("profile", "P-9710 MIOL")).strip() or "P-9710 MIOL"
    basis = str(first.get("basis", "")).strip()
    if basis and basis.lower() not in profile.lower():
        profile = f"{profile} — {basis}"

    distance_m = _float(first.get("distance_m"))
    sample_id = _sample_from_miol_filename(path)

    return MeasurementRun(
        run_id=f"MIOL-{started_at.strftime('%Y%m%d-%H%M%S')}",
        started_at=started_at,
        completed_at=completed_at,
        duration_s=duration_s,
        application="Aviation",
        product="MIOL",
        profile=profile,
        standard="ICAO MIOL photometric acquisition",
        sample_id=sample_id,
        scan_mode=scan_mode,
        execution_mode="P-9710 Step Scan",
        distance_m=distance_m,
        settle_s=0.0,
        samples=1,
        integration_ms=0,
        home_status="Imported from P-9710 MIOL CSV",
        points=points,
        csv_path=path,
    )


def _load_standard_measurement_csv(path: Path, rows: list[dict]) -> MeasurementRun:
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

    return MeasurementRun(
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


def load_measurement_run_csv(path) -> MeasurementRun:
    """Load a supported Lumigon standard or P-9710 MIOL CSV into Results."""
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        raise ValueError("The selected CSV contains no measurement rows.")

    if _looks_like_miol_csv(fieldnames):
        return _load_p9710_miol_csv(path, rows)

    return _load_standard_measurement_csv(path, rows)
