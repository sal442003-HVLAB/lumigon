import time
from dataclasses import dataclass

from delta_modbus import DeltaModbus

from machine_config import (
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
    GAMMA_SPEED_DEFAULT_RPM,
    C_SPEED_DEFAULT_RPM,
    GAMMA_SCURVE_DEFAULT_MS,
    C_SCURVE_DEFAULT_MS,
    JOG_STEP_DEG,
    ABSOLUTE_LIMIT_DEG,
    MAX_RELATIVE_MOVE_DEG,
    MOVE_TIMEOUT_SECONDS,
    MOTION_POLL_INTERVAL_SECONDS,
    GAMMA_PUU_PER_DEGREE,
    C_PUU_PER_DEGREE,
    GAMMA_SIGN,
    C_SIGN,
    GAMMA_TOLERANCE_PUU,
    C_TOLERANCE_PUU,
)


@dataclass(frozen=True)
class Axis:
    name: str
    slave_id: int
    puu_per_degree: float
    sign: int
    tolerance_puu: int


GAMMA = Axis(
    name="Gamma",
    slave_id=GAMMA_ID,
    puu_per_degree=GAMMA_PUU_PER_DEGREE,
    sign=GAMMA_SIGN,
    tolerance_puu=GAMMA_TOLERANCE_PUU,
)

C_AXIS = Axis(
    name="C",
    slave_id=C_ID,
    puu_per_degree=C_PUU_PER_DEGREE,
    sign=C_SIGN,
    tolerance_puu=C_TOLERANCE_PUU,
)


