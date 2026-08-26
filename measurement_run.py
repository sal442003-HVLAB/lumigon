"""Persistent measurement-run model and CSV export for Lumigon.

The measurement engines remain responsible only for acquisition.  This module
turns their result dictionaries into a stable run record that Results, plotting,
reports and future standards/profile analysis can all reuse.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4


@dataclass
class MeasurementPoint:
    point: int
    c_deg: float
    gamma_deg: float
    current_na: Optional[float]
    lux: Optional[float]
    candela_cd: Optional[float]
    stdev_lux: Optional[float]
    distance_m: float
    samples: int
    integration_ms: int
    execution_mode: str
    status: str = "Measured"

    @classmethod
    def from_result(cls, result: dict) -> "MeasurementPoint":
        return cls(
            point=int(result.get("point", 0)),
            c_deg=float(result.get("c_deg", 0.0)),
            gamma_deg=float(result.get("gamma_deg", 0.0)),
            current_na=_optional_float(result.get("mean_current_na")),
            lux=_optional_float(result.get("lux")),
            candela_cd=_optional_float(result.get("candela")),
            stdev_lux=_optional_float(result.get("stdev_lux")),
            distance_m=float(result.get("distance_m", 0.0)),
            samples=int(result.get("samples", 1)),
            integration_ms=int(result.get("integration_ms", 0)),
            execution_mode=str(result.get("execution_mode", "step")),
            status=str(result.get("status", "Measured")),
        )


@dataclass
class MeasurementRun:
    run_id: str
    started_at: datetime
    completed_at: datetime
    duration_s: float
    application: str
    product: str
    profile: str
    standard: str
    sample_id: str
    scan_mode: str
    execution_mode: str
    distance_m: float
    settle_s: float
    samples: int
    integration_ms: int
    home_status: str
    points: list[MeasurementPoint] = field(default_factory=list)
    csv_path: Optional[Path] = None
    save_error: Optional[str] = None

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def max_lux(self) -> Optional[float]:
        values = [p.lux for p in self.points if p.lux is not None]
        return max(values) if values else None

    @property
    def max_candela(self) -> Optional[float]:
        values = [p.candela_cd for p in self.points if p.candela_cd is not None]
        return max(values) if values else None

    @property
    def max_current_na(self) -> Optional[float]:
        values = [p.current_na for p in self.points if p.current_na is not None]
        return max(values) if values else None

    @property
    def peak_candela_point(self) -> Optional[MeasurementPoint]:
        candidates = [p for p in self.points if p.candela_cd is not None]
        return max(candidates, key=lambda p: p.candela_cd) if candidates else None


def _optional_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _combo_text(window, name: str, fallback: str = "") -> str:
    widget = getattr(window, name, None)
    if widget is None:
        return fallback
    try:
        return widget.currentText().strip()
    except Exception:
        return fallback


def _line_text(window, name: str, fallback: str = "") -> str:
    widget = getattr(window, name, None)
    if widget is None:
        return fallback
    try:
        return widget.text().strip()
    except Exception:
        return fallback


def build_measurement_run(
    window,
    raw_results: list[dict],
    *,
    started_at: datetime,
    duration_s: float,
    execution_mode: str,
    home_status: str,
) -> MeasurementRun:
    completed_at = datetime.now().astimezone()
    points = [MeasurementPoint.from_result(item) for item in raw_results]

    scan_widget = getattr(window, "measurement_scan_mode_combo", None)
    scan_mode = scan_widget.currentText().strip() if scan_widget is not None else ""

    distance_widget = getattr(window, "measurement_distance_spin", None)
    settle_widget = getattr(window, "measurement_settle_spin", None)
    samples_widget = getattr(window, "measurement_samples_spin", None)
    integration_widget = getattr(window, "measurement_integration_spin", None)

    return MeasurementRun(
        run_id=uuid4().hex[:12].upper(),
        started_at=started_at,
        completed_at=completed_at,
        duration_s=max(0.0, float(duration_s)),
        application=_combo_text(window, "measurement_application_combo"),
        product=_combo_text(window, "measurement_product_combo"),
        profile=_combo_text(window, "measurement_profile_combo"),
        standard=_line_text(window, "measurement_standard_edit"),
        sample_id=_line_text(window, "measurement_sample_id_edit") or "Unspecified",
        scan_mode=scan_mode,
        execution_mode=str(execution_mode),
        distance_m=float(distance_widget.value()) if distance_widget is not None else 0.0,
        settle_s=float(settle_widget.value()) if settle_widget is not None else 0.0,
        samples=int(samples_widget.value()) if samples_widget is not None else 1,
        integration_ms=int(integration_widget.value()) if integration_widget is not None else 0,
        home_status=home_status,
        points=points,
    )


def measurement_data_directory() -> Path:
    home = Path.home()
    documents = home / "Documents"
    base = documents if documents.exists() else home
    return base / "Lumigon" / "Measurements"


def _safe_filename(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    return text.strip("._-") or "sample"


def save_measurement_run_csv(run: MeasurementRun) -> Path:
    directory = measurement_data_directory()
    directory.mkdir(parents=True, exist_ok=True)

    timestamp = run.completed_at.strftime("%Y%m%d_%H%M%S")
    filename = (
        f"{timestamp}_{_safe_filename(run.sample_id)}_{run.run_id}.csv"
    )
    path = directory / filename

    columns = [
        "run_id",
        "started_at",
        "completed_at",
        "duration_s",
        "application",
        "product",
        "profile",
        "standard",
        "sample_id",
        "scan_mode",
        "execution_mode",
        "distance_m",
        "settle_s",
        "samples_per_point",
        "integration_ms",
        "home_status",
        "point",
        "c_deg",
        "gamma_deg",
        "current_nA",
        "lux",
        "candela_cd",
        "stdev_lux",
        "status",
    ]

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for point in run.points:
            writer.writerow(
                {
                    "run_id": run.run_id,
                    "started_at": run.started_at.isoformat(timespec="seconds"),
                    "completed_at": run.completed_at.isoformat(timespec="seconds"),
                    "duration_s": f"{run.duration_s:.3f}",
                    "application": run.application,
                    "product": run.product,
                    "profile": run.profile,
                    "standard": run.standard,
                    "sample_id": run.sample_id,
                    "scan_mode": run.scan_mode,
                    "execution_mode": run.execution_mode,
                    "distance_m": f"{run.distance_m:.6g}",
                    "settle_s": f"{run.settle_s:.6g}",
                    "samples_per_point": run.samples,
                    "integration_ms": run.integration_ms,
                    "home_status": run.home_status,
                    "point": point.point,
                    "c_deg": f"{point.c_deg:.6f}",
                    "gamma_deg": f"{point.gamma_deg:.6f}",
                    "current_nA": "" if point.current_na is None else f"{point.current_na:.9g}",
                    "lux": "" if point.lux is None else f"{point.lux:.9g}",
                    "candela_cd": "" if point.candela_cd is None else f"{point.candela_cd:.9g}",
                    "stdev_lux": "" if point.stdev_lux is None else f"{point.stdev_lux:.9g}",
                    "status": point.status,
                }
            )

    run.csv_path = path
    return path
