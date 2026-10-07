from __future__ import annotations

import os
from types import SimpleNamespace

from server_meter.sensor.i2c_bus import I2CBus, open_smbus


def test_open_smbus_skips_smbus_open(monkeypatch):
    created = {}

    class DummySMBus:
        def __init__(self, bus=None, force=False):
            assert bus is None
            self.fd = None
            self.funcs = 0
            created["init"] = True

        def open(self, bus):
            raise SystemError("buffer overflow")

    dummy_mod = SimpleNamespace(SMBus=DummySMBus, i2c_msg=object)
    monkeypatch.setitem(__import__("sys").modules, "smbus2", dummy_mod)
    monkeypatch.setattr(os.path, "exists", lambda path: path == "/dev/i2c-1")
    monkeypatch.setattr(os, "open", lambda path, flags: 42)

    handle = open_smbus(1)
    assert created["init"] is True
    assert handle.fd == 42
    assert handle.funcs == 0xFFFFFFFF


def test_i2c_bus_missing_device(monkeypatch):
    monkeypatch.setattr(os.path, "exists", lambda path: False)
    bus = I2CBus(1, 0x76)
    try:
        bus.open()
        raise AssertionError("expected unavailable")
    except Exception as exc:
        assert "not available" in str(exc)