class MotionController:

    def __init__(self, modbus: DeltaModbus):
        self.modbus = modbus
        self.gamma_zero_puu = None
        self.c_zero_puu = None

        self.gamma_expected_speed_raw = round(GAMMA_SPEED_DEFAULT_RPM * 10.0)
        self.c_expected_speed_raw = round(C_SPEED_DEFAULT_RPM * 10.0)
        self.gamma_expected_scurve_ms = GAMMA_SCURVE_DEFAULT_MS
        self.c_expected_scurve_ms = C_SCURVE_DEFAULT_MS

    def set_session_zero(self, gamma_zero_puu: int, c_zero_puu: int):
        self.gamma_zero_puu = gamma_zero_puu
        self.c_zero_puu = c_zero_puu

    def set_expected_profile(self, axis: Axis, speed_raw: int, scurve_ms: int):
        if axis.slave_id == GAMMA_ID:
            self.gamma_expected_speed_raw = speed_raw
            self.gamma_expected_scurve_ms = scurve_ms
        else:
            self.c_expected_speed_raw = speed_raw
            self.c_expected_scurve_ms = scurve_ms

    @staticmethod
    def degree_to_puu(axis: Axis, degree: float) -> int:
        return round(degree * axis.puu_per_degree * axis.sign)

    @staticmethod
    def puu_to_degree(axis: Axis, puu: int) -> float:
        return puu / axis.puu_per_degree / axis.sign

    def get_zero(self, axis: Axis) -> int:
        zero = (
            self.gamma_zero_puu
            if axis.slave_id == GAMMA_ID
            else self.c_zero_puu
        )

        if zero is None:
            raise RuntimeError("Session zero has not been captured.")

        return zero

    def get_current_angle(self, axis: Axis) -> float:
        feedback = self.modbus.read_s32(axis.slave_id, P0_09)
        return self.puu_to_degree(axis, feedback - self.get_zero(axis))

    def expected_scurve(self, axis: Axis) -> int:
        if axis.slave_id == GAMMA_ID:
            return self.gamma_expected_scurve_ms
        return self.c_expected_scurve_ms

    def expected_speed_raw(self, axis: Axis) -> int:
        if axis.slave_id == GAMMA_ID:
            return self.gamma_expected_speed_raw
        return self.c_expected_speed_raw

    def verify_axis(self, axis: Axis):
        alarm = self.modbus.read_u16(axis.slave_id, P0_01)
        if alarm != 0:
            raise RuntimeError(
                f"{axis.name}: alarm 0x{alarm:04X} active."
            )

        mode = self.modbus.read_u16(axis.slave_id, P1_01)
        if mode != 1:
            raise RuntimeError(f"{axis.name}: not in PR Mode.")

        simulation = self.modbus.read_u16(axis.slave_id, P2_30)
        if simulation != 0:
            raise RuntimeError(
                f"{axis.name}: P2-30={simulation}, expected 0."
            )

        monitor = self.modbus.read_u16(axis.slave_id, P0_17)
        if monitor != 0:
            raise RuntimeError(
                f"{axis.name}: P0-09 is not feedback position."
            )

        speed = self.modbus.read_u16(axis.slave_id, P5_60)
        expected_speed = self.expected_speed_raw(axis)
        if speed != expected_speed:
            raise RuntimeError(
                f"{axis.name}: PR speed is {speed / 10:.1f} rpm, "
                f"expected {expected_speed / 10:.1f} rpm."
            )

        scurve = self.modbus.read_u16(axis.slave_id, P1_36)
        expected_scurve = self.expected_scurve(axis)
        if scurve != expected_scurve:
            raise RuntimeError(
                f"{axis.name}: P1-36 S-curve is {scurve} ms, "
                f"expected {expected_scurve} ms. Motion blocked."
            )

        control = self.modbus.read_u32(axis.slave_id, P6_02)
        if control != PR_CONTROL_WORD:
            raise RuntimeError(
                f"{axis.name}: P6-02=0x{control:08X}, "
                f"expected 0x{PR_CONTROL_WORD:08X}."
            )

    def verify_servo_selection(self, axis: Axis):
        gamma_status = self.modbus.read_u16(GAMMA_ID, P0_46)
        c_status = self.modbus.read_u16(C_ID, P0_46)

        gamma_son = bool(gamma_status & SON_BIT)
        c_son = bool(c_status & SON_BIT)

        if axis.slave_id == GAMMA_ID:
            if not gamma_son:
                raise RuntimeError("Gamma Servo is OFF.")
            if c_son:
                raise RuntimeError(
                    "C Servo must remain OFF during commissioning."
                )
        else:
            if not c_son:
                raise RuntimeError("C Servo is OFF.")
            if gamma_son:
                raise RuntimeError(
                    "Gamma Servo must remain OFF during commissioning."
                )

    def wait_for_target(self, axis: Axis, expected_feedback: int):
        deadline = time.monotonic() + MOVE_TIMEOUT_SECONDS
        last_feedback = None

        while time.monotonic() < deadline:
            alarm = self.modbus.read_u16(axis.slave_id, P0_01)

            if alarm != 0:
                raise RuntimeError(
                    f"{axis.name}: alarm 0x{alarm:04X} during motion."
                )

            last_feedback = self.modbus.read_s32(axis.slave_id, P0_09)

            if abs(last_feedback - expected_feedback) <= axis.tolerance_puu:
                return

            time.sleep(MOTION_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"{axis.name}: motion timeout. "
            f"Expected {expected_feedback:+d} PUU, "
            f"last feedback {last_feedback:+d} PUU."
        )

    def execute_relative(self, axis: Axis, delta_degree: float):
        if abs(delta_degree) > MAX_RELATIVE_MOVE_DEG + 1e-9:
            raise RuntimeError(
                f"{axis.name}: relative move {delta_degree:+.4f}° exceeds "
                f"the maximum legal span of {MAX_RELATIVE_MOVE_DEG:.1f}°."
            )

        self.verify_axis(axis)
        self.verify_servo_selection(axis)

        current_angle = self.get_current_angle(axis)
        target_angle = current_angle + delta_degree

        if abs(target_angle) > ABSOLUTE_LIMIT_DEG + 1e-9:
            raise RuntimeError(
                f"{axis.name}: resulting target {target_angle:+.4f}° exceeds "
                f"the ±{ABSOLUTE_LIMIT_DEG:.1f}° commissioning limit."
            )

        feedback_before = self.modbus.read_s32(axis.slave_id, P0_09)
        delta_puu = self.degree_to_puu(axis, delta_degree)
        expected_feedback = feedback_before + delta_puu

        self.modbus.write_s32(axis.slave_id, P6_03, delta_puu)

        readback = self.modbus.read_s32(axis.slave_id, P6_03)
        if readback != delta_puu:
            raise RuntimeError(
                f"{axis.name}: P6-03 verification failed."
            )

        alarm = self.modbus.read_u16(axis.slave_id, P0_01)
        if alarm != 0:
            raise RuntimeError(
                f"{axis.name}: alarm appeared before PR trigger."
            )

        self.modbus.write_u16(axis.slave_id, P5_07, 1)
        self.wait_for_target(axis, expected_feedback)

    def jog(self, axis: Axis, delta_degree: float):
        if abs(abs(delta_degree) - JOG_STEP_DEG) > 1e-9:
            raise RuntimeError("Jog only permits ±0.1°.")

        current = self.get_current_angle(axis)
        target = current + delta_degree

        if abs(target) > ABSOLUTE_LIMIT_DEG:
            raise RuntimeError(
                f"{axis.name}: target {target:+.4f}° exceeds "
                f"±{ABSOLUTE_LIMIT_DEG:.1f}°."
            )

        self.execute_relative(axis, delta_degree)

    def move_absolute(self, axis: Axis, target_degree: float):
        if abs(target_degree) > ABSOLUTE_LIMIT_DEG:
            raise RuntimeError(
                f"{axis.name}: target {target_degree:+.4f}° exceeds "
                f"±{ABSOLUTE_LIMIT_DEG:.1f}°."
            )

        self.verify_axis(axis)
        self.verify_servo_selection(axis)

        current = self.get_current_angle(axis)
        remaining = target_degree - current

        if abs(remaining) <= 0.01:
            return

        # One continuous PR command. There are no intermediate 1° stops.
        # Safety is enforced by the absolute ±15° target limit above and
        # again inside execute_relative().
        self.execute_relative(axis, remaining)

    def return_to_zero(self, axis: Axis):
        self.move_absolute(axis, 0.0)
