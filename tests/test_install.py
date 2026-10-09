"""Installer venv/rsync idempotency and YAML-vs-SQLite API auth probe."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from server_meter.config import DEFAULT_PASSWORD_PLACEHOLDER
from server_meter.users import UserStore

ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = ROOT / "install.sh"
PROBE = ROOT / "scripts" / "install_auth_probe.py"


def _bash(script: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    merged["INSTALL_SH_SOURCE_ONLY"] = "1"
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(ROOT),
        env=merged,
        text=True,
        capture_output=True,
        check=False,
    )


def _source_prefix() -> str:
    return f'source "{INSTALL_SH}"'


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync is required for tree sync")
def test_rsync_does_not_delete_bsec_lib(tmp_path):
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    (src / "server_meter").mkdir(parents=True)
    (src / "server_meter" / "app.py").write_text("ok\n", encoding="utf-8")
    (src / "web").mkdir()
    (dest / "lib").mkdir(parents=True)
    secret = dest / "lib" / "libalgobsec.so"
    secret.write_bytes(b"bsec-artifact")
    leftover = dest / "obsolete.txt"
    leftover.write_text("gone\n", encoding="utf-8")
    (dest / "venv" / "bin").mkdir(parents=True)
    (dest / "venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")

    script = f"""
{_source_prefix()}
SRC_DIR="{src}"
PREFIX="{dest}"
sync_tree
"""
    result = _bash(script)
    assert result.returncode == 0, result.stderr + result.stdout
    combined = result.stderr + result.stdout
    assert "cannot delete non-empty directory" not in combined
    assert secret.read_bytes() == b"bsec-artifact"
    assert (dest / "server_meter" / "app.py").read_text(encoding="utf-8") == "ok\n"
    assert not leftover.exists()
    assert (dest / "venv" / "bin" / "python").is_file()


def test_venv_path_safety_rejects_system_dirs():
    script = f"""
{_source_prefix()}
PREFIX=/usr
venv_path_is_safe /usr/venv
"""
    result = _bash(script)
    assert result.returncode == 1

    script = f"""
{_source_prefix()}
PREFIX=/usr/lib
venv_path_is_safe /usr/lib/venv
"""
    result = _bash(script)
    assert result.returncode == 1


def _venv_works() -> bool:
    probe = subprocess.run(
        ["python3", "-c", "import ensurepip, venv"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


@pytest.mark.skipif(not _venv_works(), reason="python3-venv/ensurepip is not available")
def test_ensure_venv_recreates_broken_venv_only_under_prefix(tmp_path):
    prefix = tmp_path / "opt-server-meter"
    venv_dir = prefix / "venv"
    venv_dir.mkdir(parents=True)
    (venv_dir / "stale").write_text("nope\n", encoding="utf-8")
    script = f"""
{_source_prefix()}
PREFIX="{prefix}"
ensure_venv
test -x "{venv_dir}/bin/python"
test -f "{venv_dir}/pyvenv.cfg"
"""
    result = _bash(script)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (venv_dir / "bin" / "python").exists()
    assert not (venv_dir / "stale").exists()


@pytest.mark.skipif(not _venv_works(), reason="python3-venv/ensurepip is not available")
def test_ensure_venv_upgrades_existing_without_deleting_site_packages(tmp_path):
    prefix = tmp_path / "opt-server-meter"
    script = f"""
{_source_prefix()}
PREFIX="{prefix}"
python3 -m venv "{prefix}/venv"
site="$("{prefix}/venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')"
mkdir -p "$site/keepme"
echo kept > "$site/keepme/marker"
ensure_venv
test -f "$site/keepme/marker"
"""
    result = _bash(script)
    assert result.returncode == 0, result.stderr + result.stdout
    markers = list((prefix / "venv").glob("**/keepme/marker"))
    assert markers
    assert markers[0].read_text(encoding="utf-8").strip() == "kept"


def _write_config(path: Path, password: str, users_db: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "application:",
                "  environment: development",
                "web:",
                "  host: 127.0.0.1",
                "  port: 8080",
                "  users_db: "
                + json.dumps(str(users_db)),
                "  auth:",
                '    enabled: true',
                '    username: "admin"',
                f'    password: "{password}"',
                "sensor:",
                "  driver: mock",
                "  i2c:",
                "    bus: 1",
                "    address: 0x77",
                "  bsec:",
                "    enabled: false",
                "    persist_state: false",
                "history:",
                "  max_samples: 8",
                "  max_age_seconds: 60",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _probe(config: Path) -> tuple[int, dict]:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [sys.executable, str(PROBE), "--config", str(config)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    payload = json.loads(result.stdout)
    return result.returncode, payload


def test_auth_probe_yaml_match_and_mismatch(tmp_path):
    db = tmp_path / "users.db"
    cfg = tmp_path / "config.yaml"
    store = UserStore(str(db), test=True)
    try:
        store.create("admin", "secret123", "admin")
    finally:
        store.close()
    _write_config(cfg, "secret123", db)
    code, payload = _probe(cfg)
    assert code == 0
    assert payload["yaml_credentials_match"] is True
    assert payload["enabled_admin_count"] == 1
    assert payload["factory_password_active"] is False
    assert "secret123" not in json.dumps(payload)
    assert "password_hash" not in json.dumps(payload)

    _write_config(cfg, DEFAULT_PASSWORD_PLACEHOLDER, db)
    code, payload = _probe(cfg)
    assert code == 0
    assert payload["yaml_credentials_match"] is False
    assert payload["reason"] == "yaml_mismatch"
    assert payload["enabled_admin_count"] == 1
    assert DEFAULT_PASSWORD_PLACEHOLDER not in json.dumps(payload)


def test_auth_probe_missing_admin(tmp_path):
    db = tmp_path / "users.db"
    cfg = tmp_path / "config.yaml"
    store = UserStore(str(db), test=True)
    try:
        store.create("jan", "userpass1", "user")
    finally:
        store.close()
    _write_config(cfg, "userpass1", db)
    code, payload = _probe(cfg)
    assert code == 1
    assert payload["reason"] == "no_enabled_admin"
    assert payload["yaml_credentials_match"] is False


def test_auth_probe_missing_db(tmp_path):
    cfg = tmp_path / "config.yaml"
    db = tmp_path / "missing.db"
    _write_config(cfg, "secret123", db)
    code, payload = _probe(cfg)
    assert code == 1
    assert payload["reason"] == "users_db_missing"


def test_install_sh_does_not_treat_yaml_as_live_password():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "install_auth_probe.py" in text
    assert "yaml_credentials_match" in text
    assert "Basic Auth or API error" not in text
    assert "--exclude '/lib/'" in text
    assert "--filter 'P /lib/'" in text
    assert "python3 -m venv --upgrade" in text
    assert "venv_path_is_safe" in text
    assert "INSTALL_SH_SOURCE_ONLY" in text
    assert "Credentials are not printed" in text
    # Credentialed /api/current only after SQLite confirms the YAML seed.
    assert "INSTALL_YAML_CREDENTIALS_MATCH" in text
    assert text.count('write_netrc') >= 2


def test_install_sh_does_not_print_authorization_headers():
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert "Authorization:" not in text
    assert "curl -v" not in text
    assert "--netrc-file" in text
    assert "redact_api_body" in text


def test_probe_script_is_secret_free():
    text = PROBE.read_text(encoding="utf-8")
    assert "print(password" not in text
    assert "password_hash" not in text
    assert "Never prints passwords" in text or "never prints passwords" in text.lower()


def test_new_install_seed_still_matches_factory_hash(tmp_path):
    db = tmp_path / "users.db"
    cfg = tmp_path / "config.yaml"
    store = UserStore(str(db), test=True)
    try:
        store.create("admin", DEFAULT_PASSWORD_PLACEHOLDER, "admin")
    finally:
        store.close()
    _write_config(cfg, DEFAULT_PASSWORD_PLACEHOLDER, db)
    code, payload = _probe(cfg)
    assert code == 0
    assert payload["yaml_credentials_match"] is True
    assert payload["factory_password_active"] is True


def test_reinstall_does_not_rewrite_sqlite(tmp_path):
    db = tmp_path / "users.db"
    store = UserStore(str(db), test=True)
    try:
        user = store.create("admin", "already-set", "admin")
        digest = user.password_hash
    finally:
        store.close()
    before = db.read_bytes()
    cfg = tmp_path / "config.yaml"
    _write_config(cfg, DEFAULT_PASSWORD_PLACEHOLDER, db)
    _probe(cfg)
    after = db.read_bytes()
    store = UserStore(str(db), test=True)
    try:
        record = store.get_by_username("admin")
        assert record is not None
        assert record.password_hash == digest
        assert store.authenticate("admin", "already-set") is not None
        assert store.authenticate("admin", DEFAULT_PASSWORD_PLACEHOLDER) is None
    finally:
        store.close()
    assert before == after or record.password_hash == digest


def test_install_sh_is_executable():
    mode = INSTALL_SH.stat().st_mode
    assert mode & stat.S_IXUSR
