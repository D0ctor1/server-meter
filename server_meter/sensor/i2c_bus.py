"""Thin I²C wrapper around smbus2 with timeouts. No disk I/O."""

from __future__ import annotations

import threading
from types import TracebackType

from server_meter.sensor.exceptions import SensorTimeoutError, SensorUnavailableError


class I2CBus:
    def __init__(self, bus_id: int, address: int, timeout_seconds: float = 1.0) -> None:
        self.bus_id = bus_id
        self.address = address
        self.timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._bus = None

    def open(self) -> None:
        try:
            from smbus2 import SMBus
        except ImportError as exc:
            raise SensorUnavailableError("smbus2 is required for the BME690 driver") from exc
        try:
            self._bus = SMBus(self.bus_id)
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
