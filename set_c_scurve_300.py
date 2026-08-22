"""Safely set C/S2 P1-36 S-curve to 300 ms.

No servo-on command, no PR trigger, and no motion command are issued.
Both servos must be OFF and both alarms must be clear.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID, P0_01, P0_46, P1_36, SON_BIT

TARGET_MS = 300
CONFIRM_TEXT = "SET_C_SCURVE_300"


def main() -> None:
    print("=" * 72)
    print("LUMIGON — SAFE C S-CURVE CONFIGURATION")
    print("=" * 72)
    print("No Servo ON command")
    print("No PR trigger")
    print("No movement command")
    print(f"Only C/S2 P1-36 will be changed to {TARGET_MS} ms")

    bus = DeltaModbus(PORT)

    try:
        bus.connect()

        gamma_alarm = bus.read_u16(GAMMA_ID, P0_01)
        c_alarm = bus.read_u16(C_ID, P0_01)
        gamma_status = bus.read_u16(GAMMA_ID, P0_46)
        c_status = bus.read_u16(C_ID, P0_46)
        gamma_son = bool(gamma_status & SON_BIT)
        c_son = bool(c_status & SON_BIT)
        current = bus.read_u16(C_ID, P1_36)

        print("\nPreflight:")
        print(f"  Gamma alarm : 0x{gamma_alarm:04X}")
        print(f"  Gamma status: 0x{gamma_status:04X}")
        print(f"  Gamma SON   : {gamma_son}")
        print(f"  C alarm     : 0x{c_alarm:04X}")
        print(f"  C status    : 0x{c_status:04X}")
        print(f"  C SON       : {c_son}")
        print(f"  C P1-36     : {current} ms")

        if gamma_alarm != 0 or c_alarm != 0:
            raise RuntimeError("Active servo alarm detected")
        if gamma_son or c_son:
            raise RuntimeError("Both servos must be OFF before changing P1-36")

        confirmation = input(
            f"\nType {CONFIRM_TEXT} exactly to write C P1-36 = {TARGET_MS} ms: "
        ).strip()

        if confirmation != CONFIRM_TEXT:
            print("Cancelled. No parameter was changed.")
            return

        bus.write_u16(C_ID, P1_36, TARGET_MS)
        readback = bus.read_u16(C_ID, P1_36)

        print("\n" + "=" * 72)
        print("C S-CURVE CONFIGURATION RESULT")
        print("=" * 72)
        print(f"Previous P1-36 : {current} ms")
        print(f"Requested P1-36: {TARGET_MS} ms")
        print(f"Readback P1-36 : {readback} ms")

        if readback != TARGET_MS:
            raise RuntimeError(
                f"C P1-36 verification failed: readback={readback}"
            )

        print(f"\nPASS — C P1-36 set to {TARGET_MS} ms.")
        print("No motion command was issued.")

    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
