from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from server_meter.app import WEB_ASSET_VERSION, create_app
from server_meter.config import AppConfig
from server_meter.service import MeterService
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "style.css").read_text(encoding="utf-8")
SETTINGS_JS = (ROOT / "web" / "js" / "settings.js").read_text(encoding="utf-8")
I18N_JS = (ROOT / "web" / "js" / "i18n.js").read_text(encoding="utf-8")

SECTION_IDS = ("general", "users", "notifications", "system", "smtp", "alarms")


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


def _i18n_map(block: str) -> dict[str, str]:
    return dict(re.findall(r'"([a-z0-9_.]+)":\s*"((?:[^"\\]|\\.)*)"', block))


def _unescape(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape") if "\\" in value else value


def test_settings_tabs_are_real_hidden_panels():
    assert 'data-tab="general"' in INDEX
    assert 'data-tab="users"' in INDEX
    assert 'data-tab="notifications"' in INDEX
    assert 'data-tab="system"' in INDEX
    assert 'data-tab="smtp"' in INDEX
    assert 'data-tab="alarms"' in INDEX
    assert 'data-tab="thresholds"' not in INDEX
    for section in SECTION_IDS:
        assert f'data-tab-panel="{section}"' in INDEX
    general = re.search(r'data-tab-panel="general"([^>]*)>', INDEX)
    assert general is not None
    assert "hidden" not in general.group(1)
    for section in SECTION_IDS:
        if section == "general":
            continue
        match = re.search(rf'data-tab-panel="{section}"([^>]*)>', INDEX)
        assert match is not None, section
        assert "hidden" in match.group(1)
    assert ".settings-section[hidden]" in CSS
    assert "display: none !important" in CSS
    assert "overflow-x: auto" in CSS


def test_settings_fields_are_not_duplicated_across_sections():
    panels = {}
    for section in SECTION_IDS:
        match = re.search(
            rf'<section[^>]*data-tab-panel="{section}"[^>]*>(.*?)</section>',
            INDEX,
            re.S,
        )
        assert match is not None, section
        panels[section] = match.group(1)
    assert 'id="smtp-host"' in panels["smtp"]
    assert 'id="smtp-password"' in panels["smtp"]
    assert 'id="settings-test"' in panels["smtp"]
    assert 'id="smtp-to"' in panels["notifications"]
    assert 'id="notify-email-enabled"' in panels["notifications"]
    assert 'id="notify-recovery"' in panels["notifications"]
    assert 'id="smtp-host"' not in panels["notifications"]
    assert 'id="smtp-to"' not in panels["smtp"]
    assert 'id="settings-test"' not in panels["notifications"]
    assert 'id="threshold-body"' in panels["alarms"]
    assert 'id="threshold-body"' not in panels["smtp"]
    assert 'id="users-body"' in panels["users"]
    assert 'id="settings-system-dl"' in panels["system"]
    assert "settings.readonly" in panels["general"]
    assert "settings.readonly" in panels["system"]


def test_centralized_section_definition_and_hashes():
    assert "SETTINGS_SECTIONS" in SETTINGS_JS
    assert "requiredRole" in SETTINGS_JS
    assert "labelKey" in SETTINGS_JS
    for section in SECTION_IDS:
        assert f'id: "{section}"' in SETTINGS_JS
        assert f"/settings#{section}" in SETTINGS_JS or f'"#{section}"' in SETTINGS_JS or f"`#${{section}}`" in SETTINGS_JS
    assert 'thresholds: "alarms"' in SETTINGS_JS or "thresholds: 'alarms'" in SETTINGS_JS
    assert "location.hash" in SETTINGS_JS
    assert "/api/admin/users" in SETTINGS_JS
    assert "/api/admin/system" in SETTINGS_JS
    assert 'currentSection !== "smtp"' in SETTINGS_JS


def test_tab_labels_are_localized():
    cz = {key: _unescape(value) for key, value in _i18n_map(_section("CZ")).items()}
    en = {key: _unescape(value) for key, value in _i18n_map(_section("EN")).items()}
    assert cz["settings.tab.general"] == "Obecné"
    assert cz["settings.tab.users"] == "Uživatelé"
    assert cz["settings.tab.notifications"] == "Notifikace"
    assert cz["settings.tab.system"] == "Systém"
    assert cz["settings.tab.smtp"] == "SMTP"
    assert cz["settings.tab.alarms"] == "Alarmy"
    assert en["settings.tab.general"] == "General"
    assert en["settings.tab.users"] == "Users"
    assert en["settings.tab.notifications"] == "Notifications"
    assert en["settings.tab.system"] == "System"
    assert en["settings.tab.smtp"] == "SMTP"
    assert en["settings.tab.alarms"] == "Alarms"
    assert cz["settings.readonly"] == "Pouze ke čtení"
    assert en["settings.readonly"] == "Read-only"
    assert cz["settings.saved"].startswith("✓")
    assert en["settings.saved"].startswith("✓")
    assert cz["settings.save_failed"].startswith("✗")
    assert en["settings.save_failed"].startswith("✗")


def _client() -> TestClient:
    cfg = make_config()
    return TestClient(create_app(cfg, MeterService(cfg)))


def test_settings_page_serves_the_same_ui_as_index():
    with _client() as client:
        home = client.get("/")
        settings = client.get("/settings")
        assert home.status_code == 200
        assert settings.status_code == 200
        assert home.text == settings.text
        assert "__ASSET__" not in settings.text
        assert f"/js/settings.js?v={WEB_ASSET_VERSION}" in settings.text
        assert 'data-tab="alarms"' in settings.text


def test_user_cannot_read_settings_apis(tmp_path):
    data = make_config().model_dump()
    data["web"]["users_db"] = str(tmp_path / "users.db")
    cfg = AppConfig.model_validate(data)
    app = create_app(cfg, MeterService(cfg))
    with TestClient(app) as client:
        admin = ("admin", "secret123")
        created = client.post(
            "/api/admin/users",
            auth=admin,
            json={"username": "jan", "password": "userpass1", "role": "user", "enabled": True},
        )
        assert created.status_code == 200, created.text
        user = ("jan", "userpass1")
        assert client.get("/settings").status_code == 200
        assert client.get("/api/settings", auth=user).status_code == 403
        assert client.get("/api/admin/users", auth=user).status_code == 403
        assert client.get("/api/admin/system", auth=user).status_code == 403
        assert client.post("/api/settings/test-email", auth=user).status_code == 403
        assert client.get("/api/settings").status_code == 401


def test_settings_get_does_not_return_smtp_password(auth, client):
    payload = client.get("/api/settings", auth=auth).json()
    smtp = payload["email"]["smtp"]
    assert "password" not in smtp
    assert "password_set" in smtp


def test_tab_switching_hash_lazy_load_and_refresh():
    if not shutil.which("node"):
        assert "SETTINGS_SECTIONS" in SETTINGS_JS
        assert "canonicalSection" in SETTINGS_JS
        return
    script = r"""
const fs = require("fs");
const vm = require("vm");
const { EventEmitter } = require("events");

function el(id, extra) {
  const node = {
    id: id || "",
    hidden: !!(extra && extra.hidden),
    className: (extra && extra.className) || "",
    textContent: "",
    innerHTML: "",
    value: "",
    checked: false,
    children: [],
    dataset: Object.assign({}, extra && extra.dataset),
    attributes: {},
    listeners: {},
    style: {},
    parent: extra && extra.parent,
    tagName: (extra && extra.tagName) || "DIV",
    addEventListener(name, fn) {
      (this.listeners[name] || (this.listeners[name] = [])).push(fn);
    },
    appendChild(child) {
      this.children.push(child);
      child.parent = this;
      return child;
    },
    append(...nodes) { nodes.forEach((n) => this.appendChild(n)); },
    querySelectorAll(sel) {
      if (sel.startsWith("[data-field=")) {
        const field = sel.match(/data-field="([^"]+)"/)[1];
        return this.children.flatMap((row) => row.children || []).filter((n) => n.dataset && n.dataset.field === field);
      }
      if (sel === "tr") return this.children.filter((c) => c.tagName === "TR");
      return [];
    },
    querySelector(sel) {
      return this.querySelectorAll(sel)[0] || null;
    },
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return this.attributes[name]; },
    click() {
      (this.listeners.click || []).forEach((fn) => fn({ target: this, preventDefault() {} }));
    },
  };
  Object.defineProperty(node, "classList", {
    get() {
      return {
        toggle: (name, on) => {
          const parts = new Set(node.className.split(/\s+/).filter(Boolean));
          if (on) parts.add(name); else parts.delete(name);
          node.className = [...parts].join(" ");
        },
        contains: (name) => node.className.split(/\s+/).includes(name),
      };
    },
  });
  return node;
}

const ids = {};
function idEl(name, extra) {
  ids[name] = el(name, extra);
  return ids[name];
}

const tabs = ["general","users","notifications","system","smtp","alarms"].map((name) => {
  const btn = el("settings-tab-" + name, { className: name === "general" ? "tab-btn is-active" : "tab-btn", dataset: { tab: name } });
  ids[btn.id] = btn;
  return btn;
});
const panels = ["general","users","notifications","system","smtp","alarms"].map((name) => {
  const panel = el("settings-panel-" + name, { hidden: name !== "general", dataset: { tabPanel: name } });
  ids[panel.id] = panel;
  return panel;
});

[
  "settings-button","settings-close","settings-form","settings-test","settings-export",
  "settings-token-generate","settings-token-revoke","settings-overlay","settings-status",
  "settings-general-info","settings-general-dl","settings-system-info","settings-system-dl",
  "settings-diag-dl","settings-token-status","settings-token-once","threshold-body","users-body",
  "notify-enabled","notify-email-enabled","notify-recovery","notify-cooldown","smtp-host",
  "smtp-port","smtp-security","smtp-username","smtp-password","smtp-from","smtp-to","smtp-web-url",
  "user-add","user-form","user-form-close","user-form-cancel","user-overlay","user-form-title",
  "user-id","user-username","user-password","user-password-confirm","user-role","user-enabled",
  "user-form-error","user-delete-cancel","user-delete-confirm","user-delete-overlay","user-delete-name",
  "login-overlay",
].forEach((name) => idEl(name));
ids["login-overlay"].hidden = true;
ids["settings-overlay"].hidden = true;
ids["user-overlay"].hidden = true;
ids["user-delete-overlay"].hidden = true;

const fetches = [];
const loc = { pathname: "/settings", hash: "", href: "http://example.test/settings" };
const historyStack = [{ pathname: "/settings", hash: "" }];
function syncHref() {
  loc.href = "http://example.test" + loc.pathname + loc.hash;
}
const windowEmitter = new EventEmitter();

const documentStub = {
  readyState: "complete",
  title: "",
  documentElement: { dataset: { locale: "CZ" }, lang: "cs" },
  getElementById(id) { return ids[id] || null; },
  querySelectorAll(sel) {
    if (sel === ".tab-btn") return tabs;
    if (sel === "[data-tab-panel]") return panels;
    if (sel.startsWith("[data-i18n")) return [];
    return [];
  },
  querySelector() { return null; },
  createElement(tag) { return el("", { tagName: String(tag).toUpperCase() }); },
  addEventListener() {},
};

const context = {
  console,
  setTimeout,
  clearTimeout,
  URL: { createObjectURL: () => "blob:fake", revokeObjectURL() {} },
  Blob: function Blob() {},
  sessionStorage: { getItem: () => "YWI=", setItem() {}, removeItem() {} },
  location: loc,
  history: {
    pushState(_s, _t, url) {
      const u = new URL(url, "http://example.test");
      loc.pathname = u.pathname;
      loc.hash = u.hash;
      syncHref();
      historyStack.push({ pathname: loc.pathname, hash: loc.hash });
    },
    replaceState(_s, _t, url) {
      const u = new URL(url, "http://example.test");
      loc.pathname = u.pathname;
      loc.hash = u.hash;
      syncHref();
      historyStack[historyStack.length - 1] = { pathname: loc.pathname, hash: loc.hash };
    },
  },
  document: documentStub,
  window: {
    addEventListener(name, fn) { windowEmitter.on(name, fn); },
    history: null,
    location: loc,
  },
  fetch: async (url, options) => {
    fetches.push({ url, method: (options && options.method) || "GET" });
    const body = (() => {
      if (url === "/api/settings") {
        return {
          enabled: true,
          writable: true,
          email: {
            enabled: true,
            notify_recovery: true,
            cooldown_seconds: 3600,
            from: "meter@example.com",
            to: ["admin@example.com"],
            web_url: "http://example.test",
            smtp: { host: "smtp.example.com", port: 587, security: "starttls", username: "meter", timeout_seconds: 15 },
          },
          thresholds: { temperature: { enabled: true, warning_high: 45, critical_high: 50, unit: "°C" } },
        };
      }
      if (url === "/api/admin/users") return { users: [{ id: 1, username: "admin", role: "admin", enabled: true, created_at: 0 }] };
      if (url === "/api/admin/system") {
        return { application_version: "1.1.0", python_version: "3.12", os: "Linux", kernel: "6", uptime_seconds: 10, cpu_usage_percent: 1, cpu_temperature_c: 40, ram_usage_percent: 20, i2c_bus: "/dev/i2c-1", bme690_address: "0x77", bsec_version: "2" };
      }
      if (url === "/api/admin/monitoring-token") return { configured: false };
      if (url === "/api/status") {
        return {
          application: { locale: "CZ", environment: "test", interval_seconds: 5, sensor_type: "BME690", memory_protection: true, history_max_samples: 100, history_max_age_seconds: 3600 },
          history: { samples: 3, max_samples: 100, max_age_seconds: 3600, memory_bytes: 840 },
          memory: { ram_usage_percent: 20, pressure: "normal" },
          sensor: { status: "ok", age_seconds: 4 },
          system_health: { items: { i2c: { status: "ok" }, bsec: { status: "ok" }, bme690: { status: "ok" }, ram_protection: { status: "ok" } } },
        };
      }
      if (url === "/api/current") return { iaq_accuracy: 3, static_iaq_accuracy: 3 };
      if (url === "/api/settings/test-email") return { ok: true };
      return {};
    })();
    return { ok: true, status: 200, json: async () => body };
  },
};
context.window.history = context.history;
context.window.document = documentStub;
context.window.sessionStorage = context.sessionStorage;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(fs.readFileSync(process.env.I18N_JS, "utf8"), context);
context.window.ServerMeterI18n = context.ServerMeterI18n;
vm.runInContext(fs.readFileSync(process.env.SETTINGS_JS, "utf8"), context);
const api = context.window.ServerMeterSettings;

function visible() {
  return Object.fromEntries(panels.map((p) => [p.dataset.tabPanel, !p.hidden]));
}
function only(name) {
  const v = visible();
  return Object.keys(v).every((k) => v[k] === (k === name));
}

function urls() { return fetches.map((f) => f.url); }

async function run() {
  const out = {};
  await api.setRole("admin");
  out.defaultSection = api.currentSection();
  out.defaultOnlyGeneral = only("general");
  out.defaultOpen = api.isOpen();
  out.defaultUrls = urls().slice();
  out.defaultHasUsers = urls().includes("/api/admin/users");
  out.defaultHasSystem = urls().includes("/api/admin/system");
  out.defaultHasSettings = urls().includes("/api/settings");

  fetches.length = 0;
  await api.showTab("users");
  out.usersOnly = only("users");
  out.usersHash = loc.hash;
  out.usersPath = loc.pathname;
  out.usersFetched = urls().includes("/api/admin/users");
  out.generalHiddenAfterUsers = panels.find((p) => p.dataset.tabPanel === "general").hidden;

  fetches.length = 0;
  await api.showTab("smtp");
  out.smtpOnly = only("smtp");
  out.smtpHash = loc.hash;
  out.smtpFetchedSettings = urls().includes("/api/settings");
  out.smtpFetchedUsers = urls().includes("/api/admin/users");
  out.passwordEmpty = ids["smtp-password"].value === "";

  fetches.length = 0;
  await api.showTab("alarms");
  out.alarmsOnly = only("alarms");
  out.alarmsHash = loc.hash;
  out.alarmsRefetchSettings = urls().includes("/api/settings");

  loc.pathname = "/settings";
  loc.hash = "#smtp";
  syncHref();
  await api.openSettings();
  out.refreshSmtp = only("smtp") && api.currentSection() === "smtp";
  out.refreshHash = loc.hash;

  loc.pathname = "/settings";
  loc.hash = "#users";
  syncHref();
  await api.openSettings();
  out.directUsers = only("users") && api.currentSection() === "users";

  loc.pathname = "/settings";
  loc.hash = "#alarms";
  syncHref();
  await api.openSettings();
  out.directAlarms = only("alarms") && api.currentSection() === "alarms";

  const labelsCz = {};
  const labelsEn = {};
  context.ServerMeterI18n.setLocale("CZ");
  for (const id of ["general","users","notifications","system","smtp","alarms"]) {
    labelsCz[id] = context.ServerMeterI18n.t(api.SETTINGS_SECTIONS[id].labelKey);
  }
  context.ServerMeterI18n.setLocale("EN");
  for (const id of ["general","users","notifications","system","smtp","alarms"]) {
    labelsEn[id] = context.ServerMeterI18n.t(api.SETTINGS_SECTIONS[id].labelKey);
  }
  out.labelsCz = labelsCz;
  out.labelsEn = labelsEn;
  out.canonicalUnknown = api.canonicalSection("nope");
  out.canonicalAlias = api.canonicalSection("#thresholds");
  out.smtpTabActive = tabs.find((b) => b.dataset.tab === "smtp").className.includes("is-active") === false
    && tabs.find((b) => b.dataset.tab === "alarms").className.includes("is-active");

  api.setRole("user");
  out.userClosed = api.isOpen() === false;
  loc.pathname = "/settings";
  loc.hash = "#smtp";
  await api.openSettings();
  out.userCannotOpen = api.isOpen() === false;

  process.stdout.write(JSON.stringify(out));
}
run().catch((err) => { console.error(err); process.exit(1); });
"""
    result = subprocess.check_output(
        ["node", "-e", script],
        text=True,
        env={
            **os.environ,
            "I18N_JS": str(ROOT / "web" / "js" / "i18n.js"),
            "SETTINGS_JS": str(ROOT / "web" / "js" / "settings.js"),
        },
    )
    payload = json.loads(result)
    assert payload["defaultSection"] == "general"
    assert payload["defaultOnlyGeneral"] is True
    assert payload["defaultOpen"] is True
    assert payload["defaultHasUsers"] is False
    assert payload["defaultHasSystem"] is False
    assert payload["defaultHasSettings"] is False
    assert payload["usersOnly"] is True
    assert payload["generalHiddenAfterUsers"] is True
    assert payload["usersHash"] == "#users"
    assert payload["usersPath"] == "/settings"
    assert payload["usersFetched"] is True
    assert payload["smtpOnly"] is True
    assert payload["smtpHash"] == "#smtp"
    assert payload["smtpFetchedSettings"] is True
    assert payload["smtpFetchedUsers"] is False
    assert payload["passwordEmpty"] is True
    assert payload["alarmsOnly"] is True
    assert payload["alarmsHash"] == "#alarms"
    assert payload["alarmsRefetchSettings"] is False
    assert payload["refreshSmtp"] is True
    assert payload["refreshHash"] == "#smtp"
    assert payload["directUsers"] is True
    assert payload["directAlarms"] is True
    assert payload["labelsCz"] == {
        "general": "Obecné",
        "users": "Uživatelé",
        "notifications": "Notifikace",
        "system": "Systém",
        "smtp": "SMTP",
        "alarms": "Alarmy",
    }
    assert payload["labelsEn"] == {
        "general": "General",
        "users": "Users",
        "notifications": "Notifications",
        "system": "System",
        "smtp": "SMTP",
        "alarms": "Alarms",
    }
    assert payload["canonicalUnknown"] == "general"
    assert payload["canonicalAlias"] == "alarms"
    assert payload["userClosed"] is True
    assert payload["userCannotOpen"] is True
