# ============================================================
# Lumigon - Machine Configuration
# HMI v0.1
# ============================================================

PORT = "COM4"
BAUD_RATE = 38400

SERIAL_TIMEOUT = 1.0

GAMMA_ID = 1
C_ID = 2


# ------------------------------------------------------------
# ASDA-A2 Modbus parameter addresses
# ------------------------------------------------------------

P0_01 = 0x0002       # Alarm code
P0_09 = 0x0012       # Feedback position
P0_17 = 0x0022       # Monitor selection
P0_46 = 0x005C       # Servo status

P1_01 = 0x0102       # Control mode
P1_36 = 0x0148       # Position-command S-curve smoothing time (ms)
P2_30 = 0x023C       # Simulation / related configuration

P5_07 = 0x050E       # Execute PR#1
P5_20 = 0x0528       # Accel/decel slot 0 (ms)
P5_60 = 0x0578       # Speed slot 0
P6_02 = 0x0604       # PR#1 control
P6_03 = 0x0606       # Relative PR position


# ------------------------------------------------------------
# Servo status bits
# Confirmed during commissioning
# ------------------------------------------------------------

SON_BIT = 0x0002

PR_CONTROL_WORD = 0x00000042
GAMMA_PR_SPEED_RAW = 50      # 5.0 rpm
C_PR_SPEED_RAW = 30          # 3.0 rpm commissioning test

# C-axis commissioning profile:
# P5-20 is a shared acceleration/deceleration time in PR mode.
# Keep the ramp that already gave a good start, use a mild
# position-command S-curve, and temporarily lower C speed to
# isolate whether the stop vibration is speed/inertia related.
C_ACCEL_DECEL_MS = 500
C_S_CURVE_MS = 100

JOG_STEP_DEG = 0.1
ABSOLUTE_LIMIT_DEG = 5.0


# ------------------------------------------------------------
# Mechanical / electronic scaling
# ------------------------------------------------------------

# Confirmed electronic gear:
# P1-44 = 128
# P1-45 = 10
#
# => 100,000 PUU / motor revolution

PUU_PER_MOTOR_REV = 100000.0

# Gearboxes:
# Gamma = 15:1
# C     = 20:1

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


# ------------------------------------------------------------
# Axis direction
# Confirmed physically
#
# Gamma positive angle -> negative PUU
# C positive angle     -> positive PUU
# ------------------------------------------------------------

GAMMA_SIGN = -1
C_SIGN = +1


# ------------------------------------------------------------
# GUI
# ------------------------------------------------------------

REFRESH_INTERVAL_MS = 1000

APP_NAME = "Lumigon"
APP_VERSION = "0.2.0"