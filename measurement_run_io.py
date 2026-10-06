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


def _load_v2_measurement_csv(path: Path, rows: list[dict]) -> MeasurementRun:
    """Load the Version 2 Measurement CSV with strict integrity checks."""

    first = rows[0]
    required = {
        "lumigon_format", "schema_version", "sample_id", "run_started_at",
        "point", "c_deg", "gamma_deg", "mode", "distance_m",
    }
    missing = sorted(required.difference(first))
    if missing:
        raise ValueError("Missing V2 column(s): " + ", ".join(missing))

    def required_number(row, key, row_number, *, integer=False):
        value = _float_or_none(row.get(key))
        if value is None or not math.isfinite(value):
            raise ValueError(f"Row {row_number}: {key} must be finite and nonblank.")
        if integer and (value < 1 or not value.is_integer()):
            raise ValueError(f"Row {row_number}: {key} must be a positive integer.")
        return int(value) if integer else value
    format_name = str(first.get("lumigon_format", "")).strip()
    if format_name != "Lumigon Measurement V2":
        raise ValueError(
            "Unsupported Version 2 measurement identifier: "
            f"{format_name or '<blank>'}"
        )

    schema_version = str(first.get("schema_version", "")).strip()
    if schema_version not in {"2.0", "2.1", "2.2"}:
        raise ValueError(
            f"Unsupported Lumigon Measurement V2 schema: {schema_version or '<blank>'}"
        )
    if schema_version in {"2.1", "2.2"} and "sample_count" not in first:
        raise ValueError("Missing V2 column(s): sample_count")
    if schema_version == "2.2":
        range_columns = {
            "range_ids", "range_peak_utilization_pct", "range_precheck_peak_pct",
            "range_acquisition_peak_pct", "range_check_status", "range_check_method",
            "range_check_count", "range_selection_attempts",
        }
        missing = sorted(range_columns.difference(first))
        if missing:
            raise ValueError("Missing V2 range-check column(s): " + ", ".join(missing))

    mode = str(first.get("mode", "")).strip()
    if mode not in {"i_effective", "cw_maximum"}:
        raise ValueError(f"Unsupported V2 measurement mode: {mode or '<blank>'}")

    distance_m = _float(first.get("distance_m"))
    if not math.isfinite(distance_m) or distance_m <= 0.0:
        raise ValueError("Measurement distance must be greater than zero.")

    sample_id = str(first.get("sample_id", "Unspecified")).strip() or "Unspecified"
    # Schema 2.0 predates sample_count; retain its actual sample columns.
    sample_count = (
        required_number(first, "sample_count", 2, integer=True)
        if "sample_count" in first
        else sum(bool(str(first.get(f"sample_{i}", "")).strip()) for i in (1, 2, 3)) or 1
    )
    if not str(first.get("run_started_at", "")).strip():
        raise ValueError("Row 2: run_started_at must be nonblank.")
    started_at = _datetime(first["run_started_at"])
    coordinates = set()
    point_ids = set()
    points = []

    for row_number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"Row {row_number}: CSV row length differs from the header.")
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
        if (not str(row.get("run_started_at", "")).strip()
                or _datetime(row["run_started_at"]) != started_at):
            raise ValueError(f"Row {row_number}: mixed or missing run_started_at values.")
        if "sample_count" in row:
            if required_number(row, "sample_count", row_number, integer=True) != sample_count:
                raise ValueError(f"Row {row_number}: mixed sample_count values.")
        if not math.isfinite(row_distance):
            raise ValueError(
                f"Row {row_number}: measurement distance must be finite."
            )
        if abs(row_distance - distance_m) > max(1e-9, abs(distance_m) * 1e-9):
            raise ValueError(
                f"Row {row_number}: measurement distance differs from the run distance."
            )

        c_deg = required_number(row, "c_deg", row_number)
        gamma_deg = required_number(row, "gamma_deg", row_number)
        if not math.isfinite(c_deg) or not math.isfinite(gamma_deg):
            raise ValueError(
                f"Row {row_number}: C/Gamma coordinates must be finite numbers."
            )
        point_id = required_number(row, "point", row_number, integer=True)
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
            if not math.isfinite(expected_i):
                raise ValueError(f"Row {row_number}: E-effective × distance² overflowed.")
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

        range_pct = None
        range_status = "unverified"
        if schema_version == "2.2":
            range_pct = required_number(row, "range_peak_utilization_pct", row_number)
            precheck_pct = required_number(row, "range_precheck_peak_pct", row_number)
            capture_pct = required_number(row, "range_acquisition_peak_pct", row_number)
            if not (0 < range_pct <= 90 and 0 <= precheck_pct <= 90 and 0 < capture_pct <= 90):
                raise ValueError(f"Row {row_number}: range utilization must be verified and at most 90%.")
            if not math.isclose(range_pct, max(precheck_pct, capture_pct), rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError(f"Row {row_number}: inconsistent range utilization peaks.")
            range_status = str(row["range_check_status"]).strip()
            expected_status = "within_target" if range_pct >= 10 else "low_utilization"
            if range_status != expected_status:
                raise ValueError(f"Row {row_number}: inconsistent range_check_status.")
            if row["range_check_method"] != "GP precheck + acquisition extrema":
                raise ValueError(f"Row {row_number}: unsupported range_check_method.")
            range_id = required_number(row, "range_ids", row_number)
            if not range_id.is_integer() or not 0 <= range_id <= 7:
                raise ValueError(f"Row {row_number}: range_ids must be one integer from 0 to 7.")
            if required_number(row, "range_check_count", row_number, integer=True) < 2:
                raise ValueError(f"Row {row_number}: both precheck and acquisition GP checks are required.")
            required_number(row, "range_selection_attempts", row_number, integer=True)

        points.append(
            MeasurementPoint(
                point=point_id,
                c_deg=c_deg,
                gamma_deg=gamma_deg,
                current_na=None,
                lux=lux_value,
                candela_cd=candela_value,
                stdev_lux=None,
                distance_m=distance_m,
                samples=sample_count,
                integration_ms=0,
                execution_mode="V2 Step Scan",
                status="Measured",
                range_utilization_pct=range_pct,
                range_check_status=range_status,
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
        if len(fieldnames) != len(set(fieldnames)):
            raise ValueError("Duplicate CSV column names are not allowed.")
        rows = list(reader)

    if not rows:
        raise ValueError("The selected CSV contains no measurement rows.")

    if _looks_like_v2_measurement_csv(fieldnames):
        return _load_v2_measurement_csv(path, rows)

    if _looks_like_miol_csv(fieldnames):
        return _load_p9710_miol_csv(path, rows)

    return _load_standard_measurement_csv(path, rows)
