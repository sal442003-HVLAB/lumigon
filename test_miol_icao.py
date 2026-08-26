"""Regression tests for ICAO MIOL profile mathematics."""

from types import SimpleNamespace

from miol_icao import (
    analyse_miol_run,
    benchmark_for,
    blondel_rey_effective,
    icao_elevation_from_gamma,
)


def test_blondel_rey_square_pulse_200_ms():
    dt = 0.001
    times = [index * dt for index in range(1001)]
    values = [
        1000.0 if 0.300 <= t <= 0.500 else 0.0
        for t in times
    ]

    result = blondel_rey_effective(times, values)
    assert abs(result.effective_value - 500.0) < 3.0
    assert result.peak_value == 1000.0
    assert result.baseline_value == 0.0


def test_miol_benchmarks_and_gamma_sign():
    assert benchmark_for("A", "Day").nominal_cd == 20000.0
    assert benchmark_for("A", "Twilight").nominal_cd == 20000.0
    assert benchmark_for("A", "Night").nominal_cd == 2000.0
    assert benchmark_for("B", "Night").nominal_cd == 2000.0
    assert benchmark_for("C", "Night").nominal_cd == 2000.0
    assert icao_elevation_from_gamma(+10.0) == -10.0


def test_limited_c_data_never_claims_full_icao_pass():
    points = []
    for gamma, intensity in (
        (-2.0, 1800.0),
        (-1.0, 1700.0),
        (0.0, 2000.0),
        (+1.0, 1000.0),
        (+2.0, 800.0),
        (+3.0, 500.0),
        (+10.0, 50.0),
    ):
        points.append(
            SimpleNamespace(
                c_deg=0.0,
                gamma_deg=gamma,
                candela_cd=intensity,
            )
        )

    run = SimpleNamespace(
        profile="MIOL Type B — ICAO Annex 14",
        standard=(
            "ICAO Annex 14 | Condition: Night | "
            "Intensity: I-effective (Blondel-Rey)"
        ),
        points=points,
    )
    result = analyse_miol_run(run)

    assert result is not None
    assert result.full_360 is False
    assert result.overall.startswith("PARTIAL")
    assert result.plane_i0_cd == 2000.0
    assert result.plane_i_minus1_cd == 1000.0
    assert result.plane_i_minus10_cd == 50.0
