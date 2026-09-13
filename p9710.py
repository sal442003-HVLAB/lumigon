"""Gigahertz-Optik P-9710 RS232 support for Lumigon.

Validated laboratory settings:
- 9600 baud, 8N1
- LF command terminator
- fixed range during a flash capture
- Schmidt-Clausen MI measurement with one-step synchronization
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import serial


class P9710Error(RuntimeError):
    pass


@dataclass(frozen=True)
class P9710CWReading:
    cw_lx: float
    peak_max_lx: float | None
    peak_min_lx: float | None
    peak_to_peak_lx: float | None
    range_utilization_pct: float | None
    range_id: int
    integration_ms: float
    sync_enabled: bool


@dataclass(frozen=True)
class P9710EffectiveReading:
    e_effective_lx: float
    trigger_sample_lx: float
    range_utilization_pct: float | None
    pretrigger_ms: int
    window_ms: int
    period_s: float
    range_id: int
    software_start_error_ms: float


_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")


def parse_numeric_reply(raw: str) -> float:
    match = _NUMBER_RE.search(raw or "")
    if not match:
        raise P9710Error(f"No numeric value in P-9710 reply: {raw!r}")
    return float(match.group(0))


class P9710:
    def __init__(self, port: str, timeout_s: float = 3.0):
        self.port = str(port).strip()
        self.timeout_s = float(timeout_s)
        self.serial = None
        self.version = None
        self.unit = None

    @property
    def is_connected(self) -> bool:
        return self.serial is not None and self.serial.is_open

    def _open_serial_once(self):
        self.serial = serial.Serial(
            port=self.port,
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout_s,
            write_timeout=self.timeout_s,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

    def connect(self, attempts: int = 3, retry_delay_s: float = 0.25) -> str:
        self.disconnect()
        self.version = None
        self.unit = None
        attempts = max(1, int(attempts))
        last_exc = None

        for attempt in range(1, attempts + 1):
            try:
                self._open_serial_once()
                self.version = self.query("GI")
                self.unit = self.query("GU")
                if not self.version:
                    raise P9710Error("P-9710 did not return a firmware identification.")
                return self.version
            except Exception as exc:
                last_exc = exc
                self.disconnect()
                if attempt < attempts:
                    time.sleep(max(0.0, float(retry_delay_s)))

        raise P9710Error(
            f"Cannot connect to P-9710 on {self.port!r} after {attempts} attempts. "
            f"Last error: {last_exc}"
        ) from last_exc

    def disconnect(self):
        ser = self.serial
        self.serial = None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def query(self, command: str, wait_s: float = 0.01, timeout_s: float | None = None) -> str:
        if not self.is_connected:
            raise P9710Error("P-9710 is not connected.")

        ser = self.serial
        old_timeout = ser.timeout
        if timeout_s is not None:
            ser.timeout = float(timeout_s)
        try:
            ser.reset_input_buffer()
            ser.write((str(command).strip() + "\n").encode("ascii"))
            ser.flush()
            if wait_s > 0:
                time.sleep(wait_s)
            raw = ser.readline().decode("ascii", errors="replace").strip()
        finally:
            ser.timeout = old_timeout

        if not raw:
            raise P9710Error(f"No response to {command!r}.")
        return raw

    def command(self, command: str, wait_s: float = 0.02):
        if not self.is_connected:
            raise P9710Error("P-9710 is not connected.")
        ser = self.serial
        ser.reset_input_buffer()
        ser.write((str(command).strip() + "\n").encode("ascii"))
        ser.flush()
        if wait_s > 0:
            time.sleep(wait_s)
        old_timeout = ser.timeout
        ser.timeout = 0.05
        try:
            ser.readline()
        finally:
            ser.timeout = old_timeout

    def read_mv(self) -> tuple[float, str, float, float]:
        t1 = time.perf_counter()
        raw = self.query("MV", wait_s=0.005)
        t2 = time.perf_counter()
        return parse_numeric_reply(raw), raw, t1, t2

    def read_range_utilization(self) -> float:
        return parse_numeric_reply(self.query("GP", wait_s=0.005))

    def configure_cw(self, *, integration_ms: float = 100.0, range_id: int = 5, sync_enabled: bool = False):
        if integration_ms < 0.1 or integration_ms > 6000.0:
            raise ValueError("CW integration time must be between 0.1 ms and 6000 ms.")
        self.command("SB0")
        self.command(f"SR{int(range_id)}")
        # SN uses 0.1 ms units: SN1000 = 100 ms.
        self.command(f"SN{int(round(float(integration_ms) * 10.0))}")
        self.command("SS1" if sync_enabled else "SS0")

    def read_cw_snapshot(
        self,
        *,
        integration_ms: float = 100.0,
        range_id: int = 5,
        sync_enabled: bool = False,
    ) -> P9710CWReading:
        self.configure_cw(
            integration_ms=integration_ms,
            range_id=range_id,
            sync_enabled=sync_enabled,
        )

        cw_lx, _raw, _t1, _t2 = self.read_mv()

        def optional(command: str):
            try:
                return parse_numeric_reply(self.query(command, wait_s=0.005))
            except Exception:
                return None

        return P9710CWReading(
            cw_lx=cw_lx,
            peak_max_lx=optional("GA"),
            peak_min_lx=optional("GB"),
            peak_to_peak_lx=optional("GD"),
            range_utilization_pct=optional("GP"),
            range_id=int(range_id),
            integration_ms=float(integration_ms),
            sync_enabled=bool(sync_enabled),
        )

    def configure_flash_detection(self, range_id: int = 5):
        self.command("SB0")
        self.command(f"SR{int(range_id)}")
        self.command("SN1")

    def configure_effective(self, window_ms: int, c_s: float = 0.2, range_id: int = 5):
        self.command("SB0")
        self.command(f"SR{int(range_id)}")
        self.command(f"SU{float(c_s):g}")
        self.command(f"SM{int(window_ms)}")
        self.command("SZ0")

    def detect_reference_flash(self, threshold_lx: float = 5.0) -> tuple[float, float]:
        previous_value = 0.0
        previous_t = None

        while True:
            value, _raw, t1, t2 = self.read_mv()
            t_mid = (t1 + t2) / 2.0

            if previous_value < threshold_lx <= value:
                edge_time = t_mid if previous_t is None else (previous_t + t_mid) / 2.0
                return edge_time, value

            previous_value = value
            previous_t = t_mid

    @staticmethod
    def _wait_until(target_time: float):
        while True:
            remaining = target_time - time.perf_counter()
            if remaining <= 0.0:
                return
            if remaining > 0.020:
                time.sleep(remaining - 0.010)

    def synchronized_effective(
        self,
        *,
        period_s: float,
        pretrigger_ms: int,
        window_ms: int,
        threshold_lx: float = 5.0,
        range_id: int = 5,
        c_s: float = 0.2,
    ) -> P9710EffectiveReading:
        if period_s <= 0:
            raise ValueError("Pulse period must be positive.")
        if pretrigger_ms < 0:
            raise ValueError("Pre-trigger cannot be negative.")
        if window_ms <= 0:
            raise ValueError("MI window must be positive.")

        self.configure_flash_detection(range_id=range_id)
        t_ref, trigger_sample = self.detect_reference_flash(threshold_lx=threshold_lx)

        self.configure_effective(window_ms=window_ms, c_s=c_s, range_id=range_id)

        predicted_next_flash = t_ref + float(period_s)
        target_start = predicted_next_flash - (float(pretrigger_ms) / 1000.0)
        self._wait_until(target_start)

        actual_start = time.perf_counter()
        raw = self.query(
            "MI",
            wait_s=(float(window_ms) / 1000.0) + 0.05,
            timeout_s=(float(window_ms) / 1000.0) + 2.0,
        )
        value = parse_numeric_reply(raw)
        start_error_ms = (actual_start - target_start) * 1000.0

        try:
            range_utilization_pct = self.read_range_utilization()
        except Exception:
            range_utilization_pct = None

        return P9710EffectiveReading(
            e_effective_lx=value,
            trigger_sample_lx=trigger_sample,
            range_utilization_pct=range_utilization_pct,
            pretrigger_ms=int(pretrigger_ms),
            window_ms=int(window_ms),
            period_s=float(period_s),
            range_id=int(range_id),
            software_start_error_ms=start_error_ms,
        )
