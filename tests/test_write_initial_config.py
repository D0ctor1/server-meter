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
        ]
    )
    text = dest.read_text(encoding="utf-8")
    assert "address: 0x76" in text
    assert "password: \"CHANGE_ME\"" in text or "password: CHANGE_ME" in text
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
