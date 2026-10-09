"""Admin-only last activity (RAM) and systemd restart/reboot helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server_meter.activity import ActivityTracker, should_record
from server_meter.app import create_app
from server_meter.service import MeterService
from server_meter.system_actions import (
    ALLOWED_UNITS,
    CONFIRM_REBOOT_HOST,
    CONFIRM_RESTART_SERVICE,
    REBOOT_HOST_UNIT,
    RESTART_SERVICE_UNIT,
    SystemActions,
    UnknownSystemAction,
    command_for,
)
from server_meter.users import UserStore
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parent.parent
USERS_SQL = (ROOT / "server_meter" / "users.py").read_text(encoding="utf-8")
I18N_JS = (ROOT / "web" / "js" / "i18n.js").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "web" / "js" / "settings.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def _app(tmp_path, password="secret123"):
    cfg = make_config()
    cfg.web.auth.password = password
    cfg.web.users_db = str(tmp_path / "users.db")
    app = create_app(cfg, service=MeterService(cfg))
    return app, cfg


def _create_user(client, username="jan", role="user"):
    response = client.post(
        "/api/admin/users",
        auth=("admin", "secret123"),
        json={"username": username, "password": "userpass1", "role": role, "enabled": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_successful_login_records_activity(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        users = client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]
        admin = next(item for item in users if item["username"] == "admin")
        assert admin["last_activity_at"] is not None
        assert admin["last_activity_at"] > 0
        before = time.time() + 5
        assert admin["last_activity_at"] <= before


def test_authenticated_request_updates_timestamp(tmp_path):
    app, _cfg = _app(tmp_path)
    app.state.activity = ActivityTracker(throttle_seconds=0)
    with TestClient(app) as client:
        client.get("/api/me", auth=("admin", "secret123"))
        first = app.state.activity.get(1)
        app.state.activity = ActivityTracker(throttle_seconds=0)
        client.get("/api/status", auth=("admin", "secret123"))
        second = app.state.activity.get(1)
        assert first is not None
        assert second is not None
        assert second >= first


def test_failed_login_does_not_record_activity(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/status", auth=("admin", "wrongpass")).status_code == 401
        listed = client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]
        # The successful admin list records activity; failed login must not have
        # created a stamp beforehand. Reset and retry against a user with none.
        other = _create_user(client, "servis")
        assert app.state.activity.get(other["id"]) is None
        assert client.get("/api/status", auth=("servis", "badpass12")).status_code == 401
        assert app.state.activity.get(other["id"]) is None
        listed = client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]
        servis = next(item for item in listed if item["username"] == "servis")
        assert servis["last_activity_at"] is None


def test_anonymous_and_health_do_not_record_activity(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/css/style.css").status_code == 200
        assert app.state.activity.snapshot() == {}
        client.get("/api/me", auth=("admin", "secret123"))
        stamp = app.state.activity.get(1)
        assert stamp is not None
        app.state.activity = ActivityTracker(throttle_seconds=0)
        assert client.get("/api/health").status_code == 200
        assert app.state.activity.snapshot() == {}


def test_nagios_monitoring_does_not_record_activity(tmp_path):
    app, _cfg = _app(tmp_path)
    with TestClient(app) as client:
        token = client.post(
            "/api/admin/monitoring-token",
            auth=("admin", "secret123"),
        ).json()["token"]
        admin_id = 1
        first = app.state.activity.get(admin_id)
        app.state.activity = ActivityTracker(throttle_seconds=0)
        response = client.get("/api/monitoring", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        nagios = client.get("/api/nagios/check", auth=("admin", "secret123"))
        assert nagios.status_code == 200
        assert app.state.activity.get(admin_id) is None
        assert first is not None


def test_throttle_does_not_rewrite_every_poll(tmp_path):
    app, _cfg = _app(tmp_path)
    app.state.activity = ActivityTracker(throttle_seconds=45)
    with TestClient(app) as client:
        client.get("/api/status", auth=("admin", "secret123"))
        first = app.state.activity.get(1)
        client.get("/api/status", auth=("admin", "secret123"))
        client.get("/api/current", auth=("admin", "secret123"))
        assert app.state.activity.get(1) == first
        app.state.activity._touched_mono[1] = time.monotonic() - 60
        client.get("/api/status", auth=("admin", "secret123"))
        assert app.state.activity.get(1) != first


def test_activity_is_empty_after_new_process(tmp_path):
    app, cfg = _app(tmp_path)
    with TestClient(app) as client:
        other = _create_user(client, "servis")
        client.get("/api/status", auth=("servis", "userpass1"))
        assert app.state.activity.get(other["id"]) is not None
    app2 = create_app(cfg, service=MeterService(cfg))
    with TestClient(app2) as client:
        listed = client.get("/api/admin/users", auth=("admin", "secret123")).json()["users"]
        servis = next(item for item in listed if item["username"] == "servis")
        assert servis["last_activity_at"] is None


def test_activity_not_in_user_schema_or_me_payload(tmp_path):
    assert "last_activity" not in USERS_SQL
    app, cfg = _app(tmp_path)
    with TestClient(app) as client:
        me = client.get("/api/me", auth=("admin", "secret123")).json()
        assert "last_activity_at" not in me
        status = client.get("/api/status", auth=("admin", "secret123")).json()
        assert "last_activity_at" not in status["current_user"]
        blob = json.dumps(status)
        assert "last_activity" not in blob
    conn = sqlite3.connect(str(tmp_path / "users.db"))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    finally:
        conn.close()
    assert "last_activity_at" not in columns
    assert "last_activity" not in columns


def test_user_cannot_list_activity_or_restart(tmp_path):
    app, _cfg = _app(tmp_path)
    started: list[str] = []
    app.state.system_actions = SystemActions(runner=started.append)
    with TestClient(app) as client:
        _create_user(client)
        user = ("jan", "userpass1")
        assert client.get("/api/admin/users", auth=user).status_code == 403
        assert client.post(
            "/api/admin/restart-service",
            auth=user,
            json={"confirm": "restart-service"},
        ).status_code == 403
        assert client.post(
            "/api/admin/reboot-host",
            auth=user,
            json={"confirm": "reboot-host"},
        ).status_code == 403
        assert client.post(
            "/api/admin/restart-service",
            json={"confirm": "restart-service"},
        ).status_code == 401
        assert client.post(
            "/api/admin/reboot-host",
            json={"confirm": "reboot-host"},
        ).status_code == 401
        assert started == []


def test_demoted_or_disabled_admin_cannot_use_old_session(tmp_path):
    app, _cfg = _app(tmp_path)
    started: list[str] = []
    app.state.system_actions = SystemActions(runner=started.append)
    with TestClient(app) as client:
        other = _create_user(client, "petra", role="admin")
        first_admin = ("admin", "secret123")
        petra = ("petra", "userpass1")
        assert client.post(
            "/api/admin/restart-service",
            auth=petra,
            json={"confirm": "restart-service"},
        ).status_code == 202
        client.put(
            f"/api/admin/users/{other['id']}",
            auth=first_admin,
            json={"role": "user"},
        )
        assert client.post(
            "/api/admin/reboot-host",
            auth=petra,
            json={"confirm": "reboot-host"},
        ).status_code == 403
        client.put(
            f"/api/admin/users/{other['id']}",
            auth=first_admin,
            json={"role": "admin", "enabled": False},
        )
        assert client.post(
            "/api/admin/restart-service",
            auth=petra,
            json={"confirm": "restart-service"},
        ).status_code == 401
        assert started == [RESTART_SERVICE_UNIT]


def test_admin_restart_and_reboot_use_hardcoded_helpers(tmp_path):
    app, _cfg = _app(tmp_path)
    started: list[str] = []
    app.state.system_actions = SystemActions(runner=started.append)
    admin = ("admin", "secret123")
    with TestClient(app) as client:
        bad = client.post("/api/admin/restart-service", auth=admin, json={"confirm": "yes"})
        assert bad.status_code == 400
        inject = client.post(
            "/api/admin/restart-service",
            auth=admin,
            json={"confirm": "restart-service; reboot", "unit": "sshd.service", "cmd": "id"},
        )
        assert inject.status_code == 400
        extra = client.post(
            "/api/admin/restart-service",
            auth=admin,
            json={"confirm": "restart-service", "unit": "sshd.service", "command": "reboot"},
        )
        assert extra.status_code == 202
        assert extra.json() == {"ok": True, "accepted": True, "action": "restart-service"}
        reboot = client.post(
            "/api/admin/reboot-host",
            auth=admin,
            json={"confirm": "reboot-host"},
        )
        assert reboot.status_code == 202
        wrong = client.post(
            "/api/admin/reboot-host",
            auth=admin,
            json={"confirm": "restart-service"},
        )
        assert wrong.status_code == 400
    assert started == [RESTART_SERVICE_UNIT, REBOOT_HOST_UNIT]


def test_system_actions_reject_unknown_units():
    argv = command_for(CONFIRM_RESTART_SERVICE)
    assert argv[1:] == ["start", RESTART_SERVICE_UNIT]
    assert argv[0].endswith("systemctl")
    assert command_for(CONFIRM_REBOOT_HOST)[1:] == ["start", REBOOT_HOST_UNIT]
    with pytest.raises(ValueError):
        command_for("sshd.service")
    actions = SystemActions(runner=lambda unit: (_ for _ in ()).throw(AssertionError(unit)))
    with pytest.raises(UnknownSystemAction):
        actions.start("id; reboot")
    assert set(ALLOWED_UNITS.values()) == {RESTART_SERVICE_UNIT, REBOOT_HOST_UNIT}


def test_helper_units_and_polkit_are_minimal():
    restart = (ROOT / "systemd" / "server-meter-self-restart.service").read_text(encoding="utf-8")
    reboot = (ROOT / "systemd" / "server-meter-host-reboot.service").read_text(encoding="utf-8")
    rules = (ROOT / "systemd" / "50-server-meter.rules").read_text(encoding="utf-8")
    install = (ROOT / "install.sh").read_text(encoding="utf-8")
    uninstall = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "ExecStart=/usr/bin/systemctl restart server-meter.service" in restart
    assert "ExecStart=/usr/bin/systemctl reboot" in reboot
    assert "WantedBy=" not in restart
    assert "WantedBy=" not in reboot
    assert "server-meter-self-restart.service" in rules
    assert "server-meter-host-reboot.service" in rules
    assert 'verb !== "start"' in rules or 'verb == "start"' in rules
    assert "org.freedesktop.systemd1.manage-units" in rules
    assert "NOPASSWD: ALL" not in rules
    assert "/bin/sh" not in rules
    assert "server-meter-self-restart.service" in install
    assert "50-server-meter.rules" in install
    assert "server-meter-host-reboot.service" in uninstall
    assert "50-server-meter.rules" in uninstall
    src = (ROOT / "server_meter" / "system_actions.py").read_text(encoding="utf-8")
    assert "shell=True" not in src
    assert "sudo" not in src


def test_should_record_skips_health_and_nagios():
    assert should_record("/api/status", 1) is True
    assert should_record("/api/health", 1) is False
    assert should_record("/api/monitoring", 1) is False
    assert should_record("/api/nagios/check", 1) is False
    assert should_record("/api/status", 0) is False
    assert should_record("/api/status", -1) is False


def _i18n_block(name: str) -> dict[str, str]:
    marker = f"{name}: {{"
    start = I18N_JS.index(marker) + len(marker)
    rest = I18N_JS[start:]
    depth = 1
    for index, char in enumerate(rest):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return dict(re.findall(r'"([a-z0-9_.]+)":\s*"((?:[^"\\]|\\.)*)"', rest[:index]))
    raise AssertionError(f"unclosed {name}")


def test_i18n_activity_and_restart_copy():
    cz = _i18n_block("CZ")
    en = _i18n_block("EN")
    assert cz["users.col.last_activity"] == "Poslední aktivita"
    assert cz["users.never"] == "Nikdy"
    assert "Ano, restartovat hostitel" in cz["system.reboot_host.confirm_button"]
    assert "Raspberry Pi" in cz["system.reboot_host.confirm_detail"]
    assert "nedostupné" in cz["system.restart_service.confirm_detail"]
    assert en["users.col.last_activity"] == "Last activity"
    assert en["users.never"] == "Never"
    assert "Yes, reboot the host" in en["system.reboot_host.confirm_button"]
    assert 'data-i18n="users.col.last_activity"' in INDEX
    assert 'id="reboot-host-final-confirm"' in INDEX
    assert "reboot-host-btn" in INDEX
    assert "/api/admin/restart-service" in SETTINGS_JS
    assert "/api/admin/reboot-host" in SETTINGS_JS
    assert "openRebootHostFinal" in SETTINGS_JS
    assert "users.never" in SETTINGS_JS


def test_locale_formats_activity_timestamp():
    if not shutil.which("node"):
        assert "formatDateTimeFromTs" in I18N_JS
        return
    script = r"""
