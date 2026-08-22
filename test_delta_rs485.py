import serial
import struct
import time
from dataclasses import dataclass


# ============================================================
# Communication
# ============================================================

PORT = "COM4"
BAUD_RATE = 38400

GAMMA_ID = 1
C_ID = 2


# ============================================================
# ASDA-A2 addresses
# ============================================================

P0_01 = 0x0002   # Alarm
P0_09 = 0x0012   # Feedback position
P0_17 = 0x0022   # Feedback monitor selection
P0_46 = 0x005C   # Drive status

P1_01 = 0x0102   # Control mode
P2_30 = 0x023C

P5_07 = 0x050E   # Execute PR#1
P5_60 = 0x0578   # Speed slot 0

P6_02 = 0x0604   # PR#1 control
P6_03 = 0x0606   # Relative position


# ============================================================
# Motion settings
# ============================================================

PR_CONTROL_WORD = 0x00000042
SPEED_RAW = 50                 # 5 rpm

SON_BIT = 0x0002

ABSOLUTE_LIMIT_DEG = 5.0
MAX_MOVE_PER_COMMAND_DEG = 1.0

MOVE_TIMEOUT_SECONDS = 7.0
SAMPLE_INTERVAL_SECONDS = 0.05


@dataclass(frozen=True)
class Axis:
    slave_id: int
    name: str
    puu_per_degree: float
    sign: int
    tolerance_puu: int


GAMMA = Axis(
    slave_id=GAMMA_ID,
    name="Gamma",
    puu_per_degree=100000.0 * 15.0 / 360.0,
    sign=-1,
    tolerance_puu=25,
)

C_AXIS = Axis(
    slave_id=C_ID,
    name="C",
    puu_per_degree=100000.0 * 20.0 / 360.0,
    sign=+1,
    tolerance_puu=30,
)

AXES = {
    "G": GAMMA,
    "C": C_AXIS,
}


# ============================================================
# CRC
# ============================================================

def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF

    for byte in data:
        crc ^= byte

        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc & 0xFFFF


def add_crc(body: bytes) -> bytes:
    return body + struct.pack(
        "<H",
        crc16_modbus(body),
    )


def validate_crc(response: bytes) -> None:
    if len(response) < 5:
        raise RuntimeError(
            f"Response too short: {len(response)} bytes"
        )

    received_crc = int.from_bytes(
        response[-2:],
        byteorder="little",
    )

    calculated_crc = crc16_modbus(
        response[:-2]
    )

    if received_crc != calculated_crc:
        raise RuntimeError(
            f"CRC mismatch: received=0x{received_crc:04X}, "
            f"calculated=0x{calculated_crc:04X}"
        )


# ============================================================
# Modbus reads
# ============================================================

def read_registers(
    ser: serial.Serial,
    slave_id: int,
    address: int,
    count: int,
) -> list[int]:

    request = add_crc(
        struct.pack(
            ">BBHH",
            slave_id,
            0x03,
            address,
            count,
        )
    )

    ser.reset_input_buffer()
    ser.write(request)
    ser.flush()

    time.sleep(0.05)

    expected_length = 5 + count * 2
    response = ser.read(expected_length)

    if not response:
        raise RuntimeError(
            f"S{slave_id}: no response reading 0x{address:04X}"
        )

    validate_crc(response)

    if response[0] != slave_id:
        raise RuntimeError(
            f"Unexpected slave ID: {response[0]}"
        )

    if response[1] == 0x83:
        raise RuntimeError(
            f"S{slave_id}: Modbus exception "
            f"0x{response[2]:02X}"
        )

    if response[1] != 0x03:
        raise RuntimeError(
            f"Unexpected function: 0x{response[1]:02X}"
        )

    if response[2] != count * 2:
        raise RuntimeError(
            f"Unexpected byte count: {response[2]}"
        )

    return [
        int.from_bytes(
            response[3 + 2 * i:5 + 2 * i],
            byteorder="big",
            signed=False,
        )
        for i in range(count)
    ]


