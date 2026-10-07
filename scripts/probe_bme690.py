#!/usr/bin/env python3
"""Hardware probe for install.sh. Never writes sensor samples to disk."""

from __future__ import annotations

import argparse
import json
import sys

BME690_CHIP_ID = 0x61
CANDIDATE_ADDRS = (0x76, 0x77)


def _chip_id(bus_num: int, address: int) -> int | None:
    try:
        from smbus2 import SMBus
    except ImportError:
        return None
    try:
        with SMBus(bus_num) as bus:
            return int(bus.read_byte_data(address, 0xD0))
    except OSError:
        return None


def scan(buses: list[int]) -> list[dict[str, int]]:
    found: list[dict[str, int]] = []
    for bus in buses:
        for addr in CANDIDATE_ADDRS:
            chip = _chip_id(bus, addr)
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

    if args.scan:
        buses = [int(x) for x in args.buses.split(",") if x.strip() != ""]
        hits = scan(buses)
        json.dump({"found": hits}, sys.stdout)
        sys.stdout.write("\n")
        return 0 if hits else 2

    address = int(str(args.address).strip().lower(), 0) if args.address else 0x77
    try:
        payload = measure(args.bus, address)
    except Exception as exc:
        json.dump({"ok": False, "error": str(exc)}, sys.stdout)
        sys.stdout.write("\n")
        return 1
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
