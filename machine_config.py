# ============================================================
# Lumigon - Machine Configuration
# HMI v0.3.4
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
P5_20 = 0x0528       # PR accel/decel slot 0 (ms)
P5_60 = 0x0578       # PR speed slot 0 (0.1 rpm)

P6_02 = 0x0604
P6_03 = 0x0606

SON_BIT = 0x0002
PR_CONTROL_WORD = 0x00000042

# ------------------------------------------------------------
# Per-axis commissioning motion profiles
# ------------------------------------------------------------
# These are HMI defaults only. Opening Lumigon does not write them
# to either drive; the operator must press Apply for the selected axis.

PROFILE_MIN_MS = 100
PROFILE_MAX_MS = 3000
PROFILE_STEP_MS = 100

SPEED_MIN_RPM = 0.5
SPEED_MAX_RPM = 15.0
SPEED_STEP_RPM = 0.5

# Gamma baseline selected for normal commissioning use.
GAMMA_SPEED_DEFAULT_RPM = 5.0
GAMMA_RAMP_DEFAULT_MS = 300
GAMMA_SCURVE_DEFAULT_MS = 2000

# C baseline selected during commissioning on 2026-08-23.
C_SPEED_DEFAULT_RPM = 5.0
C_RAMP_DEFAULT_MS = 300
C_SCURVE_DEFAULT_MS = 2000

# Legacy aliases retained while older helper scripts still exist.
PR_SPEED_RAW = round(GAMMA_SPEED_DEFAULT_RPM * 10.0)
EXPECTED_GAMMA_SCURVE_MS = GAMMA_SCURVE_DEFAULT_MS
EXPECTED_C_SCURVE_MS = C_SCURVE_DEFAULT_MS
C_PROFILE_MIN_MS = PROFILE_MIN_MS
C_PROFILE_MAX_MS = PROFILE_MAX_MS
C_PROFILE_STEP_MS = PROFILE_STEP_MS
C_SPEED_MIN_RPM = SPEED_MIN_RPM
C_SPEED_MAX_RPM = SPEED_MAX_RPM
C_SPEED_STEP_RPM = SPEED_STEP_RPM

# Manual Motor Control jog increment.
JOG_STEP_DEG = 1.0

# ------------------------------------------------------------
# Confirmed software motion envelopes around Session Zero
# ------------------------------------------------------------
# Gamma axis: -60° ... +60°
# C axis:     -45° ... +45°
GAMMA_LIMIT_DEG = 60.0
C_LIMIT_DEG = 45.0

# Legacy compatibility value for older UI/helper code. MotionController does
# NOT use this shared value for safety checks; it enforces the per-axis limits
# above. New code should prefer GAMMA_LIMIT_DEG / C_LIMIT_DEG.
ABSOLUTE_LIMIT_DEG = max(GAMMA_LIMIT_DEG, C_LIMIT_DEG)
MAX_RELATIVE_MOVE_DEG = 2.0 * ABSOLUTE_LIMIT_DEG

MOVE_TIMEOUT_SECONDS = 30.0
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
APP_VERSION = "0.3.4"
