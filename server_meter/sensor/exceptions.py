"""Sensor and I²C errors. These must never crash the HTTP server."""


class SensorError(Exception):
    """Base class for recoverable sensor failures."""


class SensorUnavailableError(SensorError):
    """Sensor is not present or communication failed."""


class SensorTimeoutError(SensorError):
    """I²C or measurement timed out."""


class SensorProtocolError(SensorError):
    """Unexpected chip ID, invalid payload, or BSEC library error."""


class BsecUnavailableError(SensorError):
    """Bosch BSEC shared library is not installed or failed to load."""
