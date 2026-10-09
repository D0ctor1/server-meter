from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi.testclient import TestClient

from server_meter.app import create_app
from server_meter.config import AppConfig
from server_meter.service import MeterService
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parent.parent
I18N_JS = (ROOT / "web" / "js" / "i18n.js").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "web" / "js" / "settings.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "style.css").read_text(encoding="utf-8")

HARDCODED_UI = (
    "Authentication required",
    "Reload and sign in",
    "Current values",
    "Gas resistance",
    "IAQ accuracy",
    "Static IAQ",
    "samples in RAM",
    "Default password is active",
    "no sample yet",
    "last sample",
    "Temperature",
    "Humidity",
    "Pressure",
)


def _section(name: str) -> str:
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
                return rest[:index]
    raise AssertionError(f"unclosed {name} dictionary")


def _keys(block: str) -> set[str]:
    return set(re.findall(r'"([a-z0-9_.]+)":\s*"', block))


def test_cz_and_en_dictionaries_have_the_same_keys():
    cz = _keys(_section("CZ"))
    en = _keys(_section("EN"))
    assert cz, "CZ dictionary is empty"
    assert cz == en
    for required in (
        "sensor.temperature",
        "login.title",
        "login.invalid",
        "status.warning",
        "status.critical",
        "dashboard.current_values",
        "error.load_current",
        "sensor.unavailable_message",
        "settings.title",
        "settings.test_email",
        "settings.disclaimer",
        "users.add",
        "users.last_admin",
        "users.col.last_activity",
        "users.never",
        "system.actions",
        "system.reboot_host.confirm_button",
        "settings.tab.users",
        "dashboard.system_health",
        "dashboard.alarm_history_hint",
        "health.ram_protection_active",
        "history.window_all",
        "history.empty",
        "settings.export",
        "settings.token",
        "settings.tab.alarms",
        "settings.readonly",
        "settings.save_smtp",
    ):
        assert required in cz


def test_frontend_uses_semantic_keys_not_hardcoded_ui_copy():
    for phrase in HARDCODED_UI:
        assert phrase not in APP_JS, phrase
    assert "if (locale ===" not in APP_JS
    assert "ServerMeterI18n" in APP_JS
    assert 't("sensor.temperature")' in APP_JS or 'labelKey: "sensor.temperature"' in APP_JS


def test_html_wires_i18n_attributes_and_login_form():
    assert 'src="/js/i18n.js?v=__ASSET__"' in INDEX
    assert 'data-locale="__LOCALE__"' in INDEX
    assert 'lang="__LANG__"' in INDEX
    assert 'data-i18n="login.title"' in INDEX
    assert 'data-i18n="dashboard.current_values"' in INDEX
    assert 'id="login-overlay"' in INDEX
    assert 'id="settings-button"' in INDEX
    assert 'id="settings-overlay"' in INDEX
    assert 'data-tab="users"' in INDEX
    assert 'id="user-overlay"' in INDEX
    assert 'src="/js/settings.js?v=__ASSET__"' in INDEX
    assert "language-switch" not in INDEX
    assert "lang-switch" not in INDEX


def test_used_translation_keys_exist():
    keys = _keys(_section("CZ"))
    used = set(re.findall(r'data-i18n(?:-html|-placeholder|-aria)?="([a-z0-9_.]+)"', INDEX))
    used |= set(re.findall(r'\bt\(\s*"([a-z0-9_.]+)"', APP_JS))
    used |= set(re.findall(r'\bt\(\s*"([a-z0-9_.]+)"', SETTINGS_JS))
    used |= set(re.findall(r'(?:labelKey|helpKey):\s*"([a-z0-9_.]+)"', APP_JS))
    missing = sorted(key for key in used if key not in keys)
    assert missing == []


def test_help_keys_cover_gas_iaq_and_voc_metrics():
    keys = _keys(_section("CZ"))
    for key in (
        "sensor.help.gas_resistance",
        "sensor.help.iaq",
        "sensor.help.static_iaq",
        "sensor.help.static_iaq_accuracy",
        "sensor.help.eco2",
        "sensor.help.bvoc",
        "sensor.help.tvoc",
        "help.icon_label",
        "duration.days",
        "duration.hours",
        "duration.minutes",
        "duration.seconds",
    ):
        assert key in keys
    assert "info-tip" in APP_JS
    assert "info-tip" in CSS
    assert "formatDuration" in APP_JS
    assert "formatDuration" in I18N_JS
    for metric in ("gas_resistance", "iaq", "static_iaq", "static_iaq_accuracy", "eco2", "bvoc", "tvoc"):
        assert f'helpKey: "sensor.help.{metric}"' in APP_JS


def test_duration_format_groups_seconds_hours_and_days():
    import json
    import shutil
    import subprocess

    if not shutil.which("node"):
        assert "86400" in I18N_JS
        assert "3600" in I18N_JS
        return
    script = r"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync(process.env.I18N_JS, "utf8");
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
vm.runInContext(code, context);
const i18n = context.ServerMeterI18n;
i18n.setLocale("CZ");
const cz = {
  s: i18n.formatDuration(45),
  min: i18n.formatDuration(93),
  host: i18n.formatDuration(1606),
  h: i18n.formatDuration(3661),
  d: i18n.formatDuration(90061),
};
i18n.setLocale("EN");
const en = { min: i18n.formatDuration(93), d: i18n.formatDuration(90061) };
process.stdout.write(JSON.stringify({ cz, en }));
"""
    result = subprocess.check_output(
        ["node", "-e", script],
        text=True,
        env={**os.environ, "I18N_JS": str(ROOT / "web" / "js" / "i18n.js")},
    )
    payload = json.loads(result)
    assert payload["cz"]["s"] == "45 s"
    assert payload["cz"]["min"] == "1 min 33 s"
    assert payload["cz"]["host"] == "26 min 46 s"
    assert payload["cz"]["h"] == "1 h 1 min"
    assert payload["cz"]["d"] == "1 d 1 h"
    assert payload["en"]["min"] == "1 min 33 s"
    assert payload["en"]["d"] == "1 d 1 h"


def test_chart_frame_still_used_for_history_plots():
    assert "chart-frame" in APP_JS
    assert "chart-frame" in CSS
    assert "height: 220px" in CSS


def _client_for(locale: str | None) -> TestClient:
    data = make_config().model_dump()
    if locale is None:
        data["web"].pop("locale", None)
    else:
        data["web"]["locale"] = locale
    cfg = AppConfig.model_validate(data)
    return TestClient(create_app(cfg, MeterService(cfg)))


def test_served_html_defaults_to_cz():
    with _client_for(None) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'data-locale="CZ"' in response.text
        assert 'lang="cs"' in response.text
        assert "__LOCALE__" not in response.text
        assert "__ASSET__" not in response.text
        assert "/js/i18n.js?v=" in response.text
        assert "/js/settings.js?v=" in response.text
        assert client.get("/settings").status_code == 200
        assert 'data-tab="alarms"' in client.get("/settings").text


def test_served_html_uses_en_when_configured():
    with _client_for("EN") as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'data-locale="EN"' in response.text
        assert 'lang="en"' in response.text


def test_login_form_is_public_api_stays_protected():
    with _client_for("CZ") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/js/i18n.js").status_code == 200
