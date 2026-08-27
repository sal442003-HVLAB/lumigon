"""Temporary virtual hardware backend for off-bench Lumigon UI testing.

Enable only through machine_config.VIRTUAL_HARDWARE. When disabled, this module
is a no-op and the original hardware drivers remain untouched.
"""

from __future__ import annotations

import math
import time

from machine_config import (
    VIRTUAL_HARDWARE,
    GAMMA_ID,
    C_ID,
    P0_01,
    P0_09,
    P0_17,
    P0_46,
    P1_01,
    P1_36,
    P2_30,
    P5_07,
    P5_20,
    P5_60,
    P6_02,
    P6_03,
    SON_BIT,
    PR_CONTROL_WORD,
    GAMMA_SPEED_DEFAULT_RPM,
    GAMMA_RAMP_DEFAULT_MS,
    GAMMA_SCURVE_DEFAULT_MS,
    C_SPEED_DEFAULT_RPM,
    C_RAMP_DEFAULT_MS,
    C_SCURVE_DEFAULT_MS,
)
from delta_modbus import DeltaModbus, DeltaModbusError
from phamp_mb7 import PhAmpMB7


def _init_virtual_registers(bus: DeltaModbus) -> None:
    if hasattr(bus, "_virtual_u16"):
        return

    bus._virtual_u16 = {}
    bus._virtual_s32 = {}
    bus._virtual_u32 = {}

    for slave_id in (GAMMA_ID, C_ID):
        speed = GAMMA_SPEED_DEFAULT_RPM if slave_id == GAMMA_ID else C_SPEED_DEFAULT_RPM
        ramp = GAMMA_RAMP_DEFAULT_MS if slave_id == GAMMA_ID else C_RAMP_DEFAULT_MS
        scurve = GAMMA_SCURVE_DEFAULT_MS if slave_id == GAMMA_ID else C_SCURVE_DEFAULT_MS

        bus._virtual_u16[(slave_id, P0_01)] = 0
        bus._virtual_u16[(slave_id, P0_17)] = 0
        bus._virtual_u16[(slave_id, P0_46)] = SON_BIT | 0x0001 | 0x0004
        bus._virtual_u16[(slave_id, P1_01)] = 1
        bus._virtual_u16[(slave_id, P2_30)] = 0
        bus._virtual_u16[(slave_id, P5_20)] = int(ramp)
        bus._virtual_u16[(slave_id, P5_60)] = round(float(speed) * 10.0)
        bus._virtual_u16[(slave_id, P1_36)] = int(scurve)
        bus._virtual_u16[(slave_id, P5_07)] = 0

        bus._virtual_s32[(slave_id, P0_09)] = 0
        bus._virtual_s32[(slave_id, P6_03)] = 0
        bus._virtual_u32[(slave_id, P6_02)] = PR_CONTROL_WORD


