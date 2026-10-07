from __future__ import annotations

from server_meter.config import MemoryProtectionConfig
from server_meter.models.measurement import Measurement
from server_meter.monitoring.memory import MemoryPressure, MemoryProtector
from server_meter.monitoring.system import SystemMetrics, SystemMonitor
from server_meter.storage.ram_buffer import RamBuffer


class FakeSystem(SystemMonitor):
    def __init__(self, percent: float) -> None:
        super().__init__()
        self.percent = percent

    def snapshot(self) -> SystemMetrics:
        return SystemMetrics(
            timestamp=0.0,
            cpu_temperature_c=45.0,
            cpu_load_1m=0.2,
            cpu_load_5m=0.2,
            cpu_load_15m=0.2,
            cpu_usage_percent=10.0,
            cpu_frequency_mhz=1500.0,
            ram_total_bytes=4 * 1024**3,
            ram_used_bytes=int(self.percent / 100.0 * 4 * 1024**3),
            ram_available_bytes=int((100 - self.percent) / 100.0 * 4 * 1024**3),
            ram_usage_percent=self.percent,
            uptime_seconds=100.0,
            throttle_raw=None,
            throttle_flags=None,
            process_rss_bytes=20 * 1024 * 1024,
        )


def _buffer(n: int = 100) -> RamBuffer:
    buf = RamBuffer(max_samples=200, max_age_seconds=10_000, min_samples_keep=8)
    for i in range(n):
        buf.append(Measurement(timestamp=float(i), temperature=float(i)))
    return buf


def test_classify_levels():
    cfg = MemoryProtectionConfig()
    prot = MemoryProtector(cfg, _buffer(), FakeSystem(10))
    assert prot.classify(10) is MemoryPressure.NORMAL
    assert prot.classify(70) is MemoryPressure.WARNING
    assert prot.classify(80) is MemoryPressure.CRITICAL
    assert prot.classify(90) is MemoryPressure.EMERGENCY


def test_emergency_trims_oldest_first():
    cfg = MemoryProtectionConfig(check_interval_seconds=0)
    buf = _buffer(100)
    prot = MemoryProtector(cfg, buf, FakeSystem(95))
    snap = prot.maybe_protect(now=100.0)
    assert snap.pressure is MemoryPressure.EMERGENCY
    assert snap.trimmed > 0
    temps = [s.temperature for s in buf.snapshot()]
    assert temps == list(range(100 - len(temps), 100))
    assert temps[-1] == 99.0


def test_disabled_does_not_trim():
    cfg = MemoryProtectionConfig(enabled=False, check_interval_seconds=0)
    buf = _buffer(40)
    prot = MemoryProtector(cfg, buf, FakeSystem(99))
    snap = prot.maybe_protect(now=1.0)
    assert snap.trimmed == 0
    assert len(buf) == 40
