from dataclasses import dataclass

from delta_modbus import (
    DeltaModbus,
    DeltaModbusError,
)

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
    P5_20,
    P5_60,
    P6_02,
    P6_03,
    SON_BIT,
    PR_CONTROL_WORD,
    GAMMA_PR_SPEED_RAW,
    C_PR_SPEED_RAW,
    C_ACCEL_DECEL_MS,
    C_S_CURVE_MS,
    C_PROFILE_MIN_MS,
    C_PROFILE_MAX_MS,
    C_PROFILE_STEP_MS,
    JOG_STEP_DEG,
    ABSOLUTE_LIMIT_DEG,
    GAMMA_PUU_PER_DEGREE,
    C_PUU_PER_DEGREE,
    GAMMA_SIGN,
    C_SIGN,
)


@dataclass(frozen=True)
class Axis:
    name: str
    slave_id: int
    puu_per_degree: float
    sign: int


GAMMA = Axis(
    name="Gamma",
    slave_id=GAMMA_ID,
    puu_per_degree=GAMMA_PUU_PER_DEGREE,
    sign=GAMMA_SIGN,
)

C_AXIS = Axis(
    name="C",
    slave_id=C_ID,
    puu_per_degree=C_PUU_PER_DEGREE,
    sign=C_SIGN,
)


