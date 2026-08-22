# ============================================================
# Lumigon - Machine Configuration
# HMI v0.1
# ============================================================

PORT = "COM4"
BAUD_RATE = 38400

SERIAL_TIMEOUT = 0.5

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
P2_30 = 0x023C       # Simulation / related configuration


# ------------------------------------------------------------
# Servo status bits
# Confirmed during commissioning
# ------------------------------------------------------------

SON_BIT = 0x0002


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

REFRESH_INTERVAL_MS = 500

APP_NAME = "Lumigon"
APP_VERSION = "0.1.0"