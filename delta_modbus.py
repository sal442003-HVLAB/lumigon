import serial
import struct
import time

from machine_config import (
    BAUD_RATE,
    SERIAL_TIMEOUT,
)


class DeltaModbusError(RuntimeError):
    pass


class DeltaModbus:
    """
    Read-only Modbus RTU communication layer
    for Delta ASDA-A2 servo drives.

    HMI v0.1 intentionally contains NO write command.
    """

    def __init__(self, port: str):
        self.port = port
        self.ser: serial.Serial | None = None

    # ========================================================
    # Connection
    # ========================================================

    @property
    def is_connected(self) -> bool:
        return (
            self.ser is not None
            and self.ser.is_open
        )

    def connect(self) -> None:
        if self.is_connected:
            return

        self.ser = serial.Serial(
            port=self.port,
            baudrate=BAUD_RATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_TWO,
            timeout=SERIAL_TIMEOUT,
            write_timeout=SERIAL_TIMEOUT,
        )

        time.sleep(0.1)

        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def disconnect(self) -> None:
        if self.ser is not None:
            try:
                if self.ser.is_open:
                    self.ser.close()
            finally:
                self.ser = None

    # ========================================================
    # CRC
    # ========================================================

    @staticmethod
    def crc16_modbus(data: bytes) -> int:
        crc = 0xFFFF

        for byte in data:
            crc ^= byte

            for _ in range(8):
                if crc & 0x0001:
                    crc = (
                        (crc >> 1)
                        ^ 0xA001
                    )
                else:
                    crc >>= 1

        return crc & 0xFFFF

    @classmethod
    def add_crc(
        cls,
        body: bytes,
    ) -> bytes:

        crc = cls.crc16_modbus(body)

        return (
            body
            + struct.pack("<H", crc)
        )

    @classmethod
    def validate_crc(
        cls,
        response: bytes,
    ) -> None:

        if len(response) < 5:
            raise DeltaModbusError(
                f"Response too short: "
                f"{len(response)} bytes"
            )

        received_crc = int.from_bytes(
            response[-2:],
            byteorder="little",
        )

        calculated_crc = cls.crc16_modbus(
            response[:-2]
        )

        if received_crc != calculated_crc:
            raise DeltaModbusError(
                "CRC mismatch: "
                f"RX=0x{received_crc:04X}, "
                f"CALC=0x{calculated_crc:04X}"
            )

    # ========================================================
    # Read Holding Registers - FC03
    # ========================================================

    def read_registers(
        self,
        slave_id: int,
        address: int,
        count: int,
    ) -> list[int]:

        if not self.is_connected:
            raise DeltaModbusError(
                "Serial port is not connected."
            )

        body = struct.pack(
            ">BBHH",
            slave_id,
            0x03,
            address,
            count,
        )

        request = self.add_crc(body)

        self.ser.reset_input_buffer()

        self.ser.write(request)
        self.ser.flush()

        expected_length = (
            5
            + count * 2
        )

        response = self.ser.read(
            expected_length
        )

        if not response:
            raise DeltaModbusError(
                f"S{slave_id}: no response "
                f"reading 0x{address:04X}"
            )

        self.validate_crc(response)

        if response[0] != slave_id:
            raise DeltaModbusError(
                "Unexpected slave ID: "
                f"{response[0]}"
            )

        function = response[1]

        if function == 0x83:
            exception_code = response[2]

            raise DeltaModbusError(
                f"S{slave_id}: Modbus "
                f"exception 0x{exception_code:02X}"
            )

        if function != 0x03:
            raise DeltaModbusError(
                "Unexpected Modbus function: "
                f"0x{function:02X}"
            )

        byte_count = response[2]

        expected_byte_count = (
            count * 2
        )

        if byte_count != expected_byte_count:
            raise DeltaModbusError(
                "Unexpected byte count: "
                f"{byte_count}"
            )

        registers = []

        for i in range(count):
            start = 3 + i * 2
            end = start + 2

            value = int.from_bytes(
                response[start:end],
                byteorder="big",
                signed=False,
            )

            registers.append(value)

        return registers

    # ========================================================
    # Typed reads
    # ========================================================

    def read_u16(
        self,
        slave_id: int,
        address: int,
    ) -> int:

        return self.read_registers(
            slave_id,
            address,
            1,
        )[0]

    def read_u32(
        self,
        slave_id: int,
        address: int,
    ) -> int:

        low_word, high_word = (
            self.read_registers(
                slave_id,
                address,
                2,
            )
        )

        return (
            ((high_word & 0xFFFF) << 16)
            | (low_word & 0xFFFF)
        )

    def read_s32(
        self,
        slave_id: int,
        address: int,
    ) -> int:

        value = self.read_u32(
            slave_id,
            address,
        )

        if value & 0x80000000:
            value -= 0x100000000

        return value