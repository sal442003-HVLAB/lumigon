import csv

import pytest

from measurement_run_io import load_measurement_run_csv


FIELDS = [
    "lumigon_format",
    "schema_version",
    "sample_id",
    "sample_count",
    "run_started_at",
    "point",
    "c_deg",
    "gamma_deg",
    "mode",
    "distance_m",
    "sample_1",
    "sample_2",
    "sample_3",
    "accepted_e_effective_lx",
    "accepted_i_effective_cd",
    "accepted_cw_maximum_lx",
    "max_deviation_pct",
    "tolerance_pct",
    "range_ids",
    "mean_baseline_lx",
    "mean_net_peak_lx",
    "mean_pulse_duration_ms",
    "mean_sample_interval_ms",
    "integral_lx_s",
    "acquisition_attempt",
    "validation_attempt",
]


def _row(point, c_deg, gamma_deg, e_lx):
    distance_m = 5.0
    return {
        "lumigon_format": "Lumigon Measurement V2",
        "schema_version": "2.1",
        "sample_id": "TEST",
        "sample_count": "1",
        "run_started_at": "2026-10-06T10:00:00+03:30",
        "point": str(point),
        "c_deg": str(c_deg),
        "gamma_deg": str(gamma_deg),
        "mode": "i_effective",
        "distance_m": str(distance_m),
        "sample_1": str(e_lx),
        "sample_2": "",
        "sample_3": "",
        "accepted_e_effective_lx": str(e_lx),
        "accepted_i_effective_cd": str(e_lx * distance_m * distance_m),
        "accepted_cw_maximum_lx": "",
        "max_deviation_pct": "",
        "tolerance_pct": "",
        "range_ids": "5",
        "mean_baseline_lx": "0.1",
        "mean_net_peak_lx": "30.0",
        "mean_pulse_duration_ms": "500.0",
        "mean_sample_interval_ms": "28.0",
        "integral_lx_s": "14.0",
        "acquisition_attempt": "1",
        "validation_attempt": "1",
    }


def _write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_v2_loader_accepts_consistent_effective_grid(tmp_path):
    path = tmp_path / "measurement.csv"
    _write(
        path,
        [
            _row(1, -10, -1, 20.0),
            _row(2, -10, 0, 21.0),
            _row(3, 0, -1, 22.0),
            _row(4, 0, 0, 23.0),
        ],
    )

    run = load_measurement_run_csv(path)

    assert run.sample_id == "TEST"
    assert run.distance_m == pytest.approx(5.0)
    assert run.point_count == 4
    assert run.scan_mode == "C × Gamma Grid"
    assert run.points[0].lux == pytest.approx(20.0)
    assert run.points[0].candela_cd == pytest.approx(500.0)
    assert "validated Lumigon V2 CSV" in run.home_status


def test_v2_loader_rejects_inconsistent_i_effective(tmp_path):
    path = tmp_path / "bad_relation.csv"
    row = _row(1, 0, 0, 20.0)
    row["accepted_i_effective_cd"] = "600.0"
    _write(path, [row])

    with pytest.raises(ValueError, match="I-effective is inconsistent"):
        load_measurement_run_csv(path)


def test_v2_loader_rejects_duplicate_coordinates(tmp_path):
    path = tmp_path / "duplicate.csv"
    _write(
        path,
        [
            _row(1, 0, 0, 20.0),
            _row(2, 0, 0, 20.0),
        ],
    )

    with pytest.raises(ValueError, match="duplicate C/Gamma coordinate"):
        load_measurement_run_csv(path)


def test_v2_loader_rejects_non_finite_coordinates(tmp_path):
    path = tmp_path / "nonfinite.csv"
    _write(path, [_row(1, "nan", 0, 20.0)])

    with pytest.raises(ValueError, match="must be finite"):
        load_measurement_run_csv(path)
