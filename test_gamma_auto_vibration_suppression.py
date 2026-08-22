"""Lumigon - controlled Gamma low-frequency vibration auto-detection test.

WARNING: This script writes Gamma/S1 vibration-suppression parameters and
issues a small real motion command. Use only with the physical E-STOP ready.

The script:
1) validates alarms/status/configuration,
2) requires C servo OFF and Gamma servo ON,
3) snapshots P1-25..P1-30,
4) enables P1-29 auto vibration detection,
5) moves Gamma +1.0 degree using the already-validated PR#1 relative move,
6) waits for position completion,
7) reads P1-25..P1-30 after the move,
8) returns Gamma to the starting feedback position,
9) prints all before/after values.

It does not touch C-axis parameters.
"""

import time

from delta_modbus import DeltaModbus
from machine_config import (
    PORT,
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
    P5_60,
    P6_02,
    P6_03,
    SON_BIT,
    PR_CONTROL_WORD,
    PR_SPEED_RAW,
    REQUIRED_SCURVE_MS,
    GAMMA_PUU_PER_DEGREE,
    GAMMA_SIGN,
)

# Low-frequency vibration suppression parameters
P1_25 = 0x0132
P1_26 = 0x0134
P1_27 = 0x0136
P1_28 = 0x0138
P1_29 = 0x013A
P1_30 = 0x013C

TEST_DEGREE = 1.0
POSITION_TOLERANCE_PUU = 30
MOVE_TIMEOUT_S = 10.0


def degree_to_puu(degree: float) -> int:
    return round(degree * GAMMA_PUU_PER_DEGREE * GAMMA_SIGN)


def wait_for_feedback(bus: DeltaModbus, expected: int) -> int:
    deadline = time.monotonic() + MOVE_TIMEOUT_S
    last = None

    while time.monotonic() < deadline:
        alarm = bus.read_u16(GAMMA_ID, P0_01)
        if alarm != 0:
            raise RuntimeError(f"Gamma alarm 0x{alarm:04X} during motion")

        last = bus.read_s32(GAMMA_ID, P0_09)
        if abs(last - expected) <= POSITION_TOLERANCE_PUU:
            return last

        time.sleep(0.05)

    raise RuntimeError(
        f"Gamma motion timeout. Expected {expected:+d} PUU, last {last:+d} PUU"
    )


def read_lf(bus: DeltaModbus) -> dict[str, int]:
    return {
        "P1-25": bus.read_u16(GAMMA_ID, P1_25),
        "P1-26": bus.read_u16(GAMMA_ID, P1_26),
        "P1-27": bus.read_u16(GAMMA_ID, P1_27),
        "P1-28": bus.read_u16(GAMMA_ID, P1_28),
        "P1-29": bus.read_u16(GAMMA_ID, P1_29),
        "P1-30": bus.read_u16(GAMMA_ID, P1_30),
    }


def print_lf(title: str, values: dict[str, int]) -> None:
    print(f"\n{title}")
    for key, value in values.items():
        print(f"  {key:<5} = {value}")


def verify_preflight(bus: DeltaModbus) -> tuple[int, int, int, int]:
    gamma_alarm = bus.read_u16(GAMMA_ID, P0_01)
    c_alarm = bus.read_u16(C_ID, P0_01)
    gamma_status = bus.read_u16(GAMMA_ID, P0_46)
    c_status = bus.read_u16(C_ID, P0_46)

    gamma_son = bool(gamma_status & SON_BIT)
    c_son = bool(c_status & SON_BIT)

    print("\nPreflight:")
    print(f"  Gamma alarm : 0x{gamma_alarm:04X}")
    print(f"  Gamma status: 0x{gamma_status:04X}")
    print(f"  Gamma SON   : {gamma_son}")
    print(f"  C alarm     : 0x{c_alarm:04X}")
    print(f"  C status    : 0x{c_status:04X}")
    print(f"  C SON       : {c_son}")

    if gamma_alarm != 0 or c_alarm != 0:
        raise RuntimeError("Active servo alarm detected")
    if not gamma_son:
        raise RuntimeError("Gamma servo must be ON for this test")
    if c_son:
        raise RuntimeError("C servo must be OFF for this test")

    mode = bus.read_u16(GAMMA_ID, P1_01)
    simulation = bus.read_u16(GAMMA_ID, P2_30)
    monitor = bus.read_u16(GAMMA_ID, P0_17)
    speed = bus.read_u16(GAMMA_ID, P5_60)
    control = bus.read_u32(GAMMA_ID, P6_02)
    scurve = bus.read_u16(GAMMA_ID, P1_36)

    print(f"  Gamma P1-01 : {mode}")
    print(f"  Gamma P2-30 : {simulation}")
    print(f"  Gamma P0-17 : {monitor}")
    print(f"  Gamma P5-60 : {speed}")
    print(f"  Gamma P6-02 : 0x{control:08X}")
    print(f"  Gamma P1-36 : {scurve} ms")

    if mode != 1:
        raise RuntimeError("Gamma is not in PR mode")
    if simulation != 0:
        raise RuntimeError("Gamma P2-30 must be 0")
    if monitor != 0:
        raise RuntimeError("Gamma P0-09 is not feedback position")
    if speed != PR_SPEED_RAW:
        raise RuntimeError(
            f"Gamma PR speed {speed / 10:.1f} rpm != expected {PR_SPEED_RAW / 10:.1f} rpm"
        )
    if control != PR_CONTROL_WORD:
        raise RuntimeError(
            f"Gamma P6-02 0x{control:08X} != expected 0x{PR_CONTROL_WORD:08X}"
        )
    if scurve != REQUIRED_SCURVE_MS:
        raise RuntimeError(
            f"Gamma P1-36 {scurve} ms != required {REQUIRED_SCURVE_MS} ms"
        )

    return gamma_alarm, gamma_status, c_alarm, c_status


