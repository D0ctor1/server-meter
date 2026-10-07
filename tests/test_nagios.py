from __future__ import annotations

from server_meter.api.nagios import NagiosState, evaluate_nagios
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.monitoring.system import SystemMetrics
from tests.conftest import make_config
from server_meter.service import MeterService


class StubSystem:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def snapshot(self) -> SystemMetrics:
        defaults = dict(
            timestamp=0.0,
            cpu_temperature_c=48.0,
            cpu_load_1m=0.3,
            cpu_load_5m=0.3,
            cpu_load_15m=0.2,
            cpu_usage_percent=12.0,
            cpu_frequency_mhz=1800.0,
            ram_total_bytes=4 * 1024**3,
            ram_used_bytes=1 * 1024**3,
            ram_available_bytes=3 * 1024**3,
            ram_usage_percent=25.0,
            uptime_seconds=1000.0,
            throttle_raw=0,
            throttle_flags={
                "under_voltage": False,
                "arm_freq_capped": False,
                "throttled": False,
                "soft_temp_limit": False,
            },
            process_rss_bytes=10_000_000,
        )
        defaults.update(self.kwargs)
        return SystemMetrics(**defaults)


def _service(**system) -> MeterService:
    svc = MeterService(make_config())
    svc.system = StubSystem(**system)  # type: ignore[assignment]
    return svc


def test_ok_when_sensor_fresh():
    svc = _service()
    svc.sensor_status = SensorStatus.OK
    svc.stats.last_success_at = 1_000_000.0
    svc.current = Measurement(timestamp=1_000_000.0, temperature=24.1, humidity=45.2, pressure=1008.2, gas_resistance=123400)
    import server_meter.api.nagios as nagios

    original = nagios.evaluate_nagios.__globals__  # keep import used
    _ = original
    # Freeze age by monkeypatching sensor_age
    svc.sensor_age_seconds = lambda: 2.0  # type: ignore[method-assign]
    state, body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.OK
    assert body.startswith("OK")
    assert "temperature=24.1C" in body


def test_critical_sensor_down():
    svc = _service()
    svc.sensor_status = SensorStatus.UNAVAILABLE
    svc.current = None
    state, body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.CRITICAL
    assert "CRITICAL" in body
    assert "communication failure" in body


def test_unknown_before_first_sample():
    svc = _service()
    svc.sensor_status = SensorStatus.INITIALIZING
    svc.current = None
    state, body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.UNKNOWN
    assert body.startswith("UNKNOWN")


def test_warning_ram():
    svc = _service(ram_usage_percent=82.0)
    svc.sensor_status = SensorStatus.OK
    svc.current = Measurement(timestamp=1.0, temperature=22.0)
    svc.sensor_age_seconds = lambda: 1.0  # type: ignore[method-assign]
    state, body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.WARNING
    assert "RAM usage 82%" in body


def test_critical_cpu_temp():
    svc = _service(cpu_temperature_c=85.0)
    svc.sensor_status = SensorStatus.OK
    svc.current = Measurement(timestamp=1.0, temperature=22.0)
    svc.sensor_age_seconds = lambda: 1.0  # type: ignore[method-assign]
    state, _body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.CRITICAL


def test_stale_sensor_critical():
    svc = _service()
    svc.sensor_status = SensorStatus.OK
    svc.current = Measurement(timestamp=1.0, temperature=22.0)
    svc.sensor_age_seconds = lambda: 90.0  # type: ignore[method-assign]
    state, body = evaluate_nagios(svc, svc.config)
    assert state is NagiosState.CRITICAL
    assert "stale" in body
