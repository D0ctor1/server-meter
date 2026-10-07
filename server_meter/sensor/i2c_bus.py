"""Thin I²C wrapper around smbus2 with timeouts. No disk I/O.

On Python 3.13+/3.14 (especially aarch64) smbus2.SMBus.open() calls ioctl
I2C_FUNCS with a 4-byte buffer while the kernel writes an unsigned long
(8 bytes). That raises SystemError: buffer overflow. We open /dev/i2c-N
ourselves and skip that ioctl. i2c_rdwr still comes from smbus2.
"""

from __future__ import annotations

import os
import threading
from types import TracebackType

from server_meter.sensor.exceptions import SensorTimeoutError, SensorUnavailableError


def open_smbus(bus_id: int):
    """Return an smbus2.SMBus connected to /dev/i2c-{bus_id} without I2C_FUNCS."""
    try:
        from smbus2 import SMBus
    except ImportError as exc:
        raise SensorUnavailableError("smbus2 is required for the BME690 driver") from exc
    path = f"/dev/i2c-{int(bus_id)}"
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    handle = SMBus()
    try:
        handle.fd = os.open(path, os.O_RDWR)
    except OSError:
        raise
    # Pretend full capability; we only use I2C_RDWR.
    handle.funcs = 0xFFFFFFFF
    return handle


class I2CBus:
    def __init__(self, bus_id: int, address: int, timeout_seconds: float = 1.0) -> None:
        self.bus_id = bus_id
        self.address = address
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._bus = None

    def open(self) -> None:
        try:
            self._bus = open_smbus(self.bus_id)
        except FileNotFoundError as exc:
            raise SensorUnavailableError(
                f"I2C bus /dev/i2c-{self.bus_id} is not available. Enable I²C and check wiring."
            ) from exc
        except OSError as exc:
            raise SensorUnavailableError(f"Cannot open I2C bus {self.bus_id}: {exc}") from exc

    def close(self) -> None:
        if self._bus is not None:
            try:
                self._bus.close()
            except OSError:
                pass
            self._bus = None

    def read_bytes(self, register: int, length: int) -> bytes:
        from smbus2 import i2c_msg

        if self._bus is None:
            raise SensorUnavailableError("I2C bus is not open")
        write = i2c_msg.write(self.address, [register & 0xFF])
        read = i2c_msg.read(self.address, length)
        with self._lock:
            try:
                self._bus.i2c_rdwr(write, read)
            except TimeoutError as exc:
                raise SensorTimeoutError(f"I2C timeout on bus {self.bus_id} addr 0x{self.address:02x}") from exc
            except OSError as exc:
                raise SensorUnavailableError(
                    f"I2C read failed bus={self.bus_id} addr=0x{self.address:02x} reg=0x{register:02x}: {exc}"
                ) from exc
        return bytes(read)

    def write_bytes(self, register: int, data: bytes | list[int]) -> None:
        from smbus2 import i2c_msg

        if self._bus is None:
            raise SensorUnavailableError("I2C bus is not open")
        payload = [register & 0xFF, *[int(b) & 0xFF for b in data]]
        msg = i2c_msg.write(self.address, payload)
        with self._lock:
            try:
                self._bus.i2c_rdwr(msg)
            except TimeoutError as exc:
                raise SensorTimeoutError(f"I2C timeout on bus {self.bus_id} addr 0x{self.address:02x}") from exc
            except OSError as exc:
                raise SensorUnavailableError(
                    f"I2C write failed bus={self.bus_id} addr=0x{self.address:02x} reg=0x{register:02x}: {exc}"
                ) from exc

    def read_u8(self, register: int) -> int:
        return self.read_bytes(register, 1)[0]

    def write_u8(self, register: int, value: int) -> None:
        self.write_bytes(register, [value & 0xFF])

    def __enter__(self) -> I2CBus:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