def read_u16(
    ser: serial.Serial,
    slave_id: int,
    address: int,
) -> int:

    return read_registers(
        ser,
        slave_id,
        address,
        1,
    )[0]


def read_u32(
    ser: serial.Serial,
    slave_id: int,
    address: int,
) -> int:

    low_word, high_word = read_registers(
        ser,
        slave_id,
        address,
        2,
    )

    return (
        ((high_word & 0xFFFF) << 16)
        | (low_word & 0xFFFF)
    )


def read_s32(
    ser: serial.Serial,
    slave_id: int,
    address: int,
) -> int:

    raw = read_u32(
        ser,
        slave_id,
        address,
    )

    if raw & 0x80000000:
        raw -= 0x100000000

    return raw


# ============================================================
# Modbus writes
# ============================================================

def write_s32(
    ser: serial.Serial,
    axis: Axis,
    address: int,
    value: int,
) -> None:

    if address != P6_03:
        raise RuntimeError(
            "Safety block: only P6-03 may be written."
        )

    maximum_puu = round(
        MAX_MOVE_PER_COMMAND_DEG
        * axis.puu_per_degree
    )

    if abs(value) > maximum_puu + 2:
        raise RuntimeError(
            f"Safety block: {axis.name} command "
            f"{value:+d} PUU exceeds "
            f"{MAX_MOVE_PER_COMMAND_DEG:.1f}°."
        )

    raw = value & 0xFFFFFFFF
    low_word = raw & 0xFFFF
    high_word = (raw >> 16) & 0xFFFF

    request = add_crc(
        struct.pack(
            ">BBHHBHH",
            axis.slave_id,
            0x10,
            address,
            2,
            4,
            low_word,
            high_word,
        )
    )

    ser.reset_input_buffer()
    ser.write(request)
    ser.flush()

    time.sleep(0.12)

    response = ser.read(8)

    if not response:
        raise RuntimeError(
            f"{axis.name}: no response writing P6-03."
        )

    validate_crc(response)

    if response[0] != axis.slave_id:
        raise RuntimeError(
            "Unexpected slave ID in write response."
        )

    if response[1] == 0x90:
        raise RuntimeError(
            f"{axis.name}: Modbus write exception "
            f"0x{response[2]:02X}"
        )

    if response[1] != 0x10:
        raise RuntimeError(
            f"Unexpected write function 0x{response[1]:02X}"
        )

    echoed_address = int.from_bytes(
        response[2:4],
        byteorder="big",
    )

    echoed_count = int.from_bytes(
        response[4:6],
        byteorder="big",
    )

    if echoed_address != address or echoed_count != 2:
        raise RuntimeError(
            f"{axis.name}: write verification failed."
        )


def trigger_pr1(
    ser: serial.Serial,
    axis: Axis,
) -> None:

    request = add_crc(
        struct.pack(
            ">BBHH",
            axis.slave_id,
            0x06,
            P5_07,
            1,
        )
    )

    ser.reset_input_buffer()
    ser.write(request)
    ser.flush()

    time.sleep(0.10)

    response = ser.read(8)

    if not response:
        raise RuntimeError(
            f"{axis.name}: no response to PR trigger."
        )

    validate_crc(response)

    if response != request:
        raise RuntimeError(
            f"{axis.name}: PR trigger echo mismatch."
        )


# ============================================================
# Conversions
# ============================================================

def degree_to_puu(
    axis: Axis,
    angle_degree: float,
) -> int:

    return round(
        angle_degree
        * axis.puu_per_degree
        * axis.sign
    )


def puu_to_degree(
    axis: Axis,
    puu: int,
) -> float:

    return (
        puu
        / axis.puu_per_degree
        / axis.sign
    )


# ============================================================
# Validation
# ============================================================

