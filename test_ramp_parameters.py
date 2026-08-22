"""Lumigon - ASDA-A2 ramp parameter diagnostic (READ ONLY).

Reads candidate PR acceleration/deceleration table parameters and current
PR configuration from both drives. This script performs no Modbus writes.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID


# ASDA-A2 Modbus addresses used by the current Lumigon commissioning setup.
P0_01 = 0x0002   # Alarm
P0_46 = 0x005C   # Status / SON
P5_20 = 0x0528   # Acc/Dec table candidate 0
P5_21 = 0x052A   # Acc/Dec table candidate 1
P5_22 = 0x052C   # Acc/Dec table candidate 2
P5_23 = 0x052E   # Acc/Dec table candidate 3
P5_60 = 0x0578   # PR speed slot 0
P6_02 = 0x0604   # PR#1 control word


def read_axis(bus: DeltaModbus, name: str, slave_id: int) -> None:
    print(f"\n=== {name} / S{slave_id} ===")

    alarm = bus.read_u16(slave_id, P0_01)
    status = bus.read_u16(slave_id, P0_46)

    print(f"P0-01 Alarm       = 0x{alarm:04X}")
    print(f"P0-46 Status      = 0x{status:04X}")

    for label, address in (
        ("P5-20", P5_20),
        ("P5-21", P5_21),
        ("P5-22", P5_22),
        ("P5-23", P5_23),
        ("P5-60", P5_60),
    ):
        value = bus.read_u16(slave_id, address)
        print(f"{label:<16} = {value} (0x{value:04X})")

    pr_control = bus.read_u32(slave_id, P6_02)
    print(f"P6-02 PR#1 ctrl   = 0x{pr_control:08X}")


def main() -> None:
    print("Lumigon ramp diagnostic - READ ONLY")
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
