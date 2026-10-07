"""Evaluate a metric against thresholds with hysteresis. No I/O."""

from __future__ import annotations

from server_meter.config import MetricThreshold
from server_meter.notification.models import AlarmState


def raw_level(value: float | None, spec: MetricThreshold, current: AlarmState) -> AlarmState:
    if value is None:
        return AlarmState.UNKNOWN
    if current == AlarmState.CRITICAL:
        if _still_critical(value, spec):
            return AlarmState.CRITICAL
        if _still_warning(value, spec, leaving_critical=True):
            return AlarmState.WARNING
        return AlarmState.NORMAL
    if current == AlarmState.WARNING:
        if _is_critical(value, spec):
            return AlarmState.CRITICAL
        if _still_warning(value, spec, leaving_critical=False):
            return AlarmState.WARNING
        return AlarmState.NORMAL
    if _is_critical(value, spec):
        return AlarmState.CRITICAL
    if _is_warning(value, spec):
        return AlarmState.WARNING
    return AlarmState.NORMAL


def _is_critical(value: float, spec: MetricThreshold) -> bool:
    if spec.critical_high is not None and value >= spec.critical_high:
        return True
    if spec.critical_low is not None and value <= spec.critical_low:
        return True
    return False


def _is_warning(value: float, spec: MetricThreshold) -> bool:
    if spec.warning_high is not None and value >= spec.warning_high:
        return True
    if spec.warning_low is not None and value <= spec.warning_low:
        return True
    return False


def _still_critical(value: float, spec: MetricThreshold) -> bool:
    clear_high = spec.clear_high("critical")
    clear_low = spec.clear_low("critical")
    if clear_high is not None and spec.critical_high is not None and value >= clear_high:
        return True
    if clear_low is not None and spec.critical_low is not None and value <= clear_low:
        return True
    if spec.critical_high is None and spec.critical_low is None:
        return False
    # If only one side exists, stay critical until that side clears.
    if spec.critical_high is not None and spec.critical_low is None:
        return clear_high is not None and value >= clear_high
    if spec.critical_low is not None and spec.critical_high is None:
        return clear_low is not None and value <= clear_low
    return False


def _still_warning(value: float, spec: MetricThreshold, leaving_critical: bool) -> bool:
    if _is_critical(value, spec) and not leaving_critical:
        return False
    clear_high = spec.clear_high("warning")
    clear_low = spec.clear_low("warning")
    if spec.warning_high is not None and clear_high is not None and value >= clear_high:
        return True
    if spec.warning_low is not None and clear_low is not None and value <= clear_low:
        return True
    return False
