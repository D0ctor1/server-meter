"""Atomic YAML updates for notification settings. Never writes sensor history."""

from __future__ import annotations

import fcntl
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import yaml

from server_meter.config import AppConfig, ConfigError, _parse_yaml

logger = logging.getLogger("server_meter.config_io")


@contextmanager
def config_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(path.name + ".lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o660)
    try:
        os.chmod(lock_path, 0o660)
    except OSError:
        pass
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def dump_config_dict(config: AppConfig) -> dict[str, Any]:
    data = config.model_dump(by_alias=True)
    address = data.get("sensor", {}).get("i2c", {}).get("address")
    if isinstance(address, int):
        data["sensor"]["i2c"]["address"] = hex(address)
    return data


def atomic_write_yaml(path: Path, data: dict[str, Any], *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = mode
    previous_stat = None
    if path.exists():
        previous_stat = path.stat()
        previous_mode = previous_stat.st_mode & 0o777
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, previous_mode or 0o660)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(str(tmp), str(path))
    if previous_mode is not None:
        os.chmod(path, previous_mode)
    if previous_stat is not None:
        try:
            os.chown(path, previous_stat.st_uid, previous_stat.st_gid)
        except PermissionError:
            pass


def save_notifications(config: AppConfig) -> Path:
    path = config._source_path
    if path is None:
        raise ConfigError("Configuration path is unknown; cannot persist settings")
    with config_lock(path):
        current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(current, dict):
            raise ConfigError("Configuration root must be a mapping")
        dumped = dump_config_dict(config)
        current["notifications"] = dumped["notifications"]
        if isinstance(current.get("sensor", {}).get("i2c", {}).get("address"), int):
            current["sensor"]["i2c"]["address"] = hex(current["sensor"]["i2c"]["address"])
        atomic_write_yaml(path, current)
    logger.info("Notification configuration changed")
    return path


def reload_from_disk(config: AppConfig) -> AppConfig:
    path = config._source_path
    if path is None:
        return config
    with config_lock(path):
        loaded = _parse_yaml(path)
    loaded._source_path = path
    return loaded
