"""Evaluate samples in RAM and enqueue emails without blocking I²C."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable
from typing import Any

from server_meter.config import AppConfig, MetricThreshold, NotificationThresholds
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.monitoring.system import SystemMetrics
from server_meter.notification.i18n import format_event_time, t
from server_meter.notification.models import (
    AIR_QUALITY_METRICS,
    METRIC_GETTERS,
    METRIC_UNITS,
    AlarmState,
    MetricAlarm,
    OutboundEmail,
)
from server_meter.notification.rules import raw_level
from server_meter.notification.smtp import SmtpError, send_email

logger = logging.getLogger("server_meter.notification")

SendFn = Callable[[OutboundEmail, AppConfig], None]


class NotificationEngine:
    def __init__(
        self,
        config: AppConfig,
        *,
        send_fn: SendFn | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self._send = send_fn or send_email
        self._time = time_fn or time.time
        self._states: dict[str, MetricAlarm] = {}
        self._queue: asyncio.Queue[OutboundEmail | None] | None = None
        self._task: asyncio.Task[None] | None = None
        self.last_delivery_error: str | None = None
        self.delivery_ok = True

    def replace_config(self, config: AppConfig) -> None:
        self.config = config

    def start(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        size = self.config.notifications.max_queue_size
        self._queue = asyncio.Queue(maxsize=size)
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._worker(), name="server-meter-smtp")

    async def stop(self) -> None:
        if self._queue is not None:
            try:
                self._queue.put_nowait(None)
            except asyncio.QueueFull:
                pass
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=6.0)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            item = await self._queue.get()
            if item is None:
                return
            try:
                await asyncio.to_thread(self._send, item, self.config)
                self.delivery_ok = True
                self.last_delivery_error = None
            except SmtpError as exc:
                self.delivery_ok = False
                self.last_delivery_error = str(exc)
                logger.error("SMTP delivery failed: %s", exc)
            except Exception as exc:  # noqa: BLE001 — isolate sensor loop
                self.delivery_ok = False
                self.last_delivery_error = "SMTP delivery failed"
                logger.error("SMTP delivery failed: %s", exc)

    def observe(
        self,
        sample: Measurement | None,
        system: SystemMetrics,
        sensor_status: SensorStatus,
        age_seconds: float | None,
    ) -> None:
        try:
            self._observe(sample, system, sensor_status, age_seconds)
        except Exception:
            logger.exception("notification engine failed; measurement loop continues")

    def snapshot_alarms(self) -> dict[str, dict[str, Any]]:
        payload = {}
        for name, alarm in self._states.items():
            payload[name] = {
                "state": alarm.state.value,
                "value": alarm.last_value,
                "since": alarm.since,
                "unit": METRIC_UNITS.get(name, ""),
            }
        return payload

    def overall_state(self) -> AlarmState:
        if not self._states:
            return AlarmState.UNKNOWN
        worst = AlarmState.NORMAL
        seen_known = False
        for alarm in self._states.values():
            if alarm.state == AlarmState.UNKNOWN:
                continue
            seen_known = True
            if alarm.state.rank > worst.rank:
                worst = alarm.state
        return worst if seen_known else AlarmState.UNKNOWN

    def enqueue_test_email(self) -> None:
        self._enqueue(self._test_message())

    def send_test_now(self) -> None:
        """Send a TEST message on this thread so the Settings UI can wait."""
        message = self._test_message()
        try:
            self._send(message, self.config)
        except SmtpError as exc:
            self.delivery_ok = False
            self.last_delivery_error = str(exc)
            raise
        except Exception as exc:  # noqa: BLE001
            self.delivery_ok = False
            self.last_delivery_error = "SMTP delivery failed"
            logger.error("SMTP delivery failed: %s", exc)
            raise SmtpError("SMTP delivery failed") from None
        self.delivery_ok = True
        self.last_delivery_error = None

    def _test_message(self) -> OutboundEmail:
        locale = self.config.web.locale
        return OutboundEmail(
            kind="TEST",
            metric="test",
            subject=t(locale, "subject.test"),
            body=self._format_test_body(locale),
            recipients=list(self.config.notifications.email.to),
            from_address=self.config.notifications.email.from_address,
        )

    def _observe(
        self,
        sample: Measurement | None,
        system: SystemMetrics,
        sensor_status: SensorStatus,
        age_seconds: float | None,
    ) -> None:
        now = self._time()
        thresholds: NotificationThresholds = self.config.notifications.thresholds
        for name in METRIC_GETTERS:
            spec: MetricThreshold = getattr(thresholds, name)
            value = _metric_value(name, sample, system)
            self._tick(name, spec, value, now)
        self._tick_sensor_unavailable(thresholds.sensor_unavailable, sensor_status, age_seconds, now)

    def _tick_sensor_unavailable(
        self,
        spec: MetricThreshold,
        sensor_status: SensorStatus,
        age_seconds: float | None,
        now: float,
    ) -> None:
        if sensor_status == SensorStatus.OK and age_seconds is not None:
            value = age_seconds
        elif sensor_status in {SensorStatus.UNAVAILABLE, SensorStatus.ERROR}:
            value = spec.critical_high if spec.critical_high is not None else 1e9
        elif age_seconds is None:
            value = spec.critical_high if spec.critical_high is not None else 1e9
        else:
            value = age_seconds
        self._tick("sensor_unavailable", spec, value, now)

    def _tick(self, name: str, spec: MetricThreshold, value: float | None, now: float) -> None:
        alarm = self._states.setdefault(name, MetricAlarm(since=now))
        alarm.last_value = value
        if not spec.enabled:
            alarm.state = AlarmState.NORMAL
            alarm.pending = None
            return
        desired = raw_level(value, spec, alarm.state)
        if desired == alarm.state:
            alarm.pending = None
            self._maybe_repeat(name, spec, alarm, now)
            return
        if alarm.pending != desired:
            alarm.pending = desired
            alarm.pending_since = now
        elapsed = now - alarm.pending_since
        if elapsed < spec.min_duration_seconds:
            return
        previous = alarm.state
        alarm.state = desired
        alarm.since = now
        alarm.pending = None
        self._maybe_email(name, spec, alarm, previous, now)

    def _maybe_email(
        self,
        name: str,
        spec: MetricThreshold,
        alarm: MetricAlarm,
        previous: AlarmState,
        now: float,
    ) -> None:
        notify = self.config.notifications
        if not notify.enabled or not notify.email.enabled:
            return
        if alarm.state in {AlarmState.WARNING, AlarmState.CRITICAL}:
            upgraded = previous.rank < alarm.state.rank
            cooled = alarm.last_email_at is None or (now - alarm.last_email_at) >= notify.email.cooldown_seconds
            first = alarm.last_email_state not in {AlarmState.WARNING, AlarmState.CRITICAL}
            if first or upgraded or cooled:
                self._send_alert(name, spec, alarm, previous, now)
                return
        if (
            alarm.state == AlarmState.NORMAL
            and notify.email.notify_recovery
            and previous in {AlarmState.WARNING, AlarmState.CRITICAL}
            and alarm.last_email_state in {AlarmState.WARNING, AlarmState.CRITICAL}
        ):
            self._send_alert(name, spec, alarm, previous, now)

    def _maybe_repeat(self, name: str, spec: MetricThreshold, alarm: MetricAlarm, now: float) -> None:
        notify = self.config.notifications
        if not notify.enabled or not notify.email.enabled:
            return
        if alarm.state not in {AlarmState.WARNING, AlarmState.CRITICAL}:
            return
        if alarm.last_email_at is None:
            return
        if (now - alarm.last_email_at) < notify.email.cooldown_seconds:
            return
        self._send_alert(name, spec, alarm, alarm.state, now)

    def _send_alert(
        self,
        name: str,
        spec: MetricThreshold,
        alarm: MetricAlarm,
        previous: AlarmState,
        now: float,
    ) -> None:
        locale = self.config.web.locale
        kind = "RECOVERY" if alarm.state == AlarmState.NORMAL else alarm.state.value
        subject_metric = t(locale, "metric.air_quality") if name in AIR_QUALITY_METRICS else t(locale, f"metric.{name}")
        subject_key = {
            "WARNING": "subject.warning",
            "CRITICAL": "subject.critical",
            "RECOVERY": "subject.recovery",
        }[kind]
        body = self._format_alert_body(locale, name, spec, alarm, previous, now, kind)
        self._enqueue(
            OutboundEmail(
                kind=kind,
                metric=name,
                subject=t(locale, subject_key, metric=subject_metric),
                body=body,
                recipients=list(self.config.notifications.email.to),
                from_address=self.config.notifications.email.from_address,
            )
        )
        alarm.last_email_state = alarm.state
        alarm.last_email_at = now

    def _format_alert_body(
        self,
        locale: str,
        name: str,
        spec: MetricThreshold,
        alarm: MetricAlarm,
        previous: AlarmState,
        now: float,
        kind: str,
    ) -> str:
        unit = METRIC_UNITS.get(name, "")
        value_txt = "n/a" if alarm.last_value is None else f"{alarm.last_value} {unit}".strip()
        duration = max(0, int(now - alarm.since)) if kind != "RECOVERY" else max(0, int(spec.min_duration_seconds))
        reason = "body.reason.recovery" if kind == "RECOVERY" else "body.reason.sensor" if name == "sensor_unavailable" else "body.reason.high"
        note = "body.note.air" if name in AIR_QUALITY_METRICS else "body.note.generic"
        lines = [
            t(locale, "body.header"),
            "",
            f"{t(locale, 'body.host')}:",
            socket.gethostname(),
            "",
            f"{t(locale, 'body.status')}:",
            kind,
            "",
            f"{t(locale, 'body.metric')}:",
            t(locale, f"metric.{name}"),
            "",
            f"{t(locale, 'body.value')}:",
            value_txt,
            "",
            f"{t(locale, 'body.warning_threshold')}:",
            _fmt_bounds(spec.warning_high, spec.warning_low, unit),
            "",
            f"{t(locale, 'body.critical_threshold')}:",
            _fmt_bounds(spec.critical_high, spec.critical_low, unit),
            "",
            f"{t(locale, 'body.previous')}:",
            previous.value,
            "",
            f"{t(locale, 'body.duration')}:",
            t(locale, "duration.seconds", n=duration),
            "",
            f"{t(locale, 'body.time')}:",
            format_event_time(now, locale),
            "",
            f"{t(locale, 'body.web')}:",
            self._web_url(),
            "",
            t(locale, reason),
            t(locale, note),
        ]
        return "\n".join(lines) + "\n"

    def _format_test_body(self, locale: str) -> str:
        return "\n".join(
            [
                t(locale, "body.test_header"),
                "",
                f"{t(locale, 'body.host')}:",
                socket.gethostname(),
                "",
                f"{t(locale, 'body.web')}:",
                self._web_url(),
                "",
                t(locale, "body.test"),
            ]
        ) + "\n"

    def _web_url(self) -> str:
        configured = self.config.notifications.email.web_url.strip()
        if configured:
            return configured
        host = self.config.web.host
        if host in {"0.0.0.0", "::", ""}:
            host = socket.gethostname()
        return f"http://{host}:{self.config.web.port}"

    def _enqueue(self, message: OutboundEmail) -> None:
        if self._queue is None:
            try:
                self._send(message, self.config)
                self.delivery_ok = True
                self.last_delivery_error = None
            except Exception as exc:
                self.delivery_ok = False
                self.last_delivery_error = str(exc)
                logger.error("SMTP delivery failed: %s", exc)
            return
        if self._queue.full():
            try:
                dropped = self._queue.get_nowait()
                if dropped is not None:
                    logger.warning("email queue full; dropped oldest message")
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("email queue full; dropping message")


def _metric_value(name: str, sample: Measurement | None, system: SystemMetrics) -> float | None:
    source, attr = METRIC_GETTERS[name]
    if source == "sample":
        if sample is None:
            return None
        if attr == "eco2":
            return sample.co2_equivalent
        if attr == "bvoc":
            return sample.breath_voc_equivalent
        return getattr(sample, attr)
    return getattr(system, attr)


def _fmt_bounds(high: float | None, low: float | None, unit: str) -> str:
    parts = []
    if high is not None:
        parts.append(f">= {high} {unit}".strip())
    if low is not None:
        parts.append(f"<= {low} {unit}".strip())
    return ", ".join(parts) if parts else "n/a"
