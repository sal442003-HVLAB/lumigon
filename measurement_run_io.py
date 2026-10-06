"""Load previously saved Lumigon measurement CSV files back into the run model.

This loader accepts the original MeasurementRun CSV schema, P-9710 MIOL CSV,
and the Version 2 Measurement CSV. All are normalized into MeasurementRun so
analysis/visualization code can use one stable data model. Version 2 files are
checked strictly for schema consistency, duplicate coordinates, and the
I-effective = E-effective × distance² relationship before they are accepted.
"""

from __future__ import annotations

import csv
import math
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


def _looks_like_v2_measurement_csv(fieldnames) -> bool:
    names = set(fieldnames or [])
    required = {
        "lumigon_format",
        "schema_version",
        "point",
        "c_deg",
        "gamma_deg",
        "mode",
        "distance_m",
    }
    return required.issubset(names)


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
                point=point_id,
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


def _load_v2_measurement_csv(path: Path, rows: list[dict]) -> MeasurementRun:
    """Load the Version 2 Measurement CSV with strict integrity checks."""

    first = rows[0]
    format_name = str(first.get("lumigon_format", "")).strip()
    if format_name != "Lumigon Measurement V2":
        raise ValueError(
            "Unsupported Version 2 measurement identifier: "
            f"{format_name or '<blank>'}"
        )

    schema_version = str(first.get("schema_version", "")).strip()
    if schema_version not in {"2.0", "2.1"}:
        raise ValueError(
            f"Unsupported Lumigon Measurement V2 schema: {schema_version or '<blank>'}"
        )

    mode = str(first.get("mode", "")).strip()
    if mode not in {"i_effective", "cw_maximum"}:
        raise ValueError(f"Unsupported V2 measurement mode: {mode or '<blank>'}")

    distance_m = _float(first.get("distance_m"))
    if not math.isfinite(distance_m) or distance_m <= 0.0:
        raise ValueError("Measurement distance must be greater than zero.")

    sample_id = str(first.get("sample_id", "Unspecified")).strip() or "Unspecified"
    sample_count = _int(first.get("sample_count"), 1)
    started_at = _datetime(first.get("run_started_at"))
    coordinates = set()
    point_ids = set()
    points = []

    for row_number, row in enumerate(rows, start=2):
        row_format = str(row.get("lumigon_format", "")).strip()
        row_schema = str(row.get("schema_version", "")).strip()
        row_mode = str(row.get("mode", "")).strip()
        row_distance = _float(row.get("distance_m"))
        row_sample_id = str(row.get("sample_id", sample_id)).strip() or "Unspecified"

        if row_format != format_name or row_schema != schema_version:
            raise ValueError(
                f"Row {row_number}: mixed Lumigon V2 format/schema values are not allowed."
            )
        if row_mode != mode:
            raise ValueError(
                f"Row {row_number}: mixed measurement modes are not allowed."
            )
        if row_sample_id != sample_id:
            raise ValueError(
                f"Row {row_number}: mixed sample IDs are not allowed."
            )
        if not math.isfinite(row_distance):
            raise ValueError(
                f"Row {row_number}: measurement distance must be finite."
            )
        if abs(row_distance - distance_m) > max(1e-9, abs(distance_m) * 1e-9):
            raise ValueError(
                f"Row {row_number}: measurement distance differs from the run distance."
            )

        c_deg = _float(row.get("c_deg"))
        gamma_deg = _float(row.get("gamma_deg"))
        if not math.isfinite(c_deg) or not math.isfinite(gamma_deg):
            raise ValueError(
                f"Row {row_number}: C/Gamma coordinates must be finite numbers."
            )
        point_id = _int(row.get("point"))
        if point_id in point_ids:
            raise ValueError(
                f"Row {row_number}: duplicate point number {point_id}."
            )
        point_ids.add(point_id)

        coordinate = (round(c_deg, 9), round(gamma_deg, 9))
        if coordinate in coordinates:
            raise ValueError(
                f"Row {row_number}: duplicate C/Gamma coordinate "
                f"({c_deg:g}°, {gamma_deg:g}°)."
            )
        coordinates.add(coordinate)

        if mode == "i_effective":
            e_lx = _float_or_none(row.get("accepted_e_effective_lx"))
            i_cd = _float_or_none(row.get("accepted_i_effective_cd"))
            if (
                e_lx is None
                or i_cd is None
                or not math.isfinite(e_lx)
                or not math.isfinite(i_cd)
            ):
                raise ValueError(
                    f"Row {row_number}: E-effective and I-effective are both required."
                )

            expected_i = e_lx * distance_m * distance_m
            tolerance = max(1e-6, abs(expected_i) * 1e-6)
            if abs(i_cd - expected_i) > tolerance:
                raise ValueError(
                    f"Row {row_number}: I-effective is inconsistent with "
                    "E-effective × distance²."
                )
            lux_value = e_lx
            candela_value = i_cd
        else:
            cw_lx = _float_or_none(row.get("accepted_cw_maximum_lx"))
            if cw_lx is None or not math.isfinite(cw_lx):
                raise ValueError(
                    f"Row {row_number}: accepted CW maximum is missing."
                )
            lux_value = cw_lx
            candela_value = None

        points.append(
            MeasurementPoint(
                point=_int(row.get("point")),
                c_deg=c_deg,
                gamma_deg=gamma_deg,
                current_na=None,
                lux=lux_value,
                candela_cd=candela_value,
                stdev_lux=None,
                distance_m=distance_m,
                samples=_int(row.get("sample_count"), sample_count),
                integration_ms=0,
                execution_mode="V2 Step Scan",
                status="Measured",
            )
        )

    c_values = {round(point.c_deg, 6) for point in points}
    gamma_values = {round(point.gamma_deg, 6) for point in points}
    if len(c_values) > 1 and len(gamma_values) > 1:
        scan_mode = "C × Gamma Grid"
    elif len(c_values) == 1 and len(gamma_values) > 1:
        scan_mode = "Gamma Sweep"
    elif len(gamma_values) == 1 and len(c_values) > 1:
        scan_mode = "C Sweep"
    else:
        scan_mode = "Single Point"

    try:
        completed_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except Exception:
        completed_at = started_at
    duration_s = max(0.0, (completed_at - started_at).total_seconds())

    return MeasurementRun(
        run_id=f"V2-{started_at.strftime('%Y%m%d-%H%M%S')}",
        started_at=started_at,
        completed_at=completed_at,
        duration_s=duration_s,
        application="Goniophotometry",
        product="Lumigon V2",
        profile=(
            "E-effective → I-effective"
            if mode == "i_effective"
            else "CW maximum"
        ),
        standard="Not evaluated",
        sample_id=sample_id,
        scan_mode=scan_mode,
        execution_mode="V2 Step Scan",
        distance_m=distance_m,
        settle_s=0.0,
        samples=sample_count,
        integration_ms=0,
        home_status="Imported from validated Lumigon V2 CSV",
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
    """Load a supported Lumigon CSV into the common MeasurementRun model."""
    path = Path(path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not rows:
        raise ValueError("The selected CSV contains no measurement rows.")

    if _looks_like_v2_measurement_csv(fieldnames):
        return _load_v2_measurement_csv(path, rows)

    if _looks_like_miol_csv(fieldnames):
        return _load_p9710_miol_csv(path, rows)

    return _load_standard_measurement_csv(path, rows)