def execute_relative(bus: DeltaModbus, delta_puu: int) -> int:
    feedback_before = bus.read_s32(GAMMA_ID, P0_09)
    expected = feedback_before + delta_puu

    bus.write_s32(GAMMA_ID, P6_03, delta_puu)
    readback = bus.read_s32(GAMMA_ID, P6_03)
    if readback != delta_puu:
        raise RuntimeError(
            f"P6-03 verification failed: read {readback:+d}, expected {delta_puu:+d}"
        )

    bus.write_u16(GAMMA_ID, P5_07, 1)
    return wait_for_feedback(bus, expected)


def main() -> None:
    print("=" * 72)
    print("LUMIGON — GAMMA AUTO LOW-FREQUENCY VIBRATION TEST")
    print("=" * 72)
    print("REAL MOTION TEST: Gamma +1.0° then return to start")
    print("C servo must remain OFF")
    print("Keep the physical E-STOP in hand and the mechanism clear")

    bus = DeltaModbus(PORT)

    try:
        bus.connect()
        verify_preflight(bus)

        start_feedback = bus.read_s32(GAMMA_ID, P0_09)
        before = read_lf(bus)
        print(f"\nGamma start feedback: {start_feedback:+d} PUU")
        print_lf("LF parameters BEFORE", before)

        confirmation = input(
            "\nType RUN_GAMMA_LF_AUTO exactly to enable P1-29 auto detection "
            "and execute the +1.0° test: "
        ).strip()

        if confirmation != "RUN_GAMMA_LF_AUTO":
            print("Cancelled. No parameter or motion command issued.")
            return

        print("\nEnabling Gamma P1-29 auto detection...")
        bus.write_u16(GAMMA_ID, P1_29, 1)
        p1_29_rb = bus.read_u16(GAMMA_ID, P1_29)
        print(f"P1-29 readback immediately after write: {p1_29_rb}")
        if p1_29_rb != 1:
            raise RuntimeError(
                f"Gamma P1-29 write verification failed, readback={p1_29_rb}"
            )

        delta_puu = degree_to_puu(TEST_DEGREE)
        print(f"\nMoving Gamma +{TEST_DEGREE:.1f}° ({delta_puu:+d} PUU)...")
        forward_feedback = execute_relative(bus, delta_puu)
        print(f"Forward feedback reached: {forward_feedback:+d} PUU")

        # Give the drive time to finish its vibration-identification update.
        time.sleep(1.0)
        after_forward = read_lf(bus)
        print_lf("LF parameters AFTER FORWARD MOVE", after_forward)

        print("\nReturning Gamma to the starting feedback position...")
        current = bus.read_s32(GAMMA_ID, P0_09)
        return_delta = start_feedback - current
        returned_feedback = execute_relative(bus, return_delta)
        print(f"Returned feedback: {returned_feedback:+d} PUU")

        time.sleep(1.0)
        after_return = read_lf(bus)
        print_lf("LF parameters AFTER RETURN", after_return)

        final_alarm = bus.read_u16(GAMMA_ID, P0_01)
        final_status = bus.read_u16(GAMMA_ID, P0_46)

        print("\n" + "=" * 72)
        print("GAMMA LF AUTO TEST RESULT")
        print("=" * 72)
        print(f"Start feedback : {start_feedback:+d} PUU")
        print(f"Final feedback : {returned_feedback:+d} PUU")
        print(f"Position delta : {returned_feedback - start_feedback:+d} PUU")
        print(f"Final alarm    : 0x{final_alarm:04X}")
        print(f"Final status   : 0x{final_status:04X}")
        print(f"Final P1-29    : {after_return['P1-29']}")
        print("\nCompare P1-25..P1-28 before/after and report whether the")
        print("post-position vibration became smaller, unchanged, or worse.")

    finally:
        bus.disconnect()


if __name__ == "__main__":
    main()
