"""RAM-only storage. No disk backends."""

from server_meter.storage.ram_buffer import HISTORY_HARD_MAX_SAMPLES, RamBuffer

__all__ = ["HISTORY_HARD_MAX_SAMPLES", "RamBuffer"]