class MotionController:

    def __init__(
        self,
        modbus: DeltaModbus,
    ):
        self.modbus = modbus

        self.gamma_zero_puu = None
        self.c_zero_puu = None

        self.c_accel_decel_ms = C_ACCEL_DECEL_MS
        self.c_s_curve_ms = C_S_CURVE_MS

    # ========================================================
    # Zero
    # ========================================================

    def set_session_zero(
        self,
        gamma_zero_puu: int,
        c_zero_puu: int,
    ) -> None:

        self.gamma_zero_puu = gamma_zero_puu
        self.c_zero_puu = c_zero_puu

    # ========================================================
    # C-axis motion profile
    # ========================================================

    @staticmethod
    def _validate_profile_ms(
        name: str,
        value: int,
    ) -> int:
        value = int(value)

        if not C_PROFILE_MIN_MS <= value <= C_PROFILE_MAX_MS:
            raise ValueError(
                f"{name} must be between "
                f"{C_PROFILE_MIN_MS} and {C_PROFILE_MAX_MS} ms."
            )

        if value % C_PROFILE_STEP_MS != 0:
            raise ValueError(
                f"{name} must use {C_PROFILE_STEP_MS} ms increments."
            )

        return value

    def set_c_motion_profile(
        self,
        accel_decel_ms: int,
        s_curve_ms: int,
    ) -> None:
        self.c_accel_decel_ms = self._validate_profile_ms(
            "C Ramp",
            accel_decel_ms,
        )
        self.c_s_curve_ms = self._validate_profile_ms(
            "C S-curve",
            s_curve_ms,
        )

    # ========================================================
    # Conversion
    # ========================================================

    @staticmethod
    def degree_to_puu(
        axis: Axis,
        degree: float,
    ) -> int:

        return round(
            degree
            * axis.puu_per_degree
            * axis.sign
        )

    def get_zero(
        self,
        axis: Axis,
    ) -> int:

        if axis.slave_id == GAMMA_ID:
            zero = self.gamma_zero_puu
        else:
            zero = self.c_zero_puu

        if zero is None:
            raise RuntimeError(
                "Session zero has not been captured."
            )

        return zero

    # ========================================================
    # Safety checks
    # ========================================================

    def verify_axis(
        self,
        axis: Axis,
    ) -> None:

        alarm = self.modbus.read_u16(
            axis.slave_id,
            P0_01,
        )

        if alarm != 0:
            raise RuntimeError(
                f"{axis.name}: alarm "
                f"0x{alarm:04X} active."
            )

        mode = self.modbus.read_u16(
            axis.slave_id,
            P1_01,
        )

        if mode != 1:
            raise RuntimeError(
                f"{axis.name}: not in PR Mode."
            )

        simulation = self.modbus.read_u16(
            axis.slave_id,
            P2_30,
        )

        if simulation != 0:
            raise RuntimeError(
                f"{axis.name}: P2-30="
                f"{simulation}, expected 0."
            )

        monitor = self.modbus.read_u16(
            axis.slave_id,
            P0_17,
        )

        if monitor != 0:
            raise RuntimeError(
                f"{axis.name}: P0-09 is not "
                "feedback position."
            )

        expected_speed = (
            GAMMA_PR_SPEED_RAW
            if axis.slave_id == GAMMA_ID
            else C_PR_SPEED_RAW
        )

        speed = self.modbus.read_u16(
            axis.slave_id,
            P5_60,
        )

        if speed != expected_speed:
            raise RuntimeError(
                f"{axis.name}: PR speed is "
                f"{speed / 10:.1f} rpm, "
                f"expected {expected_speed / 10:.1f} rpm."
            )

        control = self.modbus.read_u32(
            axis.slave_id,
            P6_02,
        )

        if control != PR_CONTROL_WORD:
            raise RuntimeError(
                f"{axis.name}: P6-02="
                f"0x{control:08X}, "
                f"expected "
                f"0x{PR_CONTROL_WORD:08X}."
            )

    def verify_servo_selection(
        self,
        axis: Axis,
    ) -> None:

        gamma_status = self.modbus.read_u16(
            GAMMA_ID,
            P0_46,
        )

        c_status = self.modbus.read_u16(
            C_ID,
            P0_46,
        )

        gamma_son = bool(
            gamma_status & SON_BIT
        )

        c_son = bool(
            c_status & SON_BIT
        )

        if axis.slave_id == GAMMA_ID:

            if not gamma_son:
                raise RuntimeError(
                    "Gamma Servo is OFF."
                )

            if c_son:
                raise RuntimeError(
                    "C Servo must remain OFF "
                    "during this commissioning test."
                )

        else:

            if not c_son:
                raise RuntimeError(
                    "C Servo is OFF."
                )

            if gamma_son:
                raise RuntimeError(
                    "Gamma Servo must remain OFF "
                    "during this commissioning test."
                )

    def configure_motion_profile(
        self,
        axis: Axis,
    ) -> None:
        """Apply the selected C-axis commissioning profile before motion."""

        if axis.slave_id != C_ID:
            return

        current_speed = self.modbus.read_u16(
            axis.slave_id,
            P5_60,
        )

        if current_speed != C_PR_SPEED_RAW:
            self.modbus.write_u16(
                axis.slave_id,
                P5_60,
                C_PR_SPEED_RAW,
            )

            readback = self.modbus.read_u16(
                axis.slave_id,
                P5_60,
            )

            if readback != C_PR_SPEED_RAW:
                raise RuntimeError(
                    f"{axis.name}: P5-60 verification failed. "
                    f"Read {readback / 10:.1f} rpm, "
                    f"expected {C_PR_SPEED_RAW / 10:.1f} rpm."
                )

        current_accel_decel = self.modbus.read_u16(
            axis.slave_id,
            P5_20,
        )

        if current_accel_decel != self.c_accel_decel_ms:
            self.modbus.write_u16(
                axis.slave_id,
                P5_20,
                self.c_accel_decel_ms,
            )

            readback = self.modbus.read_u16(
                axis.slave_id,
                P5_20,
            )

            if readback != self.c_accel_decel_ms:
                raise RuntimeError(
                    f"{axis.name}: P5-20 verification failed. "
                    f"Read {readback} ms, "
                    f"expected {self.c_accel_decel_ms} ms."
                )

        current_s_curve = self.modbus.read_u16(
            axis.slave_id,
            P1_36,
        )

        if current_s_curve != self.c_s_curve_ms:
            self.modbus.write_u16(
                axis.slave_id,
                P1_36,
                self.c_s_curve_ms,
            )

            readback = self.modbus.read_u16(
                axis.slave_id,
                P1_36,
            )

            if readback != self.c_s_curve_ms:
                raise RuntimeError(
                    f"{axis.name}: P1-36 verification failed. "
                    f"Read {readback} ms, "
                    f"expected {self.c_s_curve_ms} ms."
                )

    # ========================================================
    # Jog
    # ========================================================

    def jog(
        self,
        axis: Axis,
        delta_degree: float,
    ) -> None:

        if abs(delta_degree) != JOG_STEP_DEG:
            raise RuntimeError(
                "HMI v0.2 only permits "
                "±0.1 degree jog commands."
            )

        self.configure_motion_profile(axis)
        self.verify_axis(axis)
        self.verify_servo_selection(axis)

        feedback = self.modbus.read_s32(
            axis.slave_id,
            P0_09,
        )

        zero = self.get_zero(axis)

        current_angle = (
            (feedback - zero)
            / axis.puu_per_degree
            / axis.sign
        )

        target_angle = (
            current_angle
            + delta_degree
        )

        if abs(target_angle) > ABSOLUTE_LIMIT_DEG:
            raise RuntimeError(
                f"{axis.name}: requested position "
                f"{target_angle:+.4f}° exceeds "
                f"±{ABSOLUTE_LIMIT_DEG:.1f}°."
            )

        delta_puu = self.degree_to_puu(
            axis,
            delta_degree,
        )

        # Write only the tested relative PR distance
        self.modbus.write_s32(
            axis.slave_id,
            P6_03,
            delta_puu,
        )

        # Verify written value
        readback = self.modbus.read_s32(
            axis.slave_id,
            P6_03,
        )

        if readback != delta_puu:
            raise RuntimeError(
                f"{axis.name}: P6-03 verification "
                f"failed. Read {readback:+d}, "
                f"expected {delta_puu:+d}."
            )

        # Trigger PR#1
        self.modbus.write_u16(
            axis.slave_id,
            P5_07,
            1,
        )