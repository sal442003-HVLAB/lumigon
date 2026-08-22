"""Lumigon - safe Gamma S-curve configuration test.

This script changes ONLY Gamma/S1 P1-36 from its current value to 200 ms.
It does NOT issue Servo ON, PR trigger, P6-03 write, or any motion command.

Safety preconditions:
- Both drives must report no alarm.
- Both servos must be OFF.
- User must type SET_GAMMA_SCURVE exactly before the write.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID, P0_01, P0_46, SON_BIT

P1_36 = 0x0148
TARGET_SCURVE_MS = 200


def main() -> None:
    print("=" * 72)
    print("LUMIGON — SAFE GAMMA S-CURVE CONFIGURATION")
    print("=" * 72)
    print("No Servo ON command")
    print("No PR trigger")
    print("No movement command")
    print("Only Gamma/S1 P1-36 will be changed to 200 ms")
    print()

    bus = DeltaModbus(PORT)

    try:
        bus.connect()

        gamma_alarm = bus.read_u16(GAMMA_ID, P0_01)
        c_alarm = bus.read_u16(C_ID, P0_01)
        gamma_status = bus.read_u16(GAMMA_ID, P0_46)
        c_status = bus.read_u16(C_ID, P0_46)
        gamma_son = bool(gamma_status & SON_BIT)
        c_son = bool(c_status & SON_BIT)
        old_value = bus.read_u16(GAMMA_ID, P1_36)

        print("Preflight:")
        print(f"  Gamma alarm : 0x{gamma_alarm:04X}")
        print(f"  Gamma status: 0x{gamma_status:04X}")
        print(f"  Gamma SON   : {gamma_son}")
        print(f"  C alarm     : 0x{c_alarm:04X}")
        print(f"  C status    : 0x{c_status:04X}")
        print(f"  C SON       : {c_son}")
        print(f"  Gamma P1-36 : {old_value} ms")
        print()

        if gamma_alarm != 0 or c_alarm != 0:
            raise RuntimeError("An alarm is active. Configuration aborted.")

        if gamma_son or c_son:
            raise RuntimeError(
                "Both servos must be OFF before changing P1-36. Configuration aborted."
            )

        if old_value == TARGET_SCURVE_MS:
            print("Gamma P1-36 is already 200 ms. No write required.")
            return

        confirmation = input(
            "Type SET_GAMMA_SCURVE exactly to write Gamma P1-36 = 200 ms: "
        ).strip()

        if confirmation != "SET_GAMMA_SCURVE":
            print("Configuration cancelled. No register was written.")
            return

        bus.write_u16(GAMMA_ID, P1_36, TARGET_SCURVE_MS)

        readback = bus.read_u16(GAMMA_ID, P1_36)

        print()
        print("=" * 72)
        print("GAMMA S-CURVE CONFIGURATION RESULT")
        print("=" * 72)
        print(f"Previous P1-36 : {old_value} ms")
        print(f"Requested P1-36: {TARGET_SCURVE_MS} ms")
        print(f"Readback P1-36 : {readback} ms")

        if readback != TARGET_SCURVE_MS:
            raise RuntimeError(
                f"P1-36 verification failed: read {readback}, "
                f"expected {TARGET_SCURVE_MS}."
            )

        print("\nPASS — Gamma P1-36 set to 200 ms.")
        print("No motion command was issued.")

    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