def verify_axis_configuration(
    ser: serial.Serial,
    axis: Axis,
) -> None:

    alarm = read_u16(
        ser,
        axis.slave_id,
        P0_01,
    )

    mode = read_u16(
        ser,
        axis.slave_id,
        P1_01,
    )

    simulation = read_u16(
        ser,
        axis.slave_id,
        P2_30,
    )

    monitor = read_u16(
        ser,
        axis.slave_id,
        P0_17,
    )

    speed = read_u16(
        ser,
        axis.slave_id,
        P5_60,
    )

    control = read_u32(
        ser,
        axis.slave_id,
        P6_02,
    )

    if alarm != 0:
        raise RuntimeError(
            f"{axis.name}: alarm 0x{alarm:04X} active."
        )

    if mode != 1:
        raise RuntimeError(
            f"{axis.name}: not in PR Mode."
        )

    if simulation != 0:
        raise RuntimeError(
            f"{axis.name}: unexpected P2-30={simulation}."
        )

    if monitor != 0:
        raise RuntimeError(
            f"{axis.name}: P0-09 feedback monitor not selected."
        )

    if speed != SPEED_RAW:
        raise RuntimeError(
            f"{axis.name}: speed is "
            f"{speed / 10:.1f} rpm, expected 5 rpm."
        )

    if control != PR_CONTROL_WORD:
        raise RuntimeError(
            f"{axis.name}: P6-02=0x{control:08X}, "
            f"expected 0x{PR_CONTROL_WORD:08X}."
        )


def verify_servo_selection(
    ser: serial.Serial,
    selected_axis: Axis,
) -> None:

    gamma_status = read_u16(
        ser,
        GAMMA_ID,
        P0_46,
    )

    c_status = read_u16(
        ser,
        C_ID,
        P0_46,
    )

    gamma_son = bool(
        gamma_status & SON_BIT
    )

    c_son = bool(
        c_status & SON_BIT
    )

    if selected_axis.slave_id == GAMMA_ID:
        if not gamma_son:
            raise RuntimeError(
                "Gamma Servo ON is not active."
            )

        if c_son:
            raise RuntimeError(
                "C Servo must remain OFF."
            )

    else:
        if not c_son:
            raise RuntimeError(
                "C Servo ON is not active."
            )

        if gamma_son:
            raise RuntimeError(
                "Gamma Servo must remain OFF."
            )


# ============================================================
# Absolute positioning
# ============================================================

