from __future__ import annotations

from server_meter.config import AppConfig, MetricThreshold, NotificationsConfig
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.monitoring.system import SystemMetrics
from server_meter.notification.engine import NotificationEngine
from server_meter.notification.i18n import EMAIL_I18N, t
from server_meter.notification.models import AlarmState
from server_meter.notification.rules import raw_level
from server_meter.notification.smtp import SmtpError, _sanitize
from tests.conftest import make_config


def _system(**kwargs) -> SystemMetrics:
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
        throttle_flags={"throttled": False},
        process_rss_bytes=10_000_000,
    )
    defaults.update(kwargs)
    return SystemMetrics(**defaults)


def _sample(**kwargs) -> Measurement:
    data = dict(
        timestamp=1_000.0,
        temperature=24.0,
        humidity=45.0,
        pressure=1008.0,
        gas_resistance=120000.0,
        iaq=40.0,
        iaq_accuracy=3,
        co2_equivalent=500.0,
        breath_voc_equivalent=0.3,
        sensor_status=SensorStatus.OK,
    )
    data.update(kwargs)
    return Measurement(**data)


def _notify_config(**email_over) -> AppConfig:
    cfg = make_config()
    payload = cfg.notifications.model_dump(by_alias=True)
    payload["enabled"] = True
    payload["email"]["enabled"] = True
    payload["email"]["cooldown_seconds"] = 60
    payload["email"]["notify_recovery"] = True
    payload["email"]["from"] = "meter@example.com"
    payload["email"]["to"] = ["admin@example.com"]
    payload["email"]["smtp"]["host"] = "smtp.example.com"
    payload["thresholds"]["temperature"]["min_duration_seconds"] = 30
    payload["email"].update(email_over)
    cfg.notifications = NotificationsConfig.model_validate(payload)
    return cfg


class Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_hysteresis_warning_and_critical():
    spec = MetricThreshold(warning_high=45, critical_high=50, hysteresis=2)
    assert raw_level(44.9, spec, AlarmState.NORMAL) is AlarmState.NORMAL
    assert raw_level(45.0, spec, AlarmState.NORMAL) is AlarmState.WARNING
    assert raw_level(49.9, spec, AlarmState.WARNING) is AlarmState.WARNING
    assert raw_level(50.0, spec, AlarmState.WARNING) is AlarmState.CRITICAL
    assert raw_level(48.0, spec, AlarmState.CRITICAL) is AlarmState.CRITICAL
    assert raw_level(47.9, spec, AlarmState.CRITICAL) is AlarmState.WARNING
    assert raw_level(43.0, spec, AlarmState.WARNING) is AlarmState.WARNING
    assert raw_level(42.9, spec, AlarmState.WARNING) is AlarmState.NORMAL


def test_min_duration_cooldown_and_recovery():
    sent: list[str] = []
    clock = Clock(0)

    def capture(message, _config) -> None:
        sent.append(message.kind)

    cfg = _notify_config()
    engine = NotificationEngine(cfg, send_fn=capture, time_fn=clock)
    sample = _sample(temperature=51.0)
    sysm = _system()
    engine.observe(sample, sysm, SensorStatus.OK, 1)
    assert sent == []
    clock.t = 29
    engine.observe(sample, sysm, SensorStatus.OK, 1)
    assert sent == []
    clock.t = 30
    engine.observe(sample, sysm, SensorStatus.OK, 1)
    assert sent == ["CRITICAL"]
    clock.t = 50
    engine.observe(sample, sysm, SensorStatus.OK, 1)
    assert sent == ["CRITICAL"]
    clock.t = 90
    engine.observe(sample, sysm, SensorStatus.OK, 1)
    assert sent == ["CRITICAL", "CRITICAL"]
    cool = _sample(temperature=40.0)
    clock.t = 120
    engine.observe(cool, sysm, SensorStatus.OK, 1)
    assert sent == ["CRITICAL", "CRITICAL"]
    clock.t = 150
    engine.observe(cool, sysm, SensorStatus.OK, 1)
    assert sent[-1] == "RECOVERY"
    clock.t = 180
    engine.observe(cool, sysm, SensorStatus.OK, 1)
    assert sent.count("RECOVERY") == 1


def test_smtp_failure_does_not_raise_from_observe():
    def boom(_message, _config) -> None:
        raise SmtpError("SMTP host is not configured")

    cfg = _notify_config()
    cfg.notifications.thresholds.temperature.min_duration_seconds = 0
    clock = Clock(0)
    engine = NotificationEngine(cfg, send_fn=boom, time_fn=clock)
    engine.observe(_sample(temperature=51.0), _system(), SensorStatus.OK, 1)
    assert engine.delivery_ok is False
    assert engine.last_delivery_error


def test_engine_exception_is_swallowed():
    cfg = _notify_config()
    engine = NotificationEngine(cfg, send_fn=lambda *_: None)
    engine._observe = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
    engine.observe(_sample(), _system(), SensorStatus.OK, 1)


def test_disabled_metrics_do_not_make_overall_unknown():
    cfg = _notify_config()
    engine = NotificationEngine(cfg, send_fn=lambda *_: None, time_fn=Clock(0))
    engine.observe(_sample(), _system(), SensorStatus.OK, 1)
    assert engine.overall_state() is AlarmState.NORMAL
    assert engine._states["pressure"].state is AlarmState.NORMAL


def test_sensor_unavailable_critical():
    sent: list[str] = []
    clock = Clock(0)
    cfg = _notify_config()
    cfg.notifications.thresholds.sensor_unavailable.min_duration_seconds = 0
    engine = NotificationEngine(cfg, send_fn=lambda msg, _c: sent.append(msg.metric), time_fn=clock)
    engine.observe(None, _system(), SensorStatus.UNAVAILABLE, None)
    assert "sensor_unavailable" in sent
    assert engine.overall_state() is AlarmState.CRITICAL


def test_air_quality_copy_has_no_toxic_claims():
    blob = "\n".join(f"{k}={v}" for table in EMAIL_I18N.values() for k, v in table.items())
    for forbidden in ("toxic", "poison", "dangerous to breathe", "Toxic gas"):
        assert forbidden.lower() not in blob.lower()
    assert "indikátor" in t("CZ", "body.note.air") or "odchylky" in t("CZ", "body.note.air")
    assert "anomaly" in t("EN", "body.note.air").lower() or "indicator" in t("EN", "body.note.air").lower()


def test_email_locale_changes_body_not_status_token():
    assert t("CZ", "subject.critical", metric="Teplota BME690") == "[server-meter][CRITICAL] Teplota BME690"
    assert t("EN", "subject.critical", metric="BME690 temperature") == "[server-meter][CRITICAL] BME690 temperature"
    assert "[TEST]" in t("CZ", "subject.test")
    assert "Upozornění" in t("CZ", "body.header")
    assert t("EN", "body.header") == "server-meter alert"


def test_sanitize_strips_password():
    assert "secret-pass" not in _sanitize("login secret-pass failed", "secret-pass")
    assert _sanitize("SMTPAuthenticationError: password rejected", "secret") == "SMTP authentication failed"


def test_missing_notifications_block_defaults_off():
    data = make_config().model_dump()
    data.pop("notifications", None)
    cfg = AppConfig.model_validate(data)
    assert cfg.notifications.enabled is False
    assert cfg.notifications.email.enabled is False
    assert cfg.notifications.thresholds.temperature.warning_high == 45
    assert cfg.public_status_dict()["notifications_enabled"] is False
