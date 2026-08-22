"""Lumigon - refined C-axis low-frequency vibration auto-detection test.

This is a real-motion commissioning test for C/S2 only.

Key changes from v1:
- Uses a lower temporary P1-30 detection level of 150 pulses.
- Treats auto-detection as SUCCESS only when P1-29 returns to 0 AND
  P1-26 or P1-28 becomes non-zero.
- If P1-29 returns to 0 while both gains remain 0, the test reports
  "no vibration frequency detected" instead of a false success.
- Gamma parameters are untouched.
- C always returns to its starting feedback position.
- P1-29 is forced back to 0 and P1-30 restored during cleanup.

Use with Gamma OFF, C ON, mechanism clear, and E-STOP ready.
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
    EXPECTED_SCURVE_MS,
    C_PUU_PER_DEGREE,
    C_SIGN,
)

P1_25 = 0x0132
P1_26 = 0x0134
P1_27 = 0x0136
P1_28 = 0x0138
P1_29 = 0x013A
P1_30 = 0x013C

TEST_AMPLITUDE_DEG = 5.0
MAX_SEGMENT_DEG = 1.0
MAX_CYCLES = 3
DETECTION_THRESHOLD = 150
POSITION_TOLERANCE_PUU = 35
MOVE_TIMEOUT_S = 10.0


def degree_to_puu(degree: float) -> int:
    return round(degree * C_PUU_PER_DEGREE * C_SIGN)


def wait_for_feedback(bus: DeltaModbus, expected: int) -> int:
    deadline = time.monotonic() + MOVE_TIMEOUT_S
    last = None

    while time.monotonic() < deadline:
        alarm = bus.read_u16(C_ID, P0_01)
        if alarm != 0:
            raise RuntimeError(f"C alarm 0x{alarm:04X} during motion")

        last = bus.read_s32(C_ID, P0_09)
        if abs(last - expected) <= POSITION_TOLERANCE_PUU:
            return last

        time.sleep(0.05)

    raise RuntimeError(
        f"C motion timeout. Expected {expected:+d} PUU, last {last:+d} PUU"
    )


def read_lf(bus: DeltaModbus) -> dict[str, int]:
    return {
        "P1-25": bus.read_u16(C_ID, P1_25),
        "P1-26": bus.read_u16(C_ID, P1_26),
        "P1-27": bus.read_u16(C_ID, P1_27),
        "P1-28": bus.read_u16(C_ID, P1_28),
        "P1-29": bus.read_u16(C_ID, P1_29),
        "P1-30": bus.read_u16(C_ID, P1_30),
    }


def print_lf(title: str, values: dict[str, int]) -> None:
    print(f"\n{title}")
    for key, value in values.items():
        print(f"  {key:<5} = {value}")


def suppression_enabled(values: dict[str, int]) -> bool:
    return values["P1-26"] != 0 or values["P1-28"] != 0


def verify_preflight(bus: DeltaModbus) -> None:
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
    if gamma_son:
        raise RuntimeError("Gamma servo must be OFF")
    if not c_son:
        raise RuntimeError("C servo must be ON")

    mode = bus.read_u16(C_ID, P1_01)
    simulation = bus.read_u16(C_ID, P2_30)
    monitor = bus.read_u16(C_ID, P0_17)
    speed = bus.read_u16(C_ID, P5_60)
    control = bus.read_u32(C_ID, P6_02)
    scurve = bus.read_u16(C_ID, P1_36)

    print(f"  C P1-01 : {mode}")
    print(f"  C P2-30 : {simulation}")
    print(f"  C P0-17 : {monitor}")
    print(f"  C P5-60 : {speed}")
    print(f"  C P6-02 : 0x{control:08X}")
    print(f"  C P1-36 : {scurve} ms")

    if mode != 1:
        raise RuntimeError("C is not in PR mode")
    if simulation != 0:
        raise RuntimeError("C P2-30 must be 0")
    if monitor != 0:
        raise RuntimeError("C P0-09 is not feedback position")
    if speed != PR_SPEED_RAW:
        raise RuntimeError("Unexpected C PR speed")
    if control != PR_CONTROL_WORD:
        raise RuntimeError("Unexpected C PR control word")
    if scurve != EXPECTED_SCURVE_MS:
        raise RuntimeError(
            f"C P1-36 {scurve} ms != required {EXPECTED_SCURVE_MS} ms"
        )


def execute_relative_puu(bus: DeltaModbus, delta_puu: int) -> int:
    before = bus.read_s32(C_ID, P0_09)
    expected = before + delta_puu

    bus.write_s32(C_ID, P6_03, delta_puu)
    readback = bus.read_s32(C_ID, P6_03)
    if readback != delta_puu:
        raise RuntimeError(
            f"C P6-03 verification failed: read {readback:+d}, expected {delta_puu:+d}"
        )

    bus.write_u16(C_ID, P5_07, 1)
    return wait_for_feedback(bus, expected)


def auto_state(bus: DeltaModbus) -> tuple[bool, dict[str, int]]:
    values = read_lf(bus)
    success = values["P1-29"] == 0 and suppression_enabled(values)
    return success, values


def move_relative_segmented(bus: DeltaModbus, delta_degree: float) -> tuple[int, bool]:
    remaining = delta_degree
    last_feedback = bus.read_s32(C_ID, P0_09)

    while abs(remaining) > 1e-9:
        step = min(remaining, MAX_SEGMENT_DEG) if remaining > 0 else max(remaining, -MAX_SEGMENT_DEG)
        delta_puu = degree_to_puu(step)
        print(f"    PR segment {step:+.1f}° ({delta_puu:+d} PUU)")
        last_feedback = execute_relative_puu(bus, delta_puu)
        remaining -= step

        success, values = auto_state(bus)
        if values["P1-29"] == 0:
            if success:
                print("    SUCCESS: C auto detection completed and LF suppression was enabled.")
            else:
                print("    P1-29 returned to 0, but P1-26/P1-28 are still 0: no LF frequency detected.")
            return last_feedback, success

    return last_feedback, False


def return_to_start(bus: DeltaModbus, start_feedback: int) -> int:
    current = bus.read_s32(C_ID, P0_09)
    delta_puu = start_feedback - current
    max_step_puu = abs(degree_to_puu(MAX_SEGMENT_DEG))

    while abs(delta_puu) > POSITION_TOLERANCE_PUU:
        step_puu = min(delta_puu, max_step_puu) if delta_puu > 0 else max(delta_puu, -max_step_puu)
        current = execute_relative_puu(bus, step_puu)
        delta_puu = start_feedback - current

    return current


def main() -> None:
    print("=" * 72)
    print("LUMIGON — C LF AUTO DETECTION v2")
    print("=" * 72)
    print("REAL MOTION TEST")
    print(f"Motion envelope around start: ±{TEST_AMPLITUDE_DEG:.1f}°")
    print(f"Maximum individual PR segment: {MAX_SEGMENT_DEG:.1f}°")
    print(f"Maximum cycles: {MAX_CYCLES}")
    print(f"Temporary P1-30 detection threshold: {DETECTION_THRESHOLD} pulses")
    print("Gamma must remain OFF. Keep E-STOP ready.")

    bus = DeltaModbus(PORT)
    original_p1_30 = None
    start_feedback = None

    try:
        bus.connect()
        verify_preflight(bus)

        start_feedback = bus.read_s32(C_ID, P0_09)
        before = read_lf(bus)
        original_p1_30 = before["P1-30"]

        print(f"\nC start feedback: {start_feedback:+d} PUU")
        print_lf("C LF parameters BEFORE", before)

        confirmation = input(
            "\nType RUN_C_LF_V2 exactly to start this real-motion test: "
        ).strip()
        if confirmation != "RUN_C_LF_V2":
            print("Cancelled. No changes or motion issued.")
            return

        bus.write_u16(C_ID, P1_29, 0)
        if bus.read_u16(C_ID, P1_29) != 0:
            raise RuntimeError("Failed to reset C P1-29")

        print(f"Setting temporary C P1-30 = {DETECTION_THRESHOLD}...")
        bus.write_u16(C_ID, P1_30, DETECTION_THRESHOLD)
        if bus.read_u16(C_ID, P1_30) != DETECTION_THRESHOLD:
            raise RuntimeError("Failed to set temporary C P1-30")

        print("Enabling C P1-29 auto detection...")
        bus.write_u16(C_ID, P1_29, 1)
        if bus.read_u16(C_ID, P1_29) != 1:
            raise RuntimeError("Failed to enable C P1-29 auto detection")

        success = False
        no_frequency_detected = False

        for cycle in range(1, MAX_CYCLES + 1):
            print(f"\n--- Detection cycle {cycle}/{MAX_CYCLES} ---")

            print(f"  Move to +{TEST_AMPLITUDE_DEG:.1f}° relative to start")
            _, success = move_relative_segmented(bus, +TEST_AMPLITUDE_DEG)
            state = read_lf(bus)
            if success:
                break
            if state["P1-29"] == 0:
                no_frequency_detected = True
                break

            print(f"  Sweep to -{TEST_AMPLITUDE_DEG:.1f}° relative to start")
            _, success = move_relative_segmented(bus, -2.0 * TEST_AMPLITUDE_DEG)
            state = read_lf(bus)
            if success:
                break
            if state["P1-29"] == 0:
                no_frequency_detected = True
                break

            print("  Return through start")
            _, success = move_relative_segmented(bus, +TEST_AMPLITUDE_DEG)
            state = read_lf(bus)
            if success:
                break
            if state["P1-29"] == 0:
                no_frequency_detected = True
                break

        print("\nReturning C to exact starting feedback...")
        returned = return_to_start(bus, start_feedback)
        print(f"Returned feedback: {returned:+d} PUU")

        time.sleep(1.0)
        after = read_lf(bus)
        print_lf("C LF parameters AFTER TEST", after)

        print("\n" + "=" * 72)
        print("RESULT")
        print("=" * 72)
        print(f"Suppression enabled       : {suppression_enabled(after)}")
        print(f"True LF detection success : {success}")
        print(f"No-frequency outcome      : {no_frequency_detected}")
        print(f"C P1-29 final state       : {after['P1-29']}")
        print(f"Position error            : {returned - start_feedback:+d} PUU")

    finally:
        if bus.is_connected:
            try:
                if start_feedback is not None:
                    try:
                        return_to_start(bus, start_feedback)
                    except Exception as exc:
                        print(f"WARNING: return-to-start cleanup failed: {exc}")

                try:
                    if bus.read_u16(C_ID, P1_29) != 0:
                        print("Cleanup: resetting C P1-29 to 0...")
                        bus.write_u16(C_ID, P1_29, 0)
                except Exception as exc:
                    print(f"WARNING: C P1-29 cleanup failed: {exc}")

                if original_p1_30 is not None:
                    try:
                        print(f"Cleanup: restoring C P1-30 to {original_p1_30}...")
                        bus.write_u16(C_ID, P1_30, original_p1_30)
                    except Exception as exc:
                        print(f"WARNING: C P1-30 restore failed: {exc}")
            finally:
                bus.disconnect()


if __name__ == "__main__":
    main()
