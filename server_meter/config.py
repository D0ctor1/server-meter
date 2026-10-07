"""YAML configuration loading and production validation.

Sensor measurements and alarm state stay in RAM.
Notification / SMTP settings may be written atomically from the Settings UI.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, ValidationError, field_validator, model_validator

# Absolute hard cap: even a broken YAML cannot grow RAM without bound.
HISTORY_HARD_MAX_SAMPLES = 20_000
DEFAULT_PASSWORD_PLACEHOLDER = "CHANGE_ME"
VALID_I2C_ADDRESSES = {0x76, 0x77}
SUPPORTED_LOCALES = ("CZ", "EN")
DEFAULT_LOCALE = "CZ"


class ConfigError(ValueError):
    """Raised when configuration is missing, invalid, or unsafe for production."""


class ApplicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "server-meter"
    environment: Literal["production", "development", "test"] = "production"


class AuthConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    username: str = "admin"
    password: str = DEFAULT_PASSWORD_PLACEHOLDER


class WebConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    api_docs_enabled: bool = False
    health_public: bool = True
    max_request_bytes: int = Field(default=16_384, ge=1024, le=1_048_576)
    # UI language only. Missing key → CZ so existing YAML keeps working.
    locale: str = DEFAULT_LOCALE
    # SQLite file for accounts (not sensor history). Empty → default path.
    users_db: str = ""

    @field_validator("locale", mode="before")
    @classmethod
    def validate_locale(cls, value: Any) -> str:
        if value is None:
            return DEFAULT_LOCALE
        if isinstance(value, str) and not value.strip():
            return DEFAULT_LOCALE
        candidate = str(value).strip()
        normalized = candidate.upper()
        if normalized not in SUPPORTED_LOCALES:
            raise ValueError(
                f"Invalid locale '{candidate}'.\n\nSupported locales:\n- CZ\n- EN"
            )
        return normalized


class I2CConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bus: int = Field(default=1, ge=0, le=16)
    address: int = 0x77

    @field_validator("address", mode="before")
    @classmethod
    def parse_i2c_address(cls, value: Any) -> int:
        if isinstance(value, str):
            text = value.strip().lower()
            value = int(text, 16) if text.startswith("0x") else int(text)
        if not isinstance(value, int):
            raise ValueError("I2C address must be an integer (0x76 or 0x77)")
        if value not in VALID_I2C_ADDRESSES:
            raise ValueError("I2C address must be 0x76 or 0x77")
        return value


class BsecConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    library_path: str = ""
    config_blob_path: str = ""
    sample_rate: Literal["lp", "ulp"] = "lp"
    temperature_offset: float = 0.0
    persist_state: bool = False

    @field_validator("persist_state")
    @classmethod
    def forbid_disk_state(cls, value: bool) -> bool:
        if value:
            raise ValueError(
                "BSEC runtime state must stay in RAM. persist_state cannot be true "
                "(SD-card write protection)."
            )
        return value


class SensorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = "BME690"
    driver: Literal["bme690", "mock", "bme69x_python"] = "bme690"
    i2c: I2CConfig = Field(default_factory=I2CConfig)
    interval_seconds: float = Field(default=5.0, ge=1.0, le=3600.0)
    heater_temperature_c: int = Field(default=320, ge=200, le=400)
    heater_duration_ms: int = Field(default=150, ge=1, le=2000)
    bsec: BsecConfig = Field(default_factory=BsecConfig)
    retry_initial_seconds: float = Field(default=2.0, ge=0.5, le=60.0)
    retry_max_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    i2c_timeout_seconds: float = Field(default=1.0, ge=0.1, le=10.0)


class HistoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_samples: int = Field(default=10_000, ge=10, le=HISTORY_HARD_MAX_SAMPLES)
    max_age_seconds: int = Field(default=86_400, ge=60, le=7 * 24 * 3600)
    min_samples_keep: int = Field(default=64, ge=8, le=1000)

    @model_validator(mode="after")
    def cap_hard_limit(self) -> HistoryConfig:
        if self.max_samples > HISTORY_HARD_MAX_SAMPLES:
            object.__setattr__(self, "max_samples", HISTORY_HARD_MAX_SAMPLES)
        if self.min_samples_keep >= self.max_samples:
            raise ValueError("history.min_samples_keep must be smaller than max_samples")
        return self


class MemoryProtectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    warning_percent: float = Field(default=70.0, ge=1.0, le=99.0)
    critical_percent: float = Field(default=80.0, ge=1.0, le=99.0)
    emergency_percent: float = Field(default=90.0, ge=1.0, le=99.0)
    warning_trim_fraction: float = Field(default=0.10, ge=0.01, le=0.90)
    critical_trim_fraction: float = Field(default=0.25, ge=0.01, le=0.90)
    emergency_trim_fraction: float = Field(default=0.50, ge=0.01, le=0.95)
    check_interval_seconds: float = Field(default=15.0, ge=5.0, le=300.0)

    @model_validator(mode="after")
    def ordered_thresholds(self) -> MemoryProtectionConfig:
        if not (
            self.warning_percent < self.critical_percent < self.emergency_percent
        ):
            raise ValueError(
                "memory_protection thresholds must satisfy warning < critical < emergency"
            )
        return self


class NagiosThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cpu_temperature_warning: float = Field(default=70.0, ge=40.0, le=100.0)
    cpu_temperature_critical: float = Field(default=80.0, ge=40.0, le=110.0)
    ram_usage_warning: float = Field(default=70.0, ge=10.0, le=99.0)
    ram_usage_critical: float = Field(default=85.0, ge=10.0, le=99.9)
    iaq_warning: float = Field(default=150.0, ge=50.0, le=500.0)
    iaq_critical: float = Field(default=250.0, ge=50.0, le=500.0)
    cpu_load_warning: float = Field(default=2.0, ge=0.1, le=32.0)
    cpu_load_critical: float = Field(default=4.0, ge=0.1, le=64.0)

    @model_validator(mode="after")
    def ordered_nagios(self) -> NagiosThresholds:
        pairs = [
            ("cpu_temperature_warning", "cpu_temperature_critical"),
            ("ram_usage_warning", "ram_usage_critical"),
            ("iaq_warning", "iaq_critical"),
            ("cpu_load_warning", "cpu_load_critical"),
        ]
        for low, high in pairs:
            if getattr(self, low) >= getattr(self, high):
                raise ValueError(f"nagios.thresholds.{low} must be < {high}")
        return self


class NagiosConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    sensor_max_age_seconds: float = Field(default=30.0, ge=3.0, le=3600.0)
    thresholds: NagiosThresholds = Field(default_factory=NagiosThresholds)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    access_log: bool = False


class MetricThreshold(BaseModel):
    """Anomaly thresholds for one metric. Not medical or safety limits."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    warning_high: float | None = None
    critical_high: float | None = None
    warning_low: float | None = None
    critical_low: float | None = None
    warning_clear_high: float | None = None
    critical_clear_high: float | None = None
    warning_clear_low: float | None = None
    critical_clear_low: float | None = None
    hysteresis: float | None = None
    min_duration_seconds: float = Field(default=30.0, ge=0.0, le=3600.0)

    @model_validator(mode="after")
    def ordered_bounds(self) -> MetricThreshold:
        if self.warning_high is not None and self.critical_high is not None:
            if self.warning_high >= self.critical_high:
                raise ValueError("warning_high must be < critical_high")
        if self.warning_low is not None and self.critical_low is not None:
            if self.warning_low <= self.critical_low:
                raise ValueError("warning_low must be > critical_low")
        return self

    def clear_high(self, kind: str) -> float | None:
        explicit = self.warning_clear_high if kind == "warning" else self.critical_clear_high
        if explicit is not None:
            return explicit
        high = self.warning_high if kind == "warning" else self.critical_high
        if high is None:
            return None
        delta = self.hysteresis if self.hysteresis is not None else _default_hysteresis(high)
        return high - delta

    def clear_low(self, kind: str) -> float | None:
        explicit = self.warning_clear_low if kind == "warning" else self.critical_clear_low
        if explicit is not None:
            return explicit
        low = self.warning_low if kind == "warning" else self.critical_low
        if low is None:
            return None
        delta = self.hysteresis if self.hysteresis is not None else _default_hysteresis(low)
        return low + delta


