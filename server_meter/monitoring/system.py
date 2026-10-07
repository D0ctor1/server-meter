"""Raspberry Pi / Linux system metrics from /proc and /sys. No disk writes."""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SystemMetrics:
    timestamp: float
    cpu_temperature_c: float | None
    cpu_load_1m: float | None
    cpu_load_5m: float | None
    cpu_load_15m: float | None
    cpu_usage_percent: float | None
    cpu_frequency_mhz: float | None
    ram_total_bytes: int | None
    ram_used_bytes: int | None
    ram_available_bytes: int | None
    ram_usage_percent: float | None
    uptime_seconds: float | None
    throttle_raw: int | None
    throttle_flags: dict[str, bool] | None
    process_rss_bytes: int | None

    def to_api_dict(self) -> dict[str, Any]:
        return asdict(self)


class SystemMonitor:
    """Reads volatile kernel interfaces. Never caches onto disk."""

    def __init__(self) -> None:
        self._prev_cpu: tuple[int, int] | None = None
        self._prev_cpu_ts: float = 0.0

    def snapshot(self) -> SystemMetrics:
        mem = _read_meminfo()
        load = _read_loadavg()
        ram_total = mem.get("MemTotal")
        ram_available = mem.get("MemAvailable")
        ram_used = None
        ram_pct = None
        if ram_total is not None and ram_available is not None:
            ram_used = max(0, ram_total - ram_available)
            if ram_total > 0:
                ram_pct = 100.0 * ram_used / ram_total
        throttle_raw, throttle_flags = _read_throttled()
        return SystemMetrics(
            timestamp=time.time(),
            cpu_temperature_c=_read_cpu_temp(),
            cpu_load_1m=load[0] if load else None,
            cpu_load_5m=load[1] if load else None,
            cpu_load_15m=load[2] if load else None,
            cpu_usage_percent=self._cpu_usage_percent(),
            cpu_frequency_mhz=_read_cpu_mhz(),
            ram_total_bytes=ram_total,
            ram_used_bytes=ram_used,
            ram_available_bytes=ram_available,
            ram_usage_percent=ram_pct,
            uptime_seconds=_read_uptime(),
            throttle_raw=throttle_raw,
            throttle_flags=throttle_flags,
            process_rss_bytes=_read_self_rss(),
        )

    def _cpu_usage_percent(self) -> float | None:
        times = _read_proc_stat()
        if times is None:
            return None
        idle, total = times
        now = time.monotonic()
        usage = None
        if self._prev_cpu is not None:
            prev_idle, prev_total = self._prev_cpu
            d_idle = idle - prev_idle
            d_total = total - prev_total
            if d_total > 0:
                usage = max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))
        self._prev_cpu = (idle, total)
        self._prev_cpu_ts = now
        return usage


def _read_cpu_temp() -> float | None:
    candidates = [
        Path("/sys/class/thermal/thermal_zone0/temp"),
        Path("/sys/class/hwmon/hwmon0/temp1_input"),
        Path("/sys/class/hwmon/hwmon1/temp1_input"),
    ]
    for path in candidates:
        try:
            raw = path.read_text(encoding="ascii").strip()
            value = float(raw)
            if value > 1000:
                value /= 1000.0
            if -40.0 <= value <= 125.0:
                return value
        except OSError:
            continue
    return None


def _read_loadavg() -> tuple[float, float, float] | None:
    try:
        parts = Path("/proc/loadavg").read_text(encoding="ascii").split()
        return float(parts[0]), float(parts[1]), float(parts[2])
    except (OSError, IndexError, ValueError):
        return None


def _read_meminfo() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        text = Path("/proc/meminfo").read_text(encoding="ascii")
    except OSError:
        return result
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        tokens = rest.split()
        if not tokens:
            continue
        try:
            kb = int(tokens[0])
        except ValueError:
            continue
        result[key] = kb * 1024
    return result


def _read_uptime() -> float | None:
    try:
        return float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    except (OSError, IndexError, ValueError):
        return None


def _read_cpu_mhz() -> float | None:
    candidates = [
        Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"),
        Path("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"),
    ]
    for path in candidates:
        try:
            khz = float(path.read_text(encoding="ascii").strip())
            return khz / 1000.0
        except OSError:
            continue
    return None


def _read_proc_stat() -> tuple[int, int] | None:
    try:
        line = Path("/proc/stat").read_text(encoding="ascii").splitlines()[0]
    except OSError:
        return None
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(x) for x in parts[1:]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return idle, total


def _read_self_rss() -> int | None:
    try:
        status = Path("/proc/self/statm").read_text(encoding="ascii").split()
        pages = int(status[1])
        return pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return None


def _read_throttled() -> tuple[int | None, dict[str, bool] | None]:
    """Raspberry Pi firmware throttle bitmap, if exposed on Ubuntu."""
    candidates = [
        Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
        Path("/sys/firmware/devicetree/base/thermal-zones"),
    ]
    raw_path = Path("/sys/class/hwmon")
    # Direct sysfs used by some Ubuntu Pi kernels:
    for path in [
        Path("/sys/devices/platform/soc/soc:firmware/get_throttled"),
        Path("/proc/device-tree/chosen/rpi-throttled"),
    ]:
        try:
            text = path.read_text(encoding="ascii", errors="ignore").strip()
            if text.startswith("0x") or text.isdigit():
                value = int(text, 0)
                return value, _decode_throttle(value)
        except (OSError, ValueError):
            continue
    # vcgencmd is optional and not always present on Ubuntu Server.
    try:
        import shutil
        import subprocess

        vcgencmd = shutil.which("vcgencmd")
        if vcgencmd:
            proc = subprocess.run(
                [vcgencmd, "get_throttled"],
                capture_output=True,
                text=True,
                timeout=0.4,
                check=False,
            )
            if proc.returncode == 0 and "throttled=" in proc.stdout:
                hex_part = proc.stdout.strip().split("=", 1)[1]
                value = int(hex_part, 0)
                return value, _decode_throttle(value)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    _ = raw_path
    return None, None


def _decode_throttle(value: int) -> dict[str, bool]:
    # Raspberry Pi firmware get_throttled bits
    return {
        "under_voltage": bool(value & (1 << 0)),
        "arm_freq_capped": bool(value & (1 << 1)),
        "throttled": bool(value & (1 << 2)),
        "soft_temp_limit": bool(value & (1 << 3)),
        "under_voltage_occurred": bool(value & (1 << 16)),
        "arm_freq_capped_occurred": bool(value & (1 << 17)),
        "throttled_occurred": bool(value & (1 << 18)),
        "soft_temp_limit_occurred": bool(value & (1 << 19)),
    }