const fs = require("fs");
const vm = require("vm");
const context = {
  window: {},
  document: {
    documentElement: { dataset: { locale: "CZ" }, lang: "" },
    querySelectorAll: () => [],
    readyState: "complete",
    addEventListener() {},
    title: "",
  },
};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.env.I18N_JS, "utf8"), context);
const i18n = context.ServerMeterI18n;
const ts = Date.UTC(2026, 9, 9, 11, 15, 42) / 1000;
i18n.setLocale("CZ");
const cz = i18n.formatDateTimeFromTs(ts);
i18n.setLocale("EN");
const en = i18n.formatDateTimeFromTs(ts);
process.stdout.write(JSON.stringify({ cz, en, neverCz: i18n.t("users.never") }));
"""
    env = {**os.environ, "I18N_JS": str(ROOT / "web" / "js" / "i18n.js")}
    # The snippet above sets EN last, so re-run t() for Never after CZ.
    script = script.replace(
        'process.stdout.write(JSON.stringify({ cz, en, neverCz: i18n.t("users.never") }));',
        'i18n.setLocale("CZ"); const neverCz = i18n.t("users.never"); i18n.setLocale("EN"); const neverEn = i18n.t("users.never"); process.stdout.write(JSON.stringify({ cz, en, neverCz, neverEn }));',
    )
    payload = json.loads(subprocess.check_output(["node", "-e", script], text=True, env=env))
    assert "2026" in payload["cz"]
    assert "2026" in payload["en"]
    assert payload["neverCz"] == "Nikdy"
    assert payload["neverEn"] == "Never"
