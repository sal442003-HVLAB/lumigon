"""Gigahertz-Optik P-9710 RS232 support for Lumigon.

Validated laboratory settings:
- 9600 baud, 8N1
- LF command terminator
- fixed range during a flash capture
- Schmidt-Clausen MI measurement with one-step synchronization
"""

from __future__ import annotations

import math
import re
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass

import serial


class P9710Error(RuntimeError):
    pass


class P9710CommandError(P9710Error):
    def __init__(self, command, reply):
        self.command = command
        self.reply = reply
        super().__init__(f"P-9710 rejected command {command!r}: {reply}")


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
    text = (raw or "").strip()
    if text.startswith("?"):
        raise P9710Error(f"P-9710 returned status/error reply: {text}")
    match = _NUMBER_RE.search(text)
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
        self.trace_callback = None
        self._io_lock = threading.RLock()
        self._reply_pending = False
        self.recent_replies = deque(maxlen=16)

    def _trace_reply(self, command, raw, started, finished):
        self.recent_replies.append((str(command), raw, started, finished))
        if self.trace_callback is not None:
            self.trace_callback(str(command), raw, started, finished)

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
        self.recent_replies.clear()
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
        self._reply_pending = False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

    def _exchange(self, command: str, wait_s: float, timeout_s: float | None = None) -> str:
        # Each LF-terminated command has an LF-terminated response, including
        # a bare LF for a successful setter (manual §15.1 and §15.4).
        # A short timeout must not be mistaken for that acknowledgement.
        with self._io_lock:
            if not self.is_connected:
                raise P9710Error("P-9710 is not connected.")
            if self._reply_pending:
                raise P9710Error(
                    "P-9710 response framing is uncertain after a timed-out transaction. "
                    "Wait for the meter to finish, then disconnect and reconnect before retrying."
                )
            ser = self.serial
            old_timeout = ser.timeout
            started = time.perf_counter()
            ser.timeout = self.timeout_s if timeout_s is None else float(timeout_s)
            try:
                ser.reset_input_buffer()
                ser.write((str(command).strip() + "\n").encode("ascii"))
                ser.flush()
                if wait_s > 0:
                    time.sleep(wait_s)
                reply = ser.readline()
            except (serial.SerialException, OSError):
                self._reply_pending = True
                self._trace_reply(command, "<SERIAL READ/WRITE ERROR>", started, time.perf_counter())
                raise
            finally:
                ser.timeout = old_timeout
            raw = reply.decode("ascii", errors="replace").strip()
            if not reply.endswith(b"\n"):
                self._reply_pending = True
                self._trace_reply(command, "<NO RESPONSE>" if not reply else f"<INCOMPLETE> {raw}",
                                  started, time.perf_counter())
                detail = (f"No response to {command!r}." if not reply else
                          f"Incomplete response to {command!r}: {raw!r}.")
                raise P9710Error(detail + " No complete LF acknowledgement received. "
                                 "Wait for the meter to finish, then disconnect and reconnect.")
            self._trace_reply(command, raw, started, time.perf_counter())
            return raw

    def query(self, command: str, wait_s: float = 0.01, timeout_s: float | None = None) -> str:
        raw = self._exchange(command, wait_s, timeout_s)
        if not raw:
            raise P9710Error(f"No response to {command!r}.")
        return raw

    def command(self, command: str, wait_s: float = 0.02):
        raw = self._exchange(command, wait_s)
        if raw.startswith("?") or raw == "*":
            raise P9710CommandError(command, raw)

    def read_mv(self, *, attempts: int = 3, retry_delay_s: float = 0.03) -> tuple[float, str, float, float]:
        attempts = max(1, int(attempts))
        last_exc = None
        for attempt in range(1, attempts + 1):
            t1 = time.perf_counter()
            try:
                raw = self.query("MV", wait_s=0.005)
            except (P9710Error, serial.SerialException, OSError) as exc:
                last_exc = exc
                if attempt >= attempts:
                    raise P9710Error(
                        f"No reliable response to 'MV' after {attempts} attempts. Last error: {exc}"
                    ) from exc
                time.sleep(max(0.0, float(retry_delay_s)))
                continue
            t2 = time.perf_counter()
            value = parse_numeric_reply(raw)
            return value, raw, t1, t2
        raise P9710Error(f"MV read failed: {last_exc}")

    def read_range_utilization(self) -> float:
        return parse_numeric_reply(self.query("GP", wait_s=0.005))

    def configure_cw(self, *, integration_ms: float = 100.0, range_id: int = 5, sync_enabled: bool = False, verify: bool = False):
        if integration_ms < 0.1 or integration_ms > 6000.0:
            raise ValueError("CW integration time must be between 0.1 ms and 6000 ms.")
        self.command("SB0")
        self.command(f"SR{int(range_id)}")
        integration_ticks = int(round(float(integration_ms) * 10.0))
        try:
            self.command(f"SN{integration_ticks}")
        except P9710CommandError as exc:
            # V4.4 was observed rejecting SN1 during flash setup. A rejected
            # setter is harmless only if the required setting is already in
            # effect; never silently use a slower integration for triggering.
            if exc.reply != "?1":
                raise
            guidance = (
                "Stop any front-panel measurement and verify the meter's CW "
                f"integration time is {integration_ticks / 10:g} ms. "
                "Acquisition rejected until the required setting is confirmed."
            )
            try:
                raw = self.query("GS3", wait_s=0.005)
                actual = float(raw.strip())
            except (P9710Error, ValueError) as readback_error:
                raise P9710Error(
                    f"{exc}. CW integration could not be verified using GS3: "
                    f"{readback_error}. {guidance}"
                ) from exc
            if not math.isfinite(actual) or actual != integration_ticks:
                raise P9710Error(
                    f"{exc}. GS3 returned {raw!r} (0.1 ms ticks); "
                    f"required {integration_ticks} ticks ({integration_ticks / 10:g} ms). "
                    f"{guidance}"
                ) from exc
        try:
            self.command("SS1" if sync_enabled else "SS0")
        except P9710CommandError as exc:
            # Some meter states/firmware reject SS0. Continue only when a
            # readback proves synchronization is already disabled. Do not
            # substitute SY: that command selects a calibration wavelength.
            if sync_enabled or exc.reply != "?1":
                raise
            try:
                flags = parse_numeric_reply(self.query("GS7", wait_s=0.005))
            except P9710Error as readback_error:
                raise P9710Error(
                    f"{exc}. Synchronisation OFF could not be verified using GS7: "
                    f"{readback_error}. Stop the meter's running measurement and "
                    "set Setup / Synchronisation to Not active before retrying."
                ) from exc
            # GS7 is an 8-bit flag field, not a Boolean. Manual §15.3.9
            # identifies bit 1 (mask 0x02) as synchronization active.
            # Other set bits must not block an otherwise valid CW read.
            valid_flags = math.isfinite(flags) and flags.is_integer() and 0 <= flags <= 255
            if not valid_flags or int(flags) & 0x02:
                raise P9710Error(
                    f"{exc}. GS7 returned {flags:g}; Synchronisation OFF is not "
                    "confirmed. Set Setup / Synchronisation to Not active before retrying."
                ) from exc
        if verify:
            expected = {"GR": int(range_id), "GS0": 0,
                        "GS3": int(round(float(integration_ms) * 10.0))}
            for command, value in expected.items():
                actual = parse_numeric_reply(self.query(command, wait_s=0.005))
                if not math.isfinite(actual) or actual != value:
                    raise P9710Error(
                        f"P-9710 configuration mismatch: {command} returned "
                        f"{actual:g}, expected {value}. Acquisition rejected."
                    )

    def read_cw_snapshot(self, *, integration_ms: float = 100.0, range_id: int = 5, sync_enabled: bool = False) -> P9710CWReading:
        self.configure_cw(integration_ms=integration_ms, range_id=range_id, sync_enabled=sync_enabled)
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
        self.configure_cw(integration_ms=0.1, range_id=range_id, sync_enabled=False, verify=True)
        time.sleep(0.05)

    def configure_effective(self, window_ms: int, c_s: float = 0.2, range_id: int = 5):
        # Manufacturer manual §15.3.2: SM uses 10 ms ticks, 10..19999.
        if not math.isfinite(float(window_ms)) or not 100 <= window_ms <= 199990 or window_ms % 10:
            raise ValueError("MI window must be 100–199990 ms in 10 ms steps.")
        self.command("SB0")
        self.command(f"SR{int(range_id)}")
        self.command(f"SU{float(c_s):g}")
        self.command(f"SM{int(window_ms // 10)}")
        self.command("SZ0")

    @staticmethod
    def _status_code(exc: Exception) -> str | None:
        text = str(exc)
        if "?16" in text:
            return "overload"
        if "?32" in text:
            return "underload"
        return None

    def detect_reference_flash_adaptive(
        self,
        *,
        start_range_id: int = 5,
        timeout_s: float = 12.0,
        gp_low_pct: float = 15.0,
        gp_high_pct: float = 85.0,
    ) -> tuple[float, float, int, float | None]:
        """Detect a flash rising edge without an absolute lux threshold.

        The detector watches local baseline noise and looks for a statistically
        meaningful positive rise. Range is adjusted only during this detection
        phase. Once a suitable rising edge is found, the selected range is
        returned and must remain fixed for the following MI acquisition.
        """
        range_id = max(0, min(7, int(start_range_id)))
        deadline = time.perf_counter() + max(2.0, float(timeout_s))

        while time.perf_counter() < deadline:
            self.configure_flash_detection(range_id=range_id)
            history: list[tuple[float, float]] = []
            last_value = None
            last_time = None

            while time.perf_counter() < deadline:
                try:
                    value, _raw, t1, t2 = self.read_mv()
                except P9710Error as exc:
                    status = self._status_code(exc)
                    if status == "underload" and range_id < 7:
                        range_id += 1
                        break
                    if status == "overload" and range_id > 0:
                        range_id -= 1
                        break
                    raise

                t_mid = (t1 + t2) / 2.0
                if not math.isfinite(value):
                    continue

                recent = [item[1] for item in history[-8:]]
                if len(recent) >= 4:
                    baseline = statistics.median(recent)
                    deviations = [abs(v - baseline) for v in recent]
                    noise = statistics.median(deviations) if deviations else 0.0
                    rise_floor = max(0.002, 6.0 * noise)
                    rising = (
                        last_value is not None
                        and value > last_value
                        and value - baseline >= rise_floor
                    )
                    if rising:
                        try:
                            gp = self.read_range_utilization()
                        except Exception:
                            gp = None

                        if gp is not None and gp < gp_low_pct and range_id < 7:
                            range_id += 1
                            break
                        if gp is not None and gp > gp_high_pct and range_id > 0:
                            range_id -= 1
                            break

                        edge_time = t_mid if last_time is None else (last_time + t_mid) / 2.0
                        return edge_time, value, range_id, gp

                history.append((t_mid, value))
                if len(history) > 12:
                    history.pop(0)
                last_value = value
                last_time = t_mid

        raise P9710Error(
            "No reliable rising edge was detected within the adaptive trigger window. "
            "Check that the source is flashing and that the detector is receiving some modulated light."
        )

    @staticmethod
    def _wait_until(target_time: float):
        while True:
            remaining = target_time - time.perf_counter()
            if remaining <= 0.0:
                return
            if remaining > 0.020:
                time.sleep(remaining - 0.010)

    def synchronized_effective_adaptive(
        self,
        *,
        period_s: float,
        pretrigger_ms: int,
        window_ms: int,
        start_range_id: int = 5,
        c_s: float = 0.2,
        trigger_timeout_s: float | None = None,
    ) -> P9710EffectiveReading:
        if period_s <= 0:
            raise ValueError("Pulse period must be positive.")
        if pretrigger_ms < 0:
            raise ValueError("Pre-trigger cannot be negative.")
        if window_ms <= 0:
            raise ValueError("MI window must be positive.")

        timeout_s = max(8.0, 2.5 * float(period_s)) if trigger_timeout_s is None else float(trigger_timeout_s)
        t_ref, trigger_sample, selected_range, detection_gp = self.detect_reference_flash_adaptive(
            start_range_id=start_range_id,
            timeout_s=timeout_s,
        )

        self.configure_effective(window_ms=window_ms, c_s=c_s, range_id=selected_range)
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
            range_utilization_pct = detection_gp

        return P9710EffectiveReading(
            e_effective_lx=value,
            trigger_sample_lx=trigger_sample,
            range_utilization_pct=range_utilization_pct,
            pretrigger_ms=int(pretrigger_ms),
            window_ms=int(window_ms),
            period_s=float(period_s),
            range_id=int(selected_range),
            software_start_error_ms=start_error_ms,
        )

    def detect_reference_flash(self, threshold_lx: float = 5.0, timeout_s: float | None = None) -> tuple[float, float]:
        threshold_lx = float(threshold_lx)
        if threshold_lx <= 0.0:
            raise ValueError("Flash trigger threshold must be positive.")
        deadline = None if timeout_s is None else time.perf_counter() + float(timeout_s)
        previous_value = 0.0
        previous_t = None
        last_value = None
        while True:
            if deadline is not None and time.perf_counter() >= deadline:
                detail = "" if last_value is None else f" Last MV={last_value:.4f} lx."
                raise P9710Error(
                    f"No reference flash crossed {threshold_lx:g} lx within {timeout_s:g} s.{detail}"
                )
            value, _raw, t1, t2 = self.read_mv()
            last_value = value
            t_mid = (t1 + t2) / 2.0
            if previous_value < threshold_lx <= value:
                edge_time = t_mid if previous_t is None else (previous_t + t_mid) / 2.0
                return edge_time, value
            previous_value = value
            previous_t = t_mid

    def synchronized_effective(
        self,
        *,
        period_s: float,
        pretrigger_ms: int,
        window_ms: int,
        threshold_lx: float = 5.0,
        range_id: int = 5,
        c_s: float = 0.2,
        trigger_timeout_s: float | None = None,
    ) -> P9710EffectiveReading:
        if period_s <= 0:
            raise ValueError("Pulse period must be positive.")
        if pretrigger_ms < 0:
            raise ValueError("Pre-trigger cannot be negative.")
        if window_ms <= 0:
            raise ValueError("MI window must be positive.")

        self.configure_flash_detection(range_id=range_id)
        t_ref, trigger_sample = self.detect_reference_flash(
            threshold_lx=threshold_lx,
            timeout_s=max(8.0, 2.5 * float(period_s)) if trigger_timeout_s is None else trigger_timeout_s,
        )
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
