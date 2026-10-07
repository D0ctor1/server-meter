#!/usr/bin/env python3
"""Hardware probe for install.sh. Never writes sensor samples to disk.

Chip-ID scan uses i2cget (i2c-tools), not smbus2.SMBus.open().
Python 3.14 + smbus2 ioctl I2C_FUNCS raises SystemError: buffer overflow
on Raspberry Pi 5 / aarch64.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

BME690_CHIP_ID = 0x61
CHIP_ID_REG = 0xD0
CANDIDATE_ADDRS = (0x76, 0x77)


def _i2cget(bus_num: int, address: int) -> int | None:
    for extra in ([], ["-f"]):
        try:
            proc = subprocess.run(
                ["i2cget", "-y", *extra, str(bus_num), hex(address), hex(CHIP_ID_REG), "b"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return None
        if proc.returncode != 0:
            continue
        text = (proc.stdout or "").strip().lower()
        try:
            return int(text, 0)
        except ValueError:
            continue
    return None


def scan(buses: list[int]) -> list[dict[str, int]]:
    found: list[dict[str, int]] = []
    for bus in buses:
        if not os.path.exists(f"/dev/i2c-{bus}"):
            continue
        for addr in CANDIDATE_ADDRS:
            try:
                chip = _i2cget(bus, addr)
            except Exception:
                chip = None
            if chip == BME690_CHIP_ID:
                found.append({"bus": bus, "address": addr, "chip_id": chip})
    return found


def measure(bus: int, address: int) -> dict:
    from server_meter.config import AppConfig
    from server_meter.sensor.bme690 import Bme690Driver

    cfg = AppConfig.model_validate(
        {
            "application": {"environment": "test"},
            "sensor": {
                "type": "BME690",
                "driver": "bme690",
                "i2c": {"bus": bus, "address": address},
                "interval_seconds": 5,
                "bsec": {"enabled": True, "persist_state": False},
            },
        }
    )
    driver = Bme690Driver(cfg.sensor)
    try:
        driver.open()
        sample = driver.read()
        info = driver.describe()
    finally:
        driver.close()
    return {
        "ok": sample.temperature is not None,
        "chip_id": "0x61",
        "bus": bus,
        "address": hex(address),
        "temperature": sample.temperature,
        "humidity": sample.humidity,
        "pressure": sample.pressure,
        "gas_resistance": sample.gas_resistance,
        "bsec_loaded": bool(info.get("bsec_loaded")),
        "bsec_version": info.get("bsec_version"),
        "iaq": sample.iaq,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe BME690 on I²C")
    parser.add_argument("--scan", action="store_true")
    parser.add_argument("--bus", type=int, default=1)
    parser.add_argument("--address", default="")
    parser.add_argument("--buses", default="1,0,2")
    args = parser.parse_args()

    try:
        if args.scan:
            buses = [int(x) for x in args.buses.split(",") if x.strip() != ""]
            hits = scan(buses)
            json.dump({"found": hits}, sys.stdout)
            sys.stdout.write("\n")
            return 0 if hits else 2

        address = int(str(args.address).strip().lower(), 0) if args.address else 0x77
        payload = measure(args.bus, address)
    except Exception as exc:
        json.dump({"ok": False, "found": [], "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
