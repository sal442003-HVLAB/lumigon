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
PR_SPEED_RAW = 50            # Gamma/default = 5.0 rpm

# Axis-specific S-curve tuning.
EXPECTED_GAMMA_SCURVE_MS = 200
EXPECTED_C_SCURVE_MS = 400

# C-axis profile tuning controls shown in the commissioning HMI.
C_PROFILE_MIN_MS = 100
C_PROFILE_MAX_MS = 3000
C_PROFILE_STEP_MS = 100
C_RAMP_DEFAULT_MS = 2000
C_SCURVE_DEFAULT_MS = 100

# C-axis speed tuning control. P5-60 uses 0.1 rpm units.
C_SPEED_MIN_RPM = 0.5
C_SPEED_MAX_RPM = 15.0
C_SPEED_STEP_RPM = 0.5
C_SPEED_DEFAULT_RPM = 5.0

JOG_STEP_DEG = 0.1

# Commissioning software position limit around Session Zero.
# Any target must remain inside -15° ... +15° on either axis.
ABSOLUTE_LIMIT_DEG = 15.0

# A direct move from one legal extreme (-15°) to the other (+15°)
# can require a 30° relative PR command. The controller checks the
# resulting absolute target before issuing the command.
MAX_RELATIVE_MOVE_DEG = 2.0 * ABSOLUTE_LIMIT_DEG

# At 5 rpm motor speed and the installed gear ratios, a full legal
# -15° -> +15° move can take around 15-20 seconds. Keep margin here.
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
