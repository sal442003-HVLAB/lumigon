import csv
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

import measurement_runtime_v2 as runtime
from measurement_range_display_v2 import MeasurementRangeDisplayV2
from measurement_run_io import load_measurement_run_csv
from p9710 import P9710Error


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class Clock:
    value = 0.0

    def now(self):
        return self.value


class FakeMeter:
    """Numeric MV can clip silently; GP still reports current range use."""
    def __init__(self, clock, peak=40.0, *, drift=None, bad_gp=None):
        self.clock = clock
        self.peak = peak
        self.drift = drift
        self.bad_gp = bad_gp
        self.configurations = []
        self.transactions = []
        self.last_value = None

    def configure_cw(self, *, range_id, **kwargs):
        self.range_id = range_id
        self.configurations.append(range_id)
        self.capture_start = self.clock.value

    def read_mv(self, **kwargs):
        t1 = self.clock.value
        phase = (t1 - self.capture_start) % 0.4
        peak = self.drift if self.drift is not None and len(self.configurations) >= 2 else self.peak
        value = peak if 0.1 <= phase <= 0.25 else 0.0
        capacity = 100.0 * 10.0 ** (5 - self.range_id)
        self.last_value = min(value, capacity)  # no error code on overload
        self.clock.value += 0.02
        self.transactions.append(("MV", self.last_value, t1))
        return self.last_value, str(self.last_value), t1, self.clock.value

    def read_range_utilization(self):
        assert self.transactions[-1][0] == "MV", "GP must follow its own MV"
        self.clock.value += 0.01
        capacity = 100.0 * 10.0 ** (5 - self.range_id)
        value = 100.0 * self.last_value / capacity
        self.transactions.append(("GP", value, self.clock.value))
        if isinstance(self.bad_gp, Exception):
            raise self.bad_gp
        return value if self.bad_gp is None else self.bad_gp

    @staticmethod
    def _status_code(exc):
        if "?16" in str(exc):
            return "overload"
        return "underload" if "?32" in str(exc) else ""


@pytest.fixture
def make_worker(monkeypatch, tmp_path, app):
    clock = Clock()
    monkeypatch.setattr(runtime.time, "perf_counter", clock.now)
    monkeypatch.setattr(runtime, "FLASH_CAPTURE_S", 1.4)
    monkeypatch.setattr(runtime.MeasurementV2Worker, "msleep", staticmethod(lambda ms: None))

    def make(peak=40.0, *, range_id=5, **kwargs):
        meter = FakeMeter(clock, peak, **kwargs)
        motion = SimpleNamespace(get_current_angle=lambda axis: 0.0, move_absolute=lambda axis, value: None)
        worker = runtime.MeasurementV2Worker(
            motion=motion, meter=meter, points=[(0, 0)],
            mode=runtime.MODE_I_EFFECTIVE, distance_m=5,
            sample_id="RANGE-TEST", output_path=tmp_path / "measured.csv",
        )
        worker.current_range_id = range_id
        worker._wait_interruptible = lambda seconds: None
        return worker, meter
    return make


def test_numeric_clipping_without_error_selects_less_sensitive_range(make_worker):
    worker, meter = make_worker(180)
    flash = worker._capture_one_flash()
    assert meter.configurations == [5, 4, 4]
    assert flash.range_id == 4
    assert flash.cw_max_lx == 180  # clipped 100 lx was completely discarded
    assert flash.range_peak_utilization_pct == 18
    assert flash.range_check_status == "within_target"
    assert flash.range_selection_attempts == 2


@pytest.mark.parametrize("pct, expected", [(9.0, [4, 5, 5]), (9.5, [4, 4]), (10.0, [4, 4]), (90.0, [4, 4]), (90.01, [4, 3, 3])])
def test_decade_boundaries_and_no_range_oscillation(make_worker, pct, expected):
    worker, meter = make_worker(pct * 10, range_id=4)
    flash = worker._capture_one_flash()
    assert meter.configurations == expected
    assert flash.range_peak_utilization_pct <= 90
    if pct == 9.5:
        assert flash.range_check_status == "low_utilization"


def test_dark_phase_does_not_increase_gain(make_worker):
    worker, meter = make_worker(40)
    flash = worker._capture_one_flash()
    assert meter.configurations == [5, 5]
    assert any(kind == "GP" and value == 0 for kind, value, _ in meter.transactions)
    assert flash.range_peak_utilization_pct == 40


def test_explicit_gp_underload_during_dark_phase_is_not_a_missing_reply(make_worker):
    worker, meter = make_worker(40)
    original = meter.read_range_utilization
    def gp():
        if meter.last_value == 0:
            meter.clock.value += 0.01
            meter.transactions.append(("GP", 0, meter.clock.value))
            raise P9710Error("P-9710 status ?32")
        return original()
    meter.read_range_utilization = gp
    flash = worker._capture_one_flash()
    assert flash.range_peak_utilization_pct == 40
    assert meter.configurations == [5, 5]


def test_new_gain_is_checked_not_assumed_and_falls_back_without_oscillation(make_worker):
    worker, meter = make_worker(85, range_id=4, drift=95)
    flash = worker._capture_one_flash()
    assert meter.configurations == [4, 5, 4, 4]
    assert flash.range_id == 4 and flash.range_peak_utilization_pct == 9.5
    assert flash.range_check_status == "low_utilization"


def test_brighter_acquisition_than_precheck_rejects_whole_capture(make_worker):
    worker, meter = make_worker(40, drift=180)
    flash = worker._capture_one_flash()
    assert meter.configurations == [5, 5, 4, 4]
    assert flash.range_id == 4 and flash.cw_max_lx == 180