def _default_hysteresis(magnitude: float) -> float:
    abs_val = abs(magnitude)
    if abs_val >= 100:
        return max(1.0, abs_val * 0.04)
    if abs_val >= 10:
        return 2.0
    if abs_val >= 1:
        return 0.1
    return 0.05


def _th(
    *,
    enabled: bool = True,
    warning_high: float | None = None,
    critical_high: float | None = None,
    warning_low: float | None = None,
    critical_low: float | None = None,
    hysteresis: float | None = None,
    min_duration_seconds: float = 30.0,
) -> MetricThreshold:
    return MetricThreshold(
        enabled=enabled,
        warning_high=warning_high,
        critical_high=critical_high,
        warning_low=warning_low,
        critical_low=critical_low,
        hysteresis=hysteresis,
        min_duration_seconds=min_duration_seconds,
    )


class NotificationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=45, critical_high=50, hysteresis=2, min_duration_seconds=30)
    )
    humidity: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=80, critical_high=90, hysteresis=2, min_duration_seconds=30)
    )
    pressure: MetricThreshold = Field(
        default_factory=lambda: _th(
            enabled=False, warning_low=980, critical_low=960, warning_high=1040, critical_high=1060, hysteresis=5
        )
    )
    gas_resistance: MetricThreshold = Field(
        default_factory=lambda: _th(enabled=False, warning_low=20_000, critical_low=8_000, hysteresis=2_000)
    )
    iaq: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=150, critical_high=250, hysteresis=10, min_duration_seconds=60)
    )
    iaq_accuracy: MetricThreshold = Field(
        default_factory=lambda: _th(enabled=False, warning_low=1, critical_low=0, hysteresis=0, min_duration_seconds=300)
    )
    static_iaq: MetricThreshold = Field(
        default_factory=lambda: _th(enabled=False, warning_high=150, critical_high=250, hysteresis=10, min_duration_seconds=60)
    )
    eco2: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=1500, critical_high=2500, hysteresis=100, min_duration_seconds=60)
    )
    bvoc: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=1.0, critical_high=2.0, hysteresis=0.1, min_duration_seconds=60)
    )
    cpu_temperature: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=70, critical_high=80, hysteresis=2, min_duration_seconds=30)
    )
    cpu_usage: MetricThreshold = Field(
        default_factory=lambda: _th(enabled=False, warning_high=85, critical_high=95, hysteresis=5, min_duration_seconds=60)
    )
    ram_usage: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=70, critical_high=85, hysteresis=5, min_duration_seconds=60)
    )
    sensor_unavailable: MetricThreshold = Field(
        default_factory=lambda: _th(warning_high=15, critical_high=30, hysteresis=5, min_duration_seconds=0)
    )


class SmtpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    security: Literal["none", "starttls", "tls"] = "starttls"
    username: str = ""
    password: str = ""
    timeout_seconds: float = Field(default=15.0, ge=1.0, le=60.0)


class EmailNotificationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool = False
    cooldown_seconds: int = Field(default=3600, ge=60, le=86400)
    notify_recovery: bool = True
    from_address: str = Field(default="", alias="from")
    to: list[str] = Field(default_factory=list)
    web_url: str = ""
    smtp: SmtpConfig = Field(default_factory=SmtpConfig)

    @field_validator("to", mode="before")
    @classmethod
    def coerce_recipients(cls, value: Any) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


class NotificationsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    max_queue_size: int = Field(default=10, ge=1, le=50)
    email: EmailNotificationConfig = Field(default_factory=EmailNotificationConfig)
    thresholds: NotificationThresholds = Field(default_factory=NotificationThresholds)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application: ApplicationConfig = Field(default_factory=ApplicationConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    sensor: SensorConfig = Field(default_factory=SensorConfig)
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    memory_protection: MemoryProtectionConfig = Field(default_factory=MemoryProtectionConfig)
    nagios: NagiosConfig = Field(default_factory=NagiosConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    _source_path: Path | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def production_safety(self) -> AppConfig:
        env = self.application.environment
        auth = self.web.auth
        if env == "production":
            if self.web.api_docs_enabled:
                raise ConfigError("web.api_docs_enabled must be false in production")
            if not auth.enabled:
                raise ConfigError("web.auth.enabled must be true in production")
            if not auth.username.strip():
                raise ConfigError("web.auth.username is empty")
            if not auth.password:
                raise ConfigError("web.auth.password is empty")
            if auth.password != "MIGRATED" and len(auth.password) < 8:
                raise ConfigError("web.auth.password must be at least 8 characters in production")
            # CHANGE_ME is allowed so install.sh can start the service unattended.
            # After the first start, login uses SQLite hashes; YAML may stay as a
            # one-time migration source. The UI flags default_password_active.
        if self.sensor.driver == "bme690" and self.sensor.type.upper() not in {"BME690", "BME69X"}:
            raise ConfigError("sensor.type must be BME690 when driver is bme690")
        if self.sensor.bsec.enabled and self.sensor.bsec.sample_rate == "lp":
            if self.sensor.interval_seconds < 3.0:
                raise ConfigError(
                    "sensor.interval_seconds < 3 is incompatible with BSEC LP mode "
                    "(Bosch BSEC_SAMPLE_RATE_LP is 1/3 Hz). Use interval_seconds >= 3 "
                    "or set sensor.bsec.sample_rate: ulp / disable BSEC."
                )
        if self.sensor.bsec.enabled and self.sensor.bsec.sample_rate == "ulp":
            if self.sensor.interval_seconds < 300.0:
                raise ConfigError(
                    "sensor.interval_seconds must be >= 300 when BSEC ULP mode is selected"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.application.environment == "production"

    def public_status_dict(self) -> dict[str, Any]:
        """Subset of config that is safe to expose (no secrets)."""
        return {
            "name": self.application.name,
            "environment": self.application.environment,
            "sensor_driver": self.sensor.driver,
            "sensor_type": self.sensor.type,
            "i2c_bus": self.sensor.i2c.bus,
            "i2c_address": hex(self.sensor.i2c.address),
            "interval_seconds": self.sensor.interval_seconds,
            "bsec_enabled": self.sensor.bsec.enabled and self.sensor.driver != "mock",
            "history_max_samples": self.history.max_samples,
            "history_max_age_seconds": self.history.max_age_seconds,
            "memory_protection": self.memory_protection.enabled,
            "api_docs_enabled": self.web.api_docs_enabled,
            "auth_enabled": self.web.auth.enabled,
            "default_password_active": self.web.auth.password == DEFAULT_PASSWORD_PLACEHOLDER,
            "locale": self.web.locale,
            "notifications_enabled": self.notifications.enabled,
            "email_notifications_enabled": self.notifications.enabled and self.notifications.email.enabled,
        }


def _default_config_paths() -> list[Path]:
    env_path = os.environ.get("SERVER_METER_CONFIG")
    candidates: list[Path] = []
    if env_path:
        candidates.append(Path(env_path))
    here = Path(__file__).resolve().parent.parent
    candidates.extend(
        [
            Path("/etc/server-meter/config.yaml"),
            here / "config" / "config.yaml",
            here / "config" / "config.example.yaml",
        ]
    )
    return candidates


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is not None:
        config_path = Path(path)
        if not os.access(config_path.parent, os.X_OK):
            raise ConfigError(
                f"Configuration directory not accessible by this user: {config_path.parent}"
            )
        if config_path.exists() and not os.access(config_path, os.R_OK):
            raise ConfigError(f"Configuration file not readable: {config_path}")
        if not config_path.is_file():
            raise ConfigError(f"Configuration file not found: {config_path}")
        return _parse_yaml(config_path)

    for candidate in _default_config_paths():
        if candidate.is_file():
            return _parse_yaml(candidate)
    raise ConfigError(
        "No configuration file found. Copy config/config.example.yaml to "
        "config/config.yaml or /etc/server-meter/config.yaml"
    )


def _parse_yaml(path: Path) -> AppConfig:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration {path}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if data is None:
        raise ConfigError(f"Configuration file is empty: {path}")
    if not isinstance(data, dict):
        raise ConfigError("Configuration root must be a mapping")
    try:
        cfg = AppConfig.model_validate(data)
        cfg._source_path = path
        return cfg
    except ConfigError:
        raise
    except ValidationError as exc:
        raise _config_error_from_validation(exc) from exc
    except Exception as exc:
        raise ConfigError(f"Invalid configuration: {exc}") from exc


def _config_error_from_validation(exc: ValidationError) -> ConfigError:
    """Surface locale errors in the operator-facing wording from the spec."""
    for err in exc.errors():
        msg = err.get("msg", "")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        if msg.startswith("Invalid locale"):
            return ConfigError(msg)
    return ConfigError(f"Invalid configuration: {exc}")