def move_absolute(
    ser: serial.Serial,
    axis: Axis,
    target_degree: float,
    zero_puu: int,
) -> None:

    if abs(target_degree) > ABSOLUTE_LIMIT_DEG:
        raise RuntimeError(
            f"Target {target_degree:+.4f}° exceeds "
            f"absolute limit ±{ABSOLUTE_LIMIT_DEG:.1f}°."
        )

    verify_axis_configuration(
        ser,
        axis,
    )

    verify_servo_selection(
        ser,
        axis,
    )

    feedback_before = read_s32(
        ser,
        axis.slave_id,
        P0_09,
    )

    current_degree = puu_to_degree(
        axis,
        feedback_before - zero_puu,
    )

    required_move_degree = (
        target_degree - current_degree
    )

    if abs(required_move_degree) < 0.0001:
        print(
            f"{axis.name} is already at "
            f"{target_degree:+.4f}°."
        )
        return

    if (
        abs(required_move_degree)
        > MAX_MOVE_PER_COMMAND_DEG
    ):
        raise RuntimeError(
            f"Required movement is "
            f"{required_move_degree:+.4f}°.\n"
            f"Maximum per command is "
            f"±{MAX_MOVE_PER_COMMAND_DEG:.1f}°.\n"
            "Move through intermediate targets."
        )

    delta_puu = degree_to_puu(
        axis,
        required_move_degree,
    )

    expected_feedback = (
        feedback_before + delta_puu
    )

    print("\nAbsolute motion preview:")
    print(f"  Axis             : {axis.name}")
    print(
        f"  Current angle    : "
        f"{current_degree:+.4f}°"
    )
    print(
        f"  Absolute target  : "
        f"{target_degree:+.4f}°"
    )
    print(
        f"  Required movement: "
        f"{required_move_degree:+.4f}°"
    )
    print(
        f"  PR command       : "
        f"{delta_puu:+d} PUU"
    )
    print(
        f"  Feedback before  : "
        f"{feedback_before:+d} PUU"
    )
    print(
        f"  Expected feedback: "
        f"{expected_feedback:+d} PUU"
    )

    confirmation = input(
        "\nKeep the E-stop accessible.\n"
        "Type MOVE exactly to execute: "
    ).strip()

    if confirmation != "MOVE":
        print("Movement cancelled.")
        return

    verify_servo_selection(
        ser,
        axis,
    )

    if read_u16(
        ser,
        axis.slave_id,
        P0_01,
    ) != 0:
        raise RuntimeError(
            f"{axis.name}: alarm appeared before motion."
        )

    write_s32(
        ser,
        axis,
        P6_03,
        delta_puu,
    )

    readback = read_s32(
        ser,
        axis.slave_id,
        P6_03,
    )

    if readback != delta_puu:
        raise RuntimeError(
            f"{axis.name}: P6-03 readback "
            f"{readback:+d}, expected {delta_puu:+d}."
        )

    trigger_pr1(
        ser,
        axis,
    )

    start_time = time.monotonic()
    final_feedback = feedback_before

    while True:
        time.sleep(
            SAMPLE_INTERVAL_SECONDS
        )

        alarm = read_u16(
            ser,
            axis.slave_id,
            P0_01,
        )

        status = read_u16(
            ser,
            axis.slave_id,
            P0_46,
        )

        final_feedback = read_s32(
            ser,
            axis.slave_id,
            P0_09,
        )

        error_puu = (
            final_feedback - expected_feedback
        )

        print(
            f"  FB={final_feedback:+d}, "
            f"Error={error_puu:+d} PUU, "
            f"Alarm=0x{alarm:04X}"
        )

        if alarm != 0:
            raise RuntimeError(
                f"{axis.name}: alarm 0x{alarm:04X} "
                "during movement."
            )

        if not bool(status & SON_BIT):
            raise RuntimeError(
                f"{axis.name}: Servo ON lost."
            )

        if abs(error_puu) <= axis.tolerance_puu:
            break

        if (
            time.monotonic() - start_time
            > MOVE_TIMEOUT_SECONDS
        ):
            raise RuntimeError(
                f"{axis.name}: movement timeout."
            )

    final_degree = puu_to_degree(
        axis,
        final_feedback - zero_puu,
    )

    print("\nAbsolute movement result:")
    print(
        f"  Requested target: "
        f"{target_degree:+.4f}°"
    )
    print(
        f"  Final angle     : "
        f"{final_degree:+.4f}°"
    )
    print(
        f"  Final feedback  : "
        f"{final_feedback:+d} PUU"
    )


# ============================================================
# Main
# ============================================================

