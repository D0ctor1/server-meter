from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

_SPEC = importlib.util.spec_from_file_location(
    "probe_bme690",
    Path(__file__).resolve().parent.parent / "scripts" / "probe_bme690.py",
)
probe = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(probe)


def test_i2cget_parses_chip_id(monkeypatch):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout="0x61\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert probe._i2cget(1, 0x76) == 0x61


def test_scan_skips_missing_bus(monkeypatch):
    monkeypatch.setattr(probe.os.path, "exists", lambda path: False)
    assert probe.scan([1, 0, 2]) == []


def test_scan_finds_chip(monkeypatch):
    monkeypatch.setattr(probe.os.path, "exists", lambda path: path.endswith("-1"))
    monkeypatch.setattr(probe, "_i2cget", lambda bus, addr: 0x61 if addr == 0x76 else None)
    hits = probe.scan([1])
    assert hits == [{"bus": 1, "address": 0x76, "chip_id": 0x61}]