def test_overload_at_least_sensitive_range_rejects_point(make_worker):
    worker, meter = make_worker(2e7, range_id=0)
    with pytest.raises(RuntimeError, match="90%"):
        worker._capture_one_flash()
    assert meter.configurations == [0]


@pytest.mark.parametrize("bad_gp", [float("nan"), float("inf"), P9710Error("No response to GP"), "not numeric", None])
def test_invalid_or_zero_gp_never_accepts_point(make_worker, bad_gp):
    # None selects the ordinary device behavior, with zero GP and no flash.
    worker, meter = make_worker(0 if bad_gp is None else 40, bad_gp=bad_gp)
    with pytest.raises(RuntimeError):
        worker._capture_one_flash()
    assert meter.configurations == [5]  # no blind sensitivity increase


def test_gp_failure_during_acquisition_rejects_point(make_worker):
    worker, meter = make_worker()
    original = meter.read_range_utilization
    def fail_in_main():
        if len(meter.configurations) == 2:
            raise P9710Error("No response to GP")
        return original()
    meter.read_range_utilization = fail_in_main
    with pytest.raises(runtime._RangeCheckFailed):
        worker._capture_one_flash()
    assert meter.configurations == [5, 5]


def test_peak_gp_is_paired_before_next_mv_and_preserves_mv_timestamp(make_worker):
    worker, meter = make_worker()
    capture = worker._capture_waveform(5)
    mv = [(value, t) for kind, value, t in meter.transactions if kind == "MV"]
    assert [t for t, _ in capture.samples] == pytest.approx([t + 0.01 for _, t in mv])
    assert capture.peak_utilization_pct == 40
    assert capture.gp_checks == 2  # dark initial maximum and first bright peak
    assert capture.gp_checks < len(capture.samples)


def test_offset_corrected_negative_mv_still_checks_new_upper_extreme(make_worker):
    worker, meter = make_worker()
    original = meter.read_mv
    def offset_mv(**kwargs):
        value, raw, t1, t2 = original(**kwargs)
        return value - 100.0, str(value - 100.0), t1, t2
    meter.read_mv = offset_mv
    capture = worker._capture_waveform(5)
    # Bright MV=-60 has smaller absolute magnitude than dark MV=-100.
    # Both extrema must be checked; tracking absolute maxima alone misses it.
    assert capture.peak_utilization_pct == 40
    assert capture.gp_checks == 2


def test_abort_before_gp_is_not_reported_as_a_device_failure(make_worker):
    worker, meter = make_worker()
    worker._check_abort = lambda: (_ for _ in ()).throw(runtime._AbortRequested())
    with pytest.raises(runtime._AbortRequested):
        worker._read_checked_gp(5, "Acquisition", 0)
    assert not meter.transactions


def test_success_csv_retains_gp_metadata_and_loader_preserves_status(make_worker):
    worker, meter = make_worker(95, range_id=4)
    completed, failed = [], []
    worker.completed.connect(completed.append)
    worker.failed.connect(failed.append)
    worker.run()
    assert completed and not failed
    row = completed[0]["points"][0]
    assert row["schema_version"] == "2.2"
    assert row["range_peak_utilization_pct"] == 9.5
    assert row["range_precheck_peak_pct"] == 9.5
    assert row["range_acquisition_peak_pct"] == 9.5
    assert row["range_check_count"] > 2
    assert row["range_check_status"] == "low_utilization"
    run = load_measurement_run_csv(worker.output_path)
    assert run.points[0].range_utilization_pct == 9.5
    assert run.points[0].range_check_status == "low_utilization"


def test_cw_maximum_csv_also_requires_and_preserves_range_checks(make_worker):
    worker, meter = make_worker()
    worker.mode = runtime.MODE_CW_MAXIMUM
    worker.run()
    run = load_measurement_run_csv(worker.output_path)
    assert run.points[0].lux == 40
    assert run.points[0].candela_cd is None
    assert run.points[0].range_utilization_pct == 40


@pytest.mark.parametrize("field, value", [
    ("range_peak_utilization_pct", "91"), ("range_precheck_peak_pct", "nan"),
    ("range_acquisition_peak_pct", "0"), ("range_check_status", "unverified"),
    ("range_check_count", "1"), ("range_ids", "8"),
    ("range_check_method", "estimated"), ("range_selection_attempts", ""),
])
def test_loader_rejects_invalid_verification_metadata(make_worker, field, value):
    worker, meter = make_worker()
    worker.run()
    with worker.output_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames
        rows = list(reader)
    rows[0][field] = value
    with worker.output_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(ValueError):
        load_measurement_run_csv(worker.output_path)


def test_failed_gp_writes_no_customer_measurement_row(make_worker):
    worker, meter = make_worker(bad_gp=P9710Error("No response to GP"))
    failed, accepted = [], []
    worker.failed.connect(failed.append)
    worker.point_accepted.connect(accepted.append)
    worker.run()
    assert failed and not accepted
    with worker.output_path.open() as stream:
        assert list(csv.DictReader(stream)) == []
    assert meter.configurations == [5, 5, 5]


def test_display_handles_unknown_safe_low_and_over_limit(app):
    widget = MeasurementRangeDisplayV2()
    assert "Unverified" in widget.label.text()
    widget.update_range({"range_id": 4, "peak_pct": 9.5, "state": "low_utilization"})
    assert "R4" in widget.label.text() and "9.5%" in widget.label.text()
    assert "safer range retained" in widget.label.text()
    assert widget.bar.value() == 95
    widget.update_range({"range_id": 5, "peak_pct": 95, "state": "over_limit"})
    assert "rejected" in widget.label.text()
    widget.reset()
    assert "Unverified" in widget.label.text() and widget.bar.value() == 0
    widget.close()
