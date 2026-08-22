# ============================================================
# Lumigon - Machine Configuration
# HMI v0.3.3
# ============================================================

PORT = "COM4"
BAUD_RATE = 38400
SERIAL_TIMEOUT = 1.0

GAMMA_ID = 1
C_ID = 2

P0_01 = 0x0002
P0_09 = 0x0012
P0_17 = 0x0022
P0_46 = 0x005C

P1_01 = 0x0102
P1_36 = 0x0148       # PR S-curve smoothing time (ms)
P2_30 = 0x023C

P5_07 = 0x050E
P5_60 = 0x0578

P6_02 = 0x0604
P6_03 = 0x0606

SON_BIT = 0x0002

PR_CONTROL_WORD = 0x00000042
PR_SPEED_RAW = 50

# Axis-specific S-curve tuning.
# Gamma is already behaving well at 200 ms.
# C is under commissioning at 300 ms to reduce post-stop excitation.
EXPECTED_GAMMA_SCURVE_MS = 200
EXPECTED_C_SCURVE_MS = 300

JOG_STEP_DEG = 0.1

# Commissioning software limit. Mechanical freedom is larger, but the HMI
# remains intentionally conservative until homing/limit wiring is complete.
ABSOLUTE_LIMIT_DEG = 15.0
MAX_MOVE_PER_COMMAND_DEG = 1.0

MOVE_TIMEOUT_SECONDS = 7.0
MOTION_POLL_INTERVAL_SECONDS = 0.05

PUU_PER_MOTOR_REV = 100000.0

GAMMA_GEAR_RATIO = 15.0
C_GEAR_RATIO = 20.0

GAMMA_PUU_PER_DEGREE = (
    PUU_PER_MOTOR_REV
    * GAMMA_GEAR_RATIO
    / 360.0
)

C_PUU_PER_DEGREE = (
    PUU_PER_MOTOR_REV
    * C_GEAR_RATIO
    / 360.0
)

GAMMA_SIGN = -1
C_SIGN = +1

GAMMA_TOLERANCE_PUU = 25
C_TOLERANCE_PUU = 30

REFRESH_INTERVAL_MS = 1000

APP_NAME = "Lumigon"
APP_VERSION = "0.3.3"
