"""Email copy. Independent of the browser i18n file; same semantic keys."""

from __future__ import annotations

from datetime import datetime, timezone

EMAIL_I18N = {
    "CZ": {
        "subject.warning": "[server-meter][WARNING] {metric}",
        "subject.critical": "[server-meter][CRITICAL] {metric}",
        "subject.recovery": "[server-meter][RECOVERY] {metric}",
        "subject.test": "[server-meter][TEST] SMTP",
        "metric.temperature": "Teplota BME690",
        "metric.humidity": "Vlhkost BME690",
        "metric.pressure": "Tlak BME690",
        "metric.gas_resistance": "Odpor plynu BME690",
        "metric.iaq": "Kvalita vzduchu (IAQ)",
        "metric.iaq_accuracy": "Přesnost IAQ",
        "metric.static_iaq": "Statické IAQ",
        "metric.eco2": "eCO₂ (odhad)",
        "metric.bvoc": "bVOC (odhad)",
        "metric.cpu_temperature": "Teplota CPU",
        "metric.cpu_usage": "Využití CPU",
        "metric.ram_usage": "Využití RAM",
        "metric.sensor_unavailable": "Senzor BME690 nedostupný",
        "metric.air_quality": "Kvalita vzduchu",
        "body.header": "Upozornění server-meter",
        "body.test_header": "Testovací email server-meter",
        "body.host": "Hostitel",
        "body.status": "Stav",
        "body.metric": "Metrika",
        "body.value": "Aktuální hodnota",
        "body.threshold": "Práh",
        "body.warning_threshold": "Práh WARNING",
        "body.critical_threshold": "Práh CRITICAL",
        "body.duration": "Doba",
        "body.time": "Čas",
        "body.web": "Webové rozhraní",
        "body.previous": "Předchozí stav",
        "body.note.air": "BME690/BSEC poskytuje indikátor kvality vzduchu, nikoliv certifikované měření škodlivin. Jde o detekci odchylky, ne o zdravotní limit.",
        "body.note.generic": "Výchozí prahy slouží k detekci výrazných odchylek a nejsou zdravotními limity.",
        "body.reason.high": "Hodnota je nad nastaveným prahem odchylky.",
        "body.reason.low": "Hodnota je pod nastaveným prahem odchylky.",
        "body.reason.sensor": "Senzor BME690 neposkytuje čerstvé měření.",
        "body.reason.recovery": "Hodnota se vrátila pod prahové meze s hysterézí.",
        "body.test": "Toto je test SMTP z webového nastavení. Žádný alarm nevznikl.",
        "state.NORMAL": "NORMAL",
        "state.WARNING": "WARNING",
        "state.CRITICAL": "CRITICAL",
        "state.UNKNOWN": "UNKNOWN",
        "duration.seconds": "{n} s",
    },
    "EN": {
        "subject.warning": "[server-meter][WARNING] {metric}",
        "subject.critical": "[server-meter][CRITICAL] {metric}",
        "subject.recovery": "[server-meter][RECOVERY] {metric}",
        "subject.test": "[server-meter][TEST] SMTP",
        "metric.temperature": "BME690 temperature",
        "metric.humidity": "BME690 humidity",
        "metric.pressure": "BME690 pressure",
        "metric.gas_resistance": "BME690 gas resistance",
        "metric.iaq": "Air quality (IAQ)",
        "metric.iaq_accuracy": "IAQ accuracy",
        "metric.static_iaq": "Static IAQ",
        "metric.eco2": "eCO₂ (estimate)",
        "metric.bvoc": "bVOC (estimate)",
        "metric.cpu_temperature": "CPU temperature",
        "metric.cpu_usage": "CPU usage",
        "metric.ram_usage": "RAM usage",
        "metric.sensor_unavailable": "BME690 sensor unavailable",
        "metric.air_quality": "Air quality",
        "body.header": "server-meter alert",
        "body.test_header": "server-meter SMTP test",
        "body.host": "Host",
        "body.status": "Status",
        "body.metric": "Metric",
        "body.value": "Current value",
        "body.threshold": "Threshold",
        "body.warning_threshold": "Warning threshold",
        "body.critical_threshold": "Critical threshold",
        "body.duration": "Duration",
        "body.time": "Time",
        "body.web": "Web interface",
        "body.previous": "Previous status",
        "body.note.air": "BME690/BSEC provides an air-quality indicator, not a certified measurement of hazardous gases. This is an anomaly threshold, not a medical limit.",
        "body.note.generic": "Default values are intended to detect significant anomalies and are not medical or safety limits.",
        "body.reason.high": "The value is above the configured anomaly threshold.",
        "body.reason.low": "The value is below the configured anomaly threshold.",
        "body.reason.sensor": "The BME690 sensor is not providing a fresh measurement.",
        "body.reason.recovery": "The value returned inside the hysteresis limits.",
        "body.test": "This is an SMTP test from the Settings page. No alarm was raised.",
        "state.NORMAL": "NORMAL",
        "state.WARNING": "WARNING",
        "state.CRITICAL": "CRITICAL",
        "state.UNKNOWN": "UNKNOWN",
        "duration.seconds": "{n} s",
    },
}


def t(locale: str, key: str, **params: object) -> str:
    table = EMAIL_I18N.get((locale or "CZ").upper(), EMAIL_I18N["CZ"])
    text = table.get(key) or EMAIL_I18N["EN"].get(key) or key
    for name, value in params.items():
        text = text.replace("{" + name + "}", str(value))
    return text


def format_event_time(ts: float, locale: str) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
    if (locale or "CZ").upper() == "CZ":
        return f"{dt.day}. {dt.month}. {dt.year} {dt:%H:%M:%S}"
    return f"{dt.day} {dt.strftime('%b %Y %H:%M:%S')}"
