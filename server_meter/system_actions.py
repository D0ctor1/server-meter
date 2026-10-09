"""Hardcoded systemd helper starts for admin restart/reboot.

The application never interpolates user input into a shell. The only allowed
operations are `systemctl start` of two oneshot helper units installed next to
server-meter.service and gated by polkit.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Final

logger = logging.getLogger("server_meter.system_actions")

SYSTEMCTL_CANDIDATES: Final[tuple[str, ...]] = (
    "/usr/bin/systemctl",
    "/bin/systemctl",
)

RESTART_SERVICE_UNIT = "server-meter-self-restart.service"
REBOOT_HOST_UNIT = "server-meter-host-reboot.service"

CONFIRM_RESTART_SERVICE = "restart-service"
CONFIRM_REBOOT_HOST = "reboot-host"

ALLOWED_UNITS: Final[dict[str, str]] = {
    CONFIRM_RESTART_SERVICE: RESTART_SERVICE_UNIT,
    CONFIRM_REBOOT_HOST: REBOOT_HOST_UNIT,
}


def systemctl_bin() -> str:
    for candidate in SYSTEMCTL_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return SYSTEMCTL_CANDIDATES[0]


def command_for(action: str) -> list[str]:
    unit = ALLOWED_UNITS.get(action)
    if unit is None:
        raise ValueError("unknown system action")
    return [systemctl_bin(), "start", unit]


def _run_systemctl(unit: str) -> None:
    import subprocess

    if unit not in ALLOWED_UNITS.values():
        raise ValueError("unknown helper unit")
    argv = [systemctl_bin(), "start", unit]
    logger.info("starting helper unit %s", unit)
    subprocess.run(
        argv,
        check=True,
        timeout=20,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
    )


class UnknownSystemAction(ValueError):
    pass


class SystemActions:
    def __init__(self, runner: Callable[[str], None] | None = None) -> None:
        self._runner = runner if runner is not None else _run_systemctl
        self.started: list[str] = []

    def start(self, action: str) -> str:
        unit = ALLOWED_UNITS.get(action)
        if unit is None:
            raise UnknownSystemAction("unknown system action")
        self._runner(unit)
        self.started.append(unit)
        return unit