def main() -> None:
    print("=" * 72)
    print("LUMIGON — SAFE ABSOLUTE ANGLE CONTROL")
    print("=" * 72)

    print(
        f"Absolute limit      : "
        f"±{ABSOLUTE_LIMIT_DEG:.1f}°"
    )

    print(
        f"Maximum move/command: "
        f"±{MAX_MOVE_PER_COMMAND_DEG:.1f}°"
    )

    print("Current mechanical position must be 0°, 0°.")
    print("Both Servo ON switches must initially be OFF.")

    try:
        with serial.Serial(
            port=PORT,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=1.0,
            write_timeout=1.0,
        ) as ser:

            verify_axis_configuration(
                ser,
                GAMMA,
            )

            verify_axis_configuration(
                ser,
                C_AXIS,
            )

            gamma_status = read_u16(
                ser,
                GAMMA_ID,
                P0_46,
            )

            c_status = read_u16(
                ser,
                C_ID,
                P0_46,
            )

            if gamma_status & SON_BIT:
                raise RuntimeError(
                    "Gamma Servo must be OFF while capturing zero."
                )

            if c_status & SON_BIT:
                raise RuntimeError(
                    "C Servo must be OFF while capturing zero."
                )

            print(
                "\nPlace both axes at the mechanical 0°, 0° position."
            )

            confirmation = input(
                "Type SET_ZERO exactly to capture this position: "
            ).strip()

            if confirmation != "SET_ZERO":
                print("Zero capture cancelled.")
                return

            gamma_zero = read_s32(
                ser,
                GAMMA_ID,
                P0_09,
            )

            c_zero = read_s32(
                ser,
                C_ID,
                P0_09,
            )

            zero_reference = {
                GAMMA_ID: gamma_zero,
                C_ID: c_zero,
            }

            print("\nAbsolute zero reference captured:")
            print(
                f"  Gamma zero: {gamma_zero:+d} PUU"
            )
            print(
                f"  C zero    : {c_zero:+d} PUU"
            )

            print(
                "\nThis zero remains valid only until the drives "
                "are powered off or the axes are moved manually."
            )

            while True:
                print("\n" + "-" * 72)
                print("G = move Gamma to absolute angle")
                print("C = move C to absolute angle")
                print("S = show absolute positions")
                print("Z = redefine zero with both Servo OFF")
                print("Q = quit")

                choice = input(
                    "\nSelect command: "
                ).strip().upper()

                if choice == "Q":
                    print("Controller closed.")
                    break

                if choice == "S":
                    gamma_feedback = read_s32(
                        ser,
                        GAMMA_ID,
                        P0_09,
                    )

                    c_feedback = read_s32(
                        ser,
                        C_ID,
                        P0_09,
                    )

                    gamma_angle = puu_to_degree(
                        GAMMA,
                        gamma_feedback - gamma_zero,
                    )

                    c_angle = puu_to_degree(
                        C_AXIS,
                        c_feedback - c_zero,
                    )

                    print(
                        f"Gamma absolute: "
                        f"{gamma_angle:+.4f}°, "
                        f"FB={gamma_feedback:+d}"
                    )

                    print(
                        f"C absolute    : "
                        f"{c_angle:+.4f}°, "
                        f"FB={c_feedback:+d}"
                    )

                    continue

                if choice == "Z":
                    gamma_status = read_u16(
                        ser,
                        GAMMA_ID,
                        P0_46,
                    )

                    c_status = read_u16(
                        ser,
                        C_ID,
                        P0_46,
                    )

                    if (
                        gamma_status & SON_BIT
                        or c_status & SON_BIT
                    ):
                        print(
                            "Zero redefine blocked: "
                            "both Servo switches must be OFF."
                        )
                        continue

                    zero_confirmation = input(
                        "Type SET_ZERO to redefine current "
                        "position as 0°, 0°: "
                    ).strip()

                    if zero_confirmation != "SET_ZERO":
                        print("Zero redefine cancelled.")
                        continue

                    gamma_zero = read_s32(
                        ser,
                        GAMMA_ID,
                        P0_09,
                    )

                    c_zero = read_s32(
                        ser,
                        C_ID,
                        P0_09,
                    )

                    zero_reference[GAMMA_ID] = gamma_zero
                    zero_reference[C_ID] = c_zero

                    print(
                        f"New Gamma zero: {gamma_zero:+d} PUU"
                    )
                    print(
                        f"New C zero    : {c_zero:+d} PUU"
                    )

                    continue

                if choice not in AXES:
                    print("Invalid command.")
                    continue

                axis = AXES[choice]

                try:
                    target_text = input(
                        f"Enter absolute {axis.name} target "
                        f"(-{ABSOLUTE_LIMIT_DEG:.1f} to "
                        f"+{ABSOLUTE_LIMIT_DEG:.1f} degrees): "
                    ).strip()

                    target_degree = float(
                        target_text
                    )

                    move_absolute(
                        ser,
                        axis,
                        target_degree,
                        zero_reference[
                            axis.slave_id
                        ],
                    )

                except ValueError:
                    print("Invalid numeric angle.")

                except RuntimeError as error:
                    print(
                        f"\nMOVEMENT BLOCKED: {error}"
                    )

    except (
        serial.SerialException,
        RuntimeError,
    ) as error:

        print(f"\nCONTROLLER ABORTED: {error}")

    except KeyboardInterrupt:
        print(
            "\nController stopped. "
            "Use the physical E-stop when necessary."
        )


if __name__ == "__main__":
    main()