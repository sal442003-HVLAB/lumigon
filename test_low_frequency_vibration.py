"""Lumigon - ASDA-A2 low-frequency vibration diagnostic (READ ONLY).

Reads the ASDA-A2 low-frequency vibration suppression parameters used to
investigate residual mechanical oscillation after positioning. No Modbus
writes are performed.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID


P0_01 = 0x0002   # Alarm
P0_46 = 0x005C   # Status / SON

# ASDA-A2 low-frequency vibration suppression group
P1_25 = 0x0132   # Group 1 detected/manual low-frequency value
P1_26 = 0x0134   # Group 1 response / enable-related value
P1_27 = 0x0136   # Group 2 detected/manual low-frequency value
P1_28 = 0x0138   # Group 2 response / enable-related value
P1_29 = 0x013A   # Auto low-frequency vibration detection
P1_30 = 0x013C   # Low-frequency vibration detection level
P1_36 = 0x0148   # S-curve smoothing time


def read_axis(bus: DeltaModbus, name: str, slave_id: int) -> None:
    print(f"\n=== {name} / S{slave_id} ===")

    alarm = bus.read_u16(slave_id, P0_01)
    status = bus.read_u16(slave_id, P0_46)

    print(f"P0-01 Alarm       = 0x{alarm:04X}")
    print(f"P0-46 Status      = 0x{status:04X}")
    print(f"P1-25 LF group 1  = {bus.read_u16(slave_id, P1_25)}")
    print(f"P1-26 LF resp 1   = {bus.read_u16(slave_id, P1_26)}")
    print(f"P1-27 LF group 2  = {bus.read_u16(slave_id, P1_27)}")
    print(f"P1-28 LF resp 2   = {bus.read_u16(slave_id, P1_28)}")
    print(f"P1-29 LF auto     = {bus.read_u16(slave_id, P1_29)}")
    print(f"P1-30 LF detect   = {bus.read_u16(slave_id, P1_30)}")
    print(f"P1-36 S-curve     = {bus.read_u16(slave_id, P1_36)} ms")


def main() -> None:
    print("Lumigon low-frequency vibration diagnostic - READ ONLY")
    print(f"Port: {PORT}")
    print("No parameters will be written.\n")

    bus = DeltaModbus(PORT)

    try:
        bus.connect()
        read_axis(bus, "Gamma", GAMMA_ID)
        read_axis(bus, "C", C_ID)
        print("\nDiagnostic completed successfully.")
    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
