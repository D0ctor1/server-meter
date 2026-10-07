"""Sensor driver interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from server_meter.models.measurement import Measurement, SensorStatus


class SensorDriver(ABC):
    name: str = "sensor"

    @abstractmethod
    def open(self) -> None:
        """Detect hardware / initialize algorithms. Raise SensorError on failure."""

    @abstractmethod
    def read(self) -> Measurement:
        """Return one sample. Raise SensorError on failure; never persist data."""

    @abstractmethod
    def close(self) -> None:
        """Release I²C / native resources. Must not write to disk."""

    def recover(self) -> None:
        """Re-open after a communication failure."""
        self.close()
        self.open()

    def describe(self) -> dict[str, object]:
        return {"driver": self.name, "status": SensorStatus.UNKNOWN.value}
