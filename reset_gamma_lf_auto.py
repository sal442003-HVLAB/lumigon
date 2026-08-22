"""Safely disable Gamma/S1 low-frequency vibration auto-detection.

This utility performs no motion and changes only P1-29 from 1 to 0.
Both servos must be OFF before it will write.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID, P0_01, P0_46, SON_BIT

P1_29 = 0x013A


def main() -> None:
    print("=" * 72)
    print("LUMIGON — RESET GAMMA LF AUTO-DETECTION")
    print("=" * 72)
    print("No motion command will be issued.")

    bus = DeltaModbus(PORT)
    try:
        bus.connect()

        gamma_alarm = bus.read_u16(GAMMA_ID, P0_01)
        c_alarm = bus.read_u16(C_ID, P0_01)
        gamma_status = bus.read_u16(GAMMA_ID, P0_46)
        c_status = bus.read_u16(C_ID, P0_46)
        gamma_son = bool(gamma_status & SON_BIT)
        c_son = bool(c_status & SON_BIT)
        current = bus.read_u16(GAMMA_ID, P1_29)

        print(f"Gamma alarm : 0x{gamma_alarm:04X}")
        print(f"C alarm     : 0x{c_alarm:04X}")
        print(f"Gamma SON   : {gamma_son}")
        print(f"C SON       : {c_son}")
        print(f"Gamma P1-29 : {current}")

        if gamma_alarm != 0 or c_alarm != 0:
            raise RuntimeError("Active servo alarm detected")
        if gamma_son or c_son:
            raise RuntimeError("Both servos must be OFF before resetting P1-29")

        if current == 0:
            print("P1-29 is already 0. Nothing to do.")
            return

        confirmation = input(
            "Type RESET_GAMMA_LF_AUTO exactly to set Gamma P1-29 = 0: "
        ).strip()

        if confirmation != "RESET_GAMMA_LF_AUTO":
            print("Cancelled. No parameter was changed.")
            return

        bus.write_u16(GAMMA_ID, P1_29, 0)
        readback = bus.read_u16(GAMMA_ID, P1_29)
        print(f"Readback P1-29: {readback}")

        if readback != 0:
            raise RuntimeError(f"P1-29 reset failed, readback={readback}")

        print("PASS — Gamma P1-29 reset to 0. No motion command issued.")

    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
