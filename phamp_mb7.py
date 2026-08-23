"""Driver for the Czibula & Grundmann Ph-Amp MB7 photometer amplifier.

The Lumigon integration intentionally reads photocurrent (F0) and performs the
lux conversion in software. This keeps the photometer-head sensitivity visible
and version-controlled instead of relying on the amplifier's EEPROM calibration
factor.

The tested hardware currently answers as firmware V1.22. That firmware does
not necessarily acknowledge setting commands, so this driver verifies settings
with read-back queries rather than depending on an ``OK`` response.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import statistics
import time
from typing import Optional

import serial


DEFAULT_BAUDRATE = 19200
DEFAULT_SENSITIVITY_NA_PER_LX = 13.47
DEFAULT_INTEGRATION_TIME_MS = 100

_CURRENT_RE = re.compile(
    r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
)


class PhAmpError(RuntimeError):
    """Base error for Ph-Amp communication or parsing failures."""


class PhAmpNotConnectedError(PhAmpError):
    """Raised when an operation requires an open serial connection."""


class PhAmpProtocolError(PhAmpError):
    """Raised when the amplifier returns an unexpected response."""


@dataclass(frozen=True)
class LuxReading:
    """One processed Lumigon illuminance result."""

    lux: float
    mean_current_a: float
    samples: int
    stdev_lux: float


class PhAmpMB7:
    """Serial driver for a Ph-Amp MB7 connected through an SPP COM port."""

    def __init__(
        self,
        port: str,
        *,
        sensitivity_na_per_lx: float = DEFAULT_SENSITIVITY_NA_PER_LX,
        baudrate: int = DEFAULT_BAUDRATE,
        timeout: float = 2.0,
        integration_time_ms: int = DEFAULT_INTEGRATION_TIME_MS,
        rtscts: bool = False,
    ) -> None:
        if sensitivity_na_per_lx <= 0:
            raise ValueError("sensitivity_na_per_lx must be greater than zero")
        if not 10 <= integration_time_ms <= 400:
            raise ValueError("integration_time_ms must be in the range 10..400 ms")

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.integration_time_ms = integration_time_ms
        self.rtscts = rtscts
        self.sensitivity_na_per_lx = sensitivity_na_per_lx
        self._serial: Optional[serial.Serial] = None

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    @property
    def sensitivity_a_per_lx(self) -> float:
        return self.sensitivity_na_per_lx * 1e-9

    def connect(self) -> str:
        """Open the serial port and return the amplifier identification string."""
        if self.is_connected:
            return self.get_version()

        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                write_timeout=self.timeout,
                rtscts=self.rtscts,
            )
        except serial.SerialException as exc:
            self._serial = None
            raise PhAmpError(f"Could not open {self.port}: {exc}") from exc

        # Bluetooth SPP can need a little time after COM open before the serial
        # path is fully settled. The identification query is also our link test.
        time.sleep(0.40)
        self._serial.reset_input_buffer()

        try:
            return self.get_version()
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "PhAmpMB7":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.disconnect()

    def _require_serial(self) -> serial.Serial:
        if not self.is_connected:
            raise PhAmpNotConnectedError("Ph-Amp is not connected")
        assert self._serial is not None
        return self._serial

    def _write_command(self, command: str) -> None:
        ser = self._require_serial()
        payload = (command + "\r").encode("ascii")
        try:
            ser.write(payload)
            ser.flush()
        except serial.SerialException as exc:
            raise PhAmpError(f"Serial write failed for {command!r}: {exc}") from exc

    def _query_once(self, command: str) -> str:
        ser = self._require_serial()
        ser.reset_input_buffer()
        self._write_command(command)
        try:
            raw = ser.readline()
        except serial.SerialException as exc:
            raise PhAmpError(f"Serial read failed for {command!r}: {exc}") from exc

        if not raw:
            raise PhAmpProtocolError(f"No response to {command!r}")

        response = raw.decode("ascii", errors="replace").strip()
        if not response:
            raise PhAmpProtocolError(f"Empty response to {command!r}")
        return response

    def _query(self, command: str, *, attempts: int = 1, retry_delay_s: float = 0.10) -> str:
        """Query the device, optionally retrying transient no-response cases.

        The Bluetooth SPP link and this older V1.22 firmware can occasionally
        miss the first parameter query immediately after a setting command.
        Measurement queries remain single-shot unless a caller explicitly asks
        for retries.
        """
        if attempts < 1:
            raise ValueError("attempts must be at least 1")

        last_error: Optional[PhAmpProtocolError] = None
        for attempt in range(attempts):
            try:
                return self._query_once(command)
            except PhAmpProtocolError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(retry_delay_s)

        assert last_error is not None
        raise last_error

    def _set_and_verify(
        self,
        set_command: str,
        query_command: str,
        expected: str,
    ) -> str:
        """Set a V1-compatible parameter and verify it using read-back.

        V1.22 often sends no acknowledgement for setting commands. Allow enough
        processing time, discard an acknowledgement only when one is actually
        present, then retry the read-back query to tolerate a transient missed
        response over Bluetooth SPP.
        """
        ser = self._require_serial()
        ser.reset_input_buffer()
        self._write_command(set_command)
        time.sleep(0.10)

        if ser.in_waiting:
            ser.readline()

        actual = self._query(
            query_command,
            attempts=3,
            retry_delay_s=0.15,
        )
        if actual.strip().upper() != expected.strip().upper():
            raise PhAmpProtocolError(
                f"Verification failed for {set_command!r}: "
                f"expected {expected!r}, got {actual!r}"
            )
        return actual

    def get_version(self) -> str:
        return self._query("V?", attempts=2, retry_delay_s=0.15)

    def get_serial_number(self) -> str:
        return self._query("SN?", attempts=2, retry_delay_s=0.15)

    def configure_for_lumigon(self) -> None:
        """Configure volatile measurement parameters used by Lumigon.

        No SAVE, E calibration-factor write, EEPROM clear, or reset command is
        issued here. The hardware calibration factor remains untouched.
        """
        self.set_format_photocurrent()
        self.set_software_trigger()
        self.enable_autorange()
        self.set_integration_time(self.integration_time_ms)

    def set_format_photocurrent(self) -> None:
        self._set_and_verify("F0", "F?", "F0")

    def set_software_trigger(self) -> None:
        # Tested V1.22 returns "1" for T? rather than "T1".
        self._set_and_verify("T1", "T?", "1")

    def enable_autorange(self) -> None:
        # Tested V1.22 returns "1" for RA? rather than "RA1".
        self._set_and_verify("RA", "RA?", "1")

    def set_integration_time(self, milliseconds: int) -> None:
        if not 10 <= milliseconds <= 400:
            raise ValueError("integration time must be in the range 10..400 ms")
        self._set_and_verify(f"I{milliseconds}", "I?", str(milliseconds))
        self.integration_time_ms = milliseconds

    def read_current(self) -> float:
        """Trigger one measurement and return photocurrent in amperes."""
        response = self._query("M?")
        match = _CURRENT_RE.search(response)
        if match is None:
            raise PhAmpProtocolError(
                f"Could not parse photocurrent from response {response!r}"
            )

        try:
            return float(match.group(0))
        except ValueError as exc:
            raise PhAmpProtocolError(
                f"Invalid photocurrent value in response {response!r}"
            ) from exc

    def current_to_lux(self, current_a: float) -> float:
        return current_a / self.sensitivity_a_per_lx

    def read_lux(self, samples: int = 5, sample_delay_s: float = 0.05) -> LuxReading:
        """Average multiple photocurrent readings and convert them to lux."""
        if samples < 1:
            raise ValueError("samples must be at least 1")
        if sample_delay_s < 0:
            raise ValueError("sample_delay_s cannot be negative")

        currents: list[float] = []
        lux_values: list[float] = []

        for index in range(samples):
            current_a = self.read_current()
            currents.append(current_a)
            lux_values.append(self.current_to_lux(current_a))
            if index + 1 < samples and sample_delay_s:
                time.sleep(sample_delay_s)

        mean_current_a = statistics.fmean(currents)
        mean_lux = statistics.fmean(lux_values)
        stdev_lux = statistics.stdev(lux_values) if samples > 1 else 0.0

        return LuxReading(
            lux=mean_lux,
            mean_current_a=mean_current_a,
            samples=samples,
            stdev_lux=stdev_lux,
        )
