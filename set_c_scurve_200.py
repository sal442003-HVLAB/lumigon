"""Safely set C-axis (S2) P1-36 S-curve to 200 ms.

No Servo ON command, no PR trigger, and no movement command are issued.
Both drives must be alarm-free and Servo OFF before the write is allowed.
"""

from delta_modbus import DeltaModbus
from machine_config import PORT, GAMMA_ID, C_ID, P0_01, P0_46, SON_BIT

P1_36 = 0x0148
TARGET_MS = 200
CONFIRM_TEXT = "SET_C_SCURVE"


def main() -> None:
    print("=" * 72)
    print("LUMIGON — SAFE C-AXIS S-CURVE CONFIGURATION")
    print("=" * 72)
    print("No Servo ON command")
    print("No PR trigger")
    print("No movement command")
    print(f"Only C/S2 P1-36 will be changed to {TARGET_MS} ms\n")

    bus = DeltaModbus(PORT)

    try:
        bus.connect()

        gamma_alarm = bus.read_u16(GAMMA_ID, P0_01)
        gamma_status = bus.read_u16(GAMMA_ID, P0_46)
        gamma_son = bool(gamma_status & SON_BIT)

        c_alarm = bus.read_u16(C_ID, P0_01)
        c_status = bus.read_u16(C_ID, P0_46)
        c_son = bool(c_status & SON_BIT)

        old_value = bus.read_u16(C_ID, P1_36)

        print("Preflight:")
        print(f"  Gamma alarm : 0x{gamma_alarm:04X}")
        print(f"  Gamma status: 0x{gamma_status:04X}")
        print(f"  Gamma SON   : {gamma_son}")
        print(f"  C alarm     : 0x{c_alarm:04X}")
        print(f"  C status    : 0x{c_status:04X}")
        print(f"  C SON       : {c_son}")
        print(f"  C P1-36     : {old_value} ms\n")

        if gamma_alarm != 0 or c_alarm != 0:
            raise RuntimeError("Preflight failed: one or both drives have an active alarm.")

        if gamma_son or c_son:
            raise RuntimeError("Preflight failed: both Servo ON signals must be OFF before changing P1-36.")

        if old_value == TARGET_MS:
            print(f"PASS — C P1-36 is already {TARGET_MS} ms. No write was required.")
            return

        confirmation = input(
            f"Type {CONFIRM_TEXT} exactly to write C P1-36 = {TARGET_MS} ms: "
        ).strip()

        if confirmation != CONFIRM_TEXT:
            print("Cancelled — confirmation text did not match. No write performed.")
            return

        bus.write_u16(C_ID, P1_36, TARGET_MS)
        readback = bus.read_u16(C_ID, P1_36)

        print("\n" + "=" * 72)
        print("C-AXIS S-CURVE CONFIGURATION RESULT")
        print("=" * 72)
        print(f"Previous P1-36 : {old_value} ms")
        print(f"Requested P1-36: {TARGET_MS} ms")
        print(f"Readback P1-36 : {readback} ms")

        if readback != TARGET_MS:
            raise RuntimeError(
                f"Verification failed: readback {readback} ms, expected {TARGET_MS} ms."
            )

        print(f"\nPASS — C P1-36 set to {TARGET_MS} ms.")
        print("No motion command was issued.")

    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
