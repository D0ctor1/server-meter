from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "write_initial_config.py"
EXAMPLE = ROOT / "config" / "config.example.yaml"


def test_write_then_preserve_password(tmp_path):
    dest = tmp_path / "config.yaml"
    subprocess.check_call(
        [
            sys.executable,
            str(SCRIPT),
            "--example",
            str(EXAMPLE),
            "--dest",
            str(dest),
            "--bus",
            "1",
            "--address",
            "0x76",
            "--bsec-lib",
            "/opt/server-meter/lib/libalgobsec.so",
            "--bsec-config",
            "/opt/server-meter/lib/bsec_iaq.config",
        ]
    )
    text = dest.read_text(encoding="utf-8")
    assert "address: 0x76" in text
    assert "password: \"CHANGE_ME\"" in text or "password: CHANGE_ME" in text
    assert 'library_path: "/opt/server-meter/lib/libalgobsec.so"' in text
    assert 'config_blob_path: "/opt/server-meter/lib/bsec_iaq.config"' in text
    dest.write_text(text.replace("CHANGE_ME", "MySecret9"), encoding="utf-8")
    subprocess.check_call(
        [
            sys.executable,
            str(SCRIPT),
            "--example",
            str(EXAMPLE),
            "--dest",
            str(dest),
            "--bus",
            "1",
            "--address",
            "0x77",
        ]
    )
    updated = dest.read_text(encoding="utf-8")
    assert "MySecret9" in updated
    assert "CHANGE_ME" not in updated
    assert "address: 0x77" in updated


def test_preserve_does_not_overwrite_or_inject_locale(tmp_path):
    dest = tmp_path / "config.yaml"
    original = EXAMPLE.read_text(encoding="utf-8")
    dest.write_text(
        original.replace('locale: "CZ"', 'locale: "EN"').replace("CHANGE_ME", "KeepPass1")
        if 'locale: "CZ"' in original
        else original.replace("password: \"CHANGE_ME\"", 'password: "KeepPass1"').replace(
            "web:\n", 'web:\n  locale: "EN"\n', 1
        ),
        encoding="utf-8",
    )
    subprocess.check_call(
        [
            sys.executable,
            str(SCRIPT),
            "--example",
            str(EXAMPLE),
            "--dest",
            str(dest),
            "--bus",
            "1",
            "--address",
            "0x77",
        ]
    )
    updated = dest.read_text(encoding="utf-8")
    assert 'locale: "EN"' in updated
    assert "KeepPass1" in updated
    assert "CHANGE_ME" not in updated

    missing = tmp_path / "legacy.yaml"
    legacy = EXAMPLE.read_text(encoding="utf-8")
    legacy = "\n".join(line for line in legacy.splitlines() if "locale:" not in line)
    missing.write_text(legacy, encoding="utf-8")
    subprocess.check_call(
        [
            sys.executable,
            str(SCRIPT),
            "--example",
            str(EXAMPLE),
            "--dest",
            str(missing),
            "--bus",
            "1",
            "--address",
            "0x76",
        ]
    )
    kept = missing.read_text(encoding="utf-8")
    assert "locale:" not in kept