def install_virtual_hardware() -> None:
    """Patch drivers only when VIRTUAL_HARDWARE is enabled."""
    if not VIRTUAL_HARDWARE:
        return
    if getattr(DeltaModbus, "_lumigon_virtual_installed", False):
        return

    DeltaModbus._lumigon_virtual_installed = True

    def virtual_is_connected(self):
        return bool(getattr(self, "_virtual_connected", False))

    def virtual_connect(self):
        _init_virtual_registers(self)
        self._virtual_connected = True

    def virtual_disconnect(self):
        self._virtual_connected = False

    def _require_connected(self):
        if not virtual_is_connected(self):
            raise DeltaModbusError("Virtual Modbus bus is not connected.")
        _init_virtual_registers(self)

    def virtual_read_u16(self, slave_id, address):
        _require_connected(self)
        return int(self._virtual_u16.get((slave_id, address), 0)) & 0xFFFF

    def virtual_read_u32(self, slave_id, address):
        _require_connected(self)
        if (slave_id, address) in self._virtual_u32:
            return int(self._virtual_u32[(slave_id, address)]) & 0xFFFFFFFF
        low = virtual_read_u16(self, slave_id, address)
        high = virtual_read_u16(self, slave_id, address + 1)
        return ((high & 0xFFFF) << 16) | (low & 0xFFFF)

    def virtual_read_s32(self, slave_id, address):
        _require_connected(self)
        if (slave_id, address) in self._virtual_s32:
            return int(self._virtual_s32[(slave_id, address)])
        raw = virtual_read_u32(self, slave_id, address)
        return raw - 0x100000000 if raw & 0x80000000 else raw

    def virtual_write_s32(self, slave_id, address, value):
        _require_connected(self)
        self._virtual_s32[(slave_id, address)] = int(value)

    def virtual_write_u16(self, slave_id, address, value):
        _require_connected(self)
        value = int(value) & 0xFFFF
        self._virtual_u16[(slave_id, address)] = value

        # PR trigger: apply the programmed relative P6-03 displacement instantly
        # to feedback position so the real MotionController can run unchanged.
        if address == P5_07 and value == 1:
            delta = int(self._virtual_s32.get((slave_id, P6_03), 0))
            current = int(self._virtual_s32.get((slave_id, P0_09), 0))
            self._virtual_s32[(slave_id, P0_09)] = current + delta
            self._virtual_u16[(slave_id, P5_07)] = 0

    def virtual_read_registers(self, slave_id, address, count):
        return [virtual_read_u16(self, slave_id, address + i) for i in range(int(count))]

    DeltaModbus.is_connected = property(virtual_is_connected)
    DeltaModbus.connect = virtual_connect
    DeltaModbus.disconnect = virtual_disconnect
    DeltaModbus.read_registers = virtual_read_registers
    DeltaModbus.read_u16 = virtual_read_u16
    DeltaModbus.read_u32 = virtual_read_u32
    DeltaModbus.read_s32 = virtual_read_s32
    DeltaModbus.write_u16 = virtual_write_u16
    DeltaModbus.write_s32 = virtual_write_s32

    # --------------------------------------------------------------
    # Virtual Ph-Amp MB7-compatible backend. It intentionally implements the
    # same public API so Measurement/Live acquisition code needs no changes.
    # --------------------------------------------------------------
    def meter_is_connected(self):
        return bool(getattr(self, "_virtual_connected", False))

    def meter_connect(self):
        self._virtual_connected = True
        return "VIRTUAL 1.0"

    def meter_disconnect(self):
        self._virtual_connected = False

    def meter_configure(self):
        if not meter_is_connected(self):
            raise RuntimeError("Virtual luxmeter is not connected.")

    def meter_version(self):
        if not meter_is_connected(self):
            raise RuntimeError("Virtual luxmeter is not connected.")
        return "VIRTUAL 1.0"

    def meter_serial(self):
        return "VIRTUAL-0001"

    def meter_noop(self):
        if not meter_is_connected(self):
            raise RuntimeError("Virtual luxmeter is not connected.")

    def meter_set_integration(self, milliseconds):
        if not 10 <= int(milliseconds) <= 400:
            raise ValueError("integration time must be in the range 10..400 ms")
        self.integration_time_ms = int(milliseconds)

    def meter_read_current(self):
        if not meter_is_connected(self):
            raise RuntimeError("Virtual luxmeter is not connected.")
        # Slow deterministic drift around 100 lx; useful for Live UI testing.
        lux = 100.0 + 2.5 * math.sin(time.monotonic() * 0.7)
        return lux * self.sensitivity_a_per_lx

    PhAmpMB7.is_connected = property(meter_is_connected)
    PhAmpMB7.connect = meter_connect
    PhAmpMB7.disconnect = meter_disconnect
    PhAmpMB7.configure_for_lumigon = meter_configure
    PhAmpMB7.get_version = meter_version
    PhAmpMB7.get_serial_number = meter_serial
    PhAmpMB7.set_internal_trigger = meter_noop
    PhAmpMB7.set_software_trigger = meter_noop
    PhAmpMB7.enable_autorange = meter_noop
    PhAmpMB7.set_format_photocurrent = meter_noop
    PhAmpMB7.set_integration_time = meter_set_integration
    PhAmpMB7.read_current = meter_read_current
