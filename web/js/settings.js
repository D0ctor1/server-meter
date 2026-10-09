(() => {
  const AUTH_STORAGE_KEY = "server-meter.basic";
  const i18n = window.ServerMeterI18n;
  const t = (key, params) => i18n.t(key, params);

  const SETTINGS_SECTIONS = {
    general: {
      id: "general",
      labelKey: "settings.tab.general",
      requiredRole: "admin",
      content: "[data-tab-panel='general']",
    },
    users: {
      id: "users",
      labelKey: "settings.tab.users",
      requiredRole: "admin",
      content: "[data-tab-panel='users']",
    },
    notifications: {
      id: "notifications",
      labelKey: "settings.tab.notifications",
      requiredRole: "admin",
      content: "[data-tab-panel='notifications']",
    },
    system: {
      id: "system",
      labelKey: "settings.tab.system",
      requiredRole: "admin",
      content: "[data-tab-panel='system']",
    },
    smtp: {
      id: "smtp",
      labelKey: "settings.tab.smtp",
      requiredRole: "admin",
      content: "[data-tab-panel='smtp']",
    },
    alarms: {
      id: "alarms",
      labelKey: "settings.tab.alarms",
      requiredRole: "admin",
      content: "[data-tab-panel='alarms']",
    },
  };

  const HASH_ALIASES = { thresholds: "alarms" };
  const DEFAULT_SECTION = "general";
  const SETTINGS_PATH = "/settings";
  const FORM_SECTIONS = { notifications: true, smtp: true, alarms: true };

  const METRIC_ORDER = [
    "temperature",
    "humidity",
    "pressure",
    "gas_resistance",
    "iaq",
    "iaq_accuracy",
    "static_iaq",
    "eco2",
    "bvoc",
    "cpu_temperature",
    "cpu_usage",
    "ram_usage",
    "sensor_unavailable",
  ];

  const $ = (id) => document.getElementById(id);
  let loaded = null;
  let settingsFetch = null;
  let currentRole = "user";
  let currentSection = DEFAULT_SECTION;
  let syncingHash = false;
  let overlayOpen = false;

  function authHeader() {
    const token = sessionStorage.getItem(AUTH_STORAGE_KEY);
    return token ? { Authorization: `Basic ${token}` } : {};
  }

  async function requestJson(url, options) {
    const response = await fetch(url, {
      cache: "no-store",
      ...options,
      headers: { ...(options && options.headers), ...authHeader() },
    });
    if (response.status === 401) {
      const err = new Error("unauthorized");
      err.code = 401;
      throw err;
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (_exc) {
      payload = null;
    }
    if (!response.ok) {
      const message = payload && (payload.message || payload.error)
        ? (payload.message || payload.error)
        : t("error.http", { code: response.status });
      const err = new Error(message);
      err.code = response.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  function numOrEmpty(value) {
    return value === null || value === undefined ? "" : String(value);
  }

  function parseNum(value) {
    if (value === "" || value === null || value === undefined) return null;
    const number = Number(value);
    return Number.isNaN(number) ? null : number;
  }

  function fmtMem(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return "—";
    const n = Number(bytes);
    if (n < 1024) return `${Math.round(n)} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KiB`;
    return `${(n / (1024 * 1024)).toFixed(1)} MiB`;
  }

  function canonicalSection(raw) {
    const id = String(raw || "").replace(/^#/, "").trim().toLowerCase();
    const mapped = HASH_ALIASES[id] || id;
    return Object.prototype.hasOwnProperty.call(SETTINGS_SECTIONS, mapped)
      ? mapped
      : DEFAULT_SECTION;
  }

  function hashSection() {
    return canonicalSection(typeof location !== "undefined" ? location.hash : "");
  }

  function currentPathname() {
    const path = typeof location !== "undefined" ? location.pathname : "/";
    return path.replace(/\/+$/, "") || "/";
  }

  function wantsSettingsFromUrl() {
    if (currentPathname() === SETTINGS_PATH) return true;
    const raw = String(typeof location !== "undefined" ? location.hash : "").replace(/^#/, "");
    if (!raw) return false;
    const mapped = HASH_ALIASES[raw.toLowerCase()] || raw.toLowerCase();
    return Object.prototype.hasOwnProperty.call(SETTINGS_SECTIONS, mapped);
  }

  function setStatus(message, kind) {
    const node = $("settings-status");
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.textContent = "";
      node.className = "settings-status";
      return;
    }
    node.hidden = false;
    node.textContent = message;
    node.className = `settings-status ${kind || ""}`;
  }

  function metricLabel(name) {
    const key = `settings.metric.${name}`;
    const translated = t(key);
    return translated === key ? name : translated;
  }

  function renderThresholds(thresholds) {
    const body = $("threshold-body");
    if (!body) return;
    body.innerHTML = "";
    const names = METRIC_ORDER.filter((name) => thresholds[name]).concat(
      Object.keys(thresholds).filter((name) => METRIC_ORDER.indexOf(name) < 0),
    );
    for (const name of names) {
      const spec = thresholds[name] || {};
      const unit = spec.unit ? ` ${spec.unit}` : "";
      const row = document.createElement("tr");
      row.dataset.metric = name;
      row.innerHTML = `
        <td>${metricLabel(name)}${unit ? `<span class="unit"> ${unit}</span>` : ""}</td>
        <td><input type="checkbox" data-field="enabled"${spec.enabled ? " checked" : ""}></td>
        <td><input type="number" step="any" data-field="warning_high" value="${numOrEmpty(spec.warning_high)}"></td>
        <td><input type="number" step="any" data-field="critical_high" value="${numOrEmpty(spec.critical_high)}"></td>
        <td><input type="number" step="any" data-field="warning_low" value="${numOrEmpty(spec.warning_low)}"></td>
        <td><input type="number" step="any" data-field="critical_low" value="${numOrEmpty(spec.critical_low)}"></td>
        <td><input type="number" step="any" data-field="hysteresis" value="${numOrEmpty(spec.hysteresis)}"></td>
        <td><input type="number" step="1" min="0" data-field="min_duration_seconds" value="${numOrEmpty(spec.min_duration_seconds)}"></td>
      `;
      body.appendChild(row);
    }
  }

  function readThresholds() {
    const thresholds = {};
    const body = $("threshold-body");
    if (!body) return thresholds;
    body.querySelectorAll("tr").forEach((row) => {
      const name = row.dataset.metric;
      const get = (field) => row.querySelector(`[data-field="${field}"]`);
      thresholds[name] = {
        enabled: get("enabled").checked,
        warning_high: parseNum(get("warning_high").value),
        critical_high: parseNum(get("critical_high").value),
        warning_low: parseNum(get("warning_low").value),
        critical_low: parseNum(get("critical_low").value),
        hysteresis: parseNum(get("hysteresis").value),
        min_duration_seconds: parseNum(get("min_duration_seconds").value),
      };
    });
    return thresholds;
  }

  function fillForm(data) {
    loaded = data;
    if ($("notify-enabled")) $("notify-enabled").checked = !!data.enabled;
    if ($("notify-email-enabled")) $("notify-email-enabled").checked = !!(data.email && data.email.enabled);
    if ($("notify-recovery")) $("notify-recovery").checked = !!(data.email && data.email.notify_recovery);
    if ($("notify-cooldown")) $("notify-cooldown").value = data.email ? data.email.cooldown_seconds : 3600;
    const smtp = (data.email && data.email.smtp) || {};
    if ($("smtp-host")) $("smtp-host").value = smtp.host || "";
    if ($("smtp-port")) $("smtp-port").value = smtp.port || 587;
    if ($("smtp-security")) $("smtp-security").value = smtp.security || "starttls";
    if ($("smtp-username")) $("smtp-username").value = smtp.username || "";
    if ($("smtp-password")) $("smtp-password").value = "";
    if ($("smtp-from")) $("smtp-from").value = (data.email && data.email.from) || "";
    if ($("smtp-to")) $("smtp-to").value = ((data.email && data.email.to) || []).join(", ");
    if ($("smtp-web-url")) $("smtp-web-url").value = (data.email && data.email.web_url) || "";
    renderThresholds(data.thresholds || {});
    if (data.delivery_error) {
      setStatus(t("settings.delivery_error", { error: data.delivery_error }), "state-warn");
    } else if (data.writable === false) {
      setStatus(t("settings.not_writable"), "state-warn");
    }
  }

  function payloadFromForm() {
    const password = $("smtp-password") ? $("smtp-password").value : "";
    const smtp = {
      host: $("smtp-host") ? $("smtp-host").value.trim() : "",
      port: $("smtp-port") ? parseNum($("smtp-port").value) : null,
      security: $("smtp-security") ? $("smtp-security").value : "starttls",
      username: $("smtp-username") ? $("smtp-username").value.trim() : "",
      timeout_seconds: loaded && loaded.email && loaded.email.smtp
        ? loaded.email.smtp.timeout_seconds
        : 15,
    };
    if (password) smtp.password = password;
    return {
      enabled: $("notify-enabled") ? $("notify-enabled").checked : false,
      email: {
        enabled: $("notify-email-enabled") ? $("notify-email-enabled").checked : false,
        notify_recovery: $("notify-recovery") ? $("notify-recovery").checked : false,
        cooldown_seconds: $("notify-cooldown") ? parseNum($("notify-cooldown").value) : 3600,
        from: $("smtp-from") ? $("smtp-from").value.trim() : "",
        to: $("smtp-to") ? $("smtp-to").value : "",
        web_url: $("smtp-web-url") ? $("smtp-web-url").value.trim() : "",
        smtp,
      },
      thresholds: readThresholds(),
    };
  }

  let editingUserId = null;
  let deletingUser = null;

  function applyVisibility(name) {
    const section = canonicalSection(name);
    currentSection = section;
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      const active = btn.dataset.tab === section;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-selected", active ? "true" : "false");
    });
    document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
      const active = panel.dataset.tabPanel === section;
      panel.hidden = !active;
      panel.setAttribute("aria-hidden", active ? "false" : "true");
    });
    if (section !== "users") {
      closeUserForm();
      closeDeleteUser();
    }
    if (section !== "system") {
      closeRestartService();
      closeRebootHost();
    }
    return section;
  }

  function syncHash(section, replace) {
    const next = `#${section}`;
    const path = overlayOpen ? SETTINGS_PATH : currentPathname();
    const target = `${path}${next}`;
    const current = `${currentPathname()}${typeof location !== "undefined" ? location.hash : ""}`;
    if (current === target) return;
    syncingHash = true;
    try {
      if (replace && window.history && window.history.replaceState) {
        window.history.replaceState(null, "", target);
      } else if (window.history && window.history.pushState) {
        window.history.pushState(null, "", target);
      } else if (typeof location !== "undefined") {
        location.hash = next;
      }
    } finally {
      syncingHash = false;
    }
  }

  async function loadSectionData(section) {
    if (section === "general") {
      await fillGeneral();
      return;
    }
    if (section === "users") {
      await loadUsers();
      return;
    }
    if (section === "system") {
      await fillSystemDetails();
      return;
    }
    if (FORM_SECTIONS[section]) {
      await ensureSettingsLoaded();
    }
  }

  async function showTab(name, options) {
    const opts = options || {};
    const section = applyVisibility(name);
    if (!opts.skipHash) syncHash(section, !!opts.replaceHash);
    if (opts.skipLoad) return section;
    await loadSectionData(section);
    return section;
  }

  async function ensureSettingsLoaded() {
    if (loaded) return loaded;
    if (settingsFetch) return settingsFetch;
    settingsFetch = requestJson("/api/settings", { method: "GET" })
      .then((data) => {
        fillForm(data);
        return data;
      })
      .finally(() => {
        settingsFetch = null;
      });
    return settingsFetch;
  }

  function roleLabel(role) {
    return role === "admin" ? t("users.role_admin") : t("users.role_user");
  }

  function statusLabel(enabled) {
    return enabled ? t("users.active") : t("users.disabled");
  }

  function userErrorMessage(err) {
    if (err && err.payload && err.payload.error === "last_admin") {
      return t("users.last_admin");
    }
    if (err && err.payload && err.payload.error === "duplicate_username") {
      return t("users.duplicate");
    }
    return err && err.message ? err.message : t("error.http", { code: (err && err.code) || "" });
  }

  async function loadUsers() {
    const body = $("users-body");
    if (!body) return;
    try {
      const data = await requestJson("/api/admin/users", { method: "GET" });
      body.innerHTML = "";
      (data.users || []).forEach((user) => {
        const row = document.createElement("tr");
        const created = user.created_at ? i18n.formatDateTimeFromTs(user.created_at) : "—";
        const activity = user.last_activity_at
          ? i18n.formatDateTimeFromTs(user.last_activity_at)
          : t("users.never");
        row.innerHTML = `
          <td></td>
          <td></td>
          <td></td>
          <td></td>
          <td></td>
          <td class="user-actions"></td>
        `;
        row.children[0].textContent = user.username;
        row.children[1].textContent = roleLabel(user.role);
        row.children[2].textContent = statusLabel(user.enabled);
        row.children[3].textContent = activity;
        row.children[4].textContent = created;
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "secondary-btn";
        edit.textContent = t("users.edit");
        edit.addEventListener("click", () => openUserForm(user));
        row.children[5].appendChild(edit);
        const del = document.createElement("button");
        del.type = "button";
        del.className = "danger-btn";
        del.textContent = t("users.delete");
        del.addEventListener("click", () => openDeleteUser(user));
        row.children[5].appendChild(del);
        body.appendChild(row);
      });
    } catch (err) {
      setStatus(userErrorMessage(err), "state-crit");
    }
  }

  function setUserFormError(message) {
    const node = $("user-form-error");
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = message;
  }

  function openUserForm(user) {
    if (currentSection !== "users") return;
    editingUserId = user && user.id ? user.id : null;
    $("user-form-title").textContent = editingUserId ? t("users.edit_title") : t("users.add_title");
    $("user-id").value = editingUserId || "";
    $("user-username").value = user ? user.username : "";
    $("user-password").value = "";
    $("user-password-confirm").value = "";
    $("user-role").value = user && user.role === "admin" ? "admin" : "user";
    $("user-enabled").value = user && user.enabled === false ? "0" : "1";
    setUserFormError("");
    $("user-overlay").hidden = false;
    i18n.apply($("user-overlay"));
    $("user-form-title").textContent = editingUserId ? t("users.edit_title") : t("users.add_title");
    $("user-password").placeholder = editingUserId ? t("users.password_keep") : "";
  }

  function closeUserForm() {
    const overlay = $("user-overlay");
    if (overlay) overlay.hidden = true;
    if ($("user-password")) $("user-password").value = "";
    if ($("user-password-confirm")) $("user-password-confirm").value = "";
    editingUserId = null;
  }

  function openDeleteUser(user) {
    if (currentSection !== "users") return;
    deletingUser = user;
    $("user-delete-name").textContent = user.username;
    $("user-delete-overlay").hidden = false;
    i18n.apply($("user-delete-overlay"));
    $("user-delete-name").textContent = user.username;
  }

  function closeDeleteUser() {
    const overlay = $("user-delete-overlay");
    if (overlay) overlay.hidden = true;
    deletingUser = null;
  }

  function overlayVisible(id) {
    const node = $(id);
    return !!(node && !node.hidden);
  }

  function closeRestartService() {
    const overlay = $("restart-service-overlay");
    if (overlay) overlay.hidden = true;
  }

  function openRestartService() {
    if (currentSection !== "system") return;
    const overlay = $("restart-service-overlay");
    if (!overlay) return;
    overlay.hidden = false;
    i18n.apply(overlay);
  }

  function closeRebootHost() {
    const first = $("reboot-host-overlay");
    const second = $("reboot-host-final-overlay");
    if (first) first.hidden = true;
    if (second) second.hidden = true;
  }

  function openRebootHost() {
    if (currentSection !== "system") return;
    closeRebootHost();
    const overlay = $("reboot-host-overlay");
    if (!overlay) return;
    overlay.hidden = false;
    i18n.apply(overlay);
  }

  function openRebootHostFinal() {
    const first = $("reboot-host-overlay");
    if (first) first.hidden = true;
    const overlay = $("reboot-host-final-overlay");
    if (!overlay) return;
    overlay.hidden = false;
    i18n.apply(overlay);
  }

  function isDisconnectError(err) {
    if (!err) return false;
    if (err.name === "TypeError" || err.name === "AbortError") return true;
    const code = Number(err.code);
    return code === 502 || code === 503 || code === 504;
  }

  async function postSystemAction(url, confirm) {
    return requestJson(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm }),
    });
  }

  async function onRestartServiceConfirm() {
    try {
      await postSystemAction("/api/admin/restart-service", "restart-service");
      closeRestartService();
      setStatus(t("system.restart_service.accepted"), "state-warn");
    } catch (err) {
      closeRestartService();
      if (isDisconnectError(err)) {
        setStatus(t("system.restart_service.interrupted"), "state-warn");
        return;
      }
      setStatus(err.message || t("system.restart_service.failed"), "state-crit");
    }
  }

  async function onRebootHostFinalConfirm() {
    try {
      await postSystemAction("/api/admin/reboot-host", "reboot-host");
      closeRebootHost();
      setStatus(t("system.reboot_host.accepted"), "state-warn");
    } catch (err) {
      closeRebootHost();
      if (isDisconnectError(err)) {
        setStatus(t("system.reboot_host.interrupted"), "state-warn");
        return;
      }
      setStatus(err.message || t("system.reboot_host.failed"), "state-crit");
    }
  }

  async function onUserSave(event) {
    event.preventDefault();
    const username = $("user-username").value.trim();
    const password = $("user-password").value;
    const confirm = $("user-password-confirm").value;
    if (password !== confirm) {
      setUserFormError(t("users.password_mismatch"));
      return;
    }
    if (!editingUserId && !password) {
      setUserFormError(t("users.password_required"));
      return;
    }
    const payload = {
      username,
      role: $("user-role").value,
      enabled: $("user-enabled").value === "1",
    };
    if (password) payload.password = password;
    try {
      if (editingUserId) {
        await requestJson(`/api/admin/users/${editingUserId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        await requestJson("/api/admin/users", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }
      closeUserForm();
      await loadUsers();
      setStatus(t("users.saved"), "state-ok");
      syncHash("users", true);
    } catch (err) {
      setUserFormError(userErrorMessage(err));
    }
  }

  async function onUserDelete() {
    if (!deletingUser) return;
    try {
      await requestJson(`/api/admin/users/${deletingUser.id}`, { method: "DELETE" });
      closeDeleteUser();
      await loadUsers();
      setStatus(t("users.deleted"), "state-ok");
      syncHash("users", true);
    } catch (err) {
      closeDeleteUser();
      setStatus(userErrorMessage(err), "state-crit");
    }
  }

  function fillDl(id, rows) {
    const root = $(id);
    if (!root) return;
    root.innerHTML = "";
    for (const [label, value] of rows) {
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.textContent = value == null || value === "" ? "—" : String(value);
      root.append(dt, dd);
    }
  }

  function onOff(value) {
    return value ? t("settings.enabled_on") : t("settings.enabled_off");
  }

  async function fillGeneral() {
    try {
      const status = await requestJson("/api/status", { method: "GET" });
      const app = status.application || {};
      const history = status.history || {};
      const locale = app.locale || "CZ";
      if ($("settings-general-info")) {
        $("settings-general-info").textContent = t("settings.general_info", {
          locale,
          env: app.environment || "",
        });
      }
      fillDl("settings-general-dl", [
        [t("settings.general.locale"), locale],
        [t("settings.general.environment"), app.environment || "—"],
        [t("settings.general.sensor_type"), app.sensor_type || "BME690"],
        [t("settings.general.interval"), app.interval_seconds != null ? `${app.interval_seconds} s` : "—"],
        [t("settings.general.max_samples"), history.max_samples != null ? history.max_samples : app.history_max_samples],
        [t("settings.general.max_age"), history.max_age_auto || app.history_max_age_auto
          ? `${t("settings.general.max_age_auto")} ≈ ${i18n.formatDuration(
            history.theoretical_max_age_seconds != null
              ? history.theoretical_max_age_seconds
              : app.history_max_age_seconds,
          )}`
          : i18n.formatDuration(
            history.max_age_seconds != null ? history.max_age_seconds : app.history_max_age_seconds,
          )],
        [t("settings.general.ram_protection"), onOff(!!app.memory_protection)],
      ]);
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  async function fillSystemDetails() {
    try {
      const [info, token, status, current] = await Promise.all([
        requestJson("/api/admin/system", { method: "GET" }),
        requestJson("/api/admin/monitoring-token", { method: "GET" }),
        requestJson("/api/status", { method: "GET" }),
        requestJson("/api/current", { method: "GET" }),
      ]);
      if ($("settings-system-info")) {
        $("settings-system-info").textContent = t("settings.system_info", {
          ram: status.memory && status.memory.ram_usage_percent != null
            ? Number(status.memory.ram_usage_percent).toFixed(0)
            : "—",
          samples: status.history ? status.history.samples : 0,
          sensor: status.sensor ? status.sensor.status : "—",
        });
      }
      fillDl("settings-system-dl", [
        [t("diag.app_version"), info.application_version],
        [t("diag.python"), info.python_version],
        [t("diag.os"), info.os],
        [t("diag.kernel"), info.kernel],
        [t("diag.uptime"), i18n.formatDuration(info.uptime_seconds)],
        [t("diag.cpu"), info.cpu_usage_percent == null ? "—" : `${Number(info.cpu_usage_percent).toFixed(0)} %`],
        [t("diag.cpu_temp"), info.cpu_temperature_c == null ? "—" : `${Number(info.cpu_temperature_c).toFixed(1)} °C`],
        [t("diag.ram"), info.ram_usage_percent == null ? "—" : `${Number(info.ram_usage_percent).toFixed(0)} %`],
      ]);
      const health = status.system_health && status.system_health.items ? status.system_health.items : {};
      const i2c = health.i2c || {};
      const bsec = health.bsec || {};
      const bme = health.bme690 || {};
      const ramProt = health.ram_protection || {};
      fillDl("settings-diag-dl", [
        [t("diag.i2c_bus"), info.i2c_bus || i2c.bus],
        [t("diag.address"), info.bme690_address || i2c.address],
        [t("diag.i2c_status"), i2c.status || "—"],
        [t("diag.bme690_status"), bme.status || "—"],
        [t("diag.bsec_version"), info.bsec_version || "—"],
        [t("diag.bsec_status"), bsec.status || "—"],
        [t("diag.sensor_age"), status.sensor && status.sensor.age_seconds != null
          ? i18n.formatDuration(status.sensor.age_seconds)
          : "—"],
        [t("diag.history_samples"), status.history
          ? `${status.history.samples} / ${status.history.max_samples}`
          : "—"],
        [t("diag.ram_history"), status.history ? fmtMem(status.history.memory_bytes) : "—"],
        [t("diag.ram_protection_status"), ramProt.status || ramProt.pressure || "—"],
        [t("diag.iaq_accuracy"), current && current.iaq_accuracy != null ? String(current.iaq_accuracy) : "—"],
        [t("diag.static_iaq_accuracy"), current && current.static_iaq_accuracy != null ? String(current.static_iaq_accuracy) : "—"],
      ]);
      const tokenStatus = $("settings-token-status");
      if (tokenStatus) {
        tokenStatus.textContent = token.configured ? t("settings.token_configured") : t("settings.token_none");
      }
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  async function onExport() {
    try {
      const payload = await requestJson("/api/admin/export", { method: "GET" });
      const blob = JSON.stringify(payload, null, 2);
      const url = URL.createObjectURL(new Blob([blob], { type: "application/json" }));
      const link = document.createElement("a");
      link.href = url;
      link.download = "server-meter-config.json";
      link.click();
      URL.revokeObjectURL(url);
      setStatus(t("settings.export_ok"), "state-ok");
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  async function onTokenGenerate() {
    try {
      const payload = await requestJson("/api/admin/monitoring-token", { method: "POST" });
      const once = $("settings-token-once");
      if (once) {
        once.hidden = false;
        once.textContent = t("settings.token_once", { token: payload.token });
      }
      await fillSystemDetails();
      setStatus(t("settings.token_generated"), "state-ok");
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  async function onTokenRevoke() {
    try {
      await requestJson("/api/admin/monitoring-token", { method: "DELETE" });
      const once = $("settings-token-once");
      if (once) {
        once.hidden = true;
        once.textContent = "";
      }
      await fillSystemDetails();
      setStatus(t("settings.token_revoked"), "state-ok");
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  async function openSettings(preferred) {
    if (currentRole !== "admin") return false;
    const login = $("login-overlay");
    if (login && !login.hidden) return false;
    const overlay = $("settings-overlay");
    if (!overlay) return false;
    overlayOpen = true;
    overlay.hidden = false;
    i18n.apply(overlay);
    const section = canonicalSection(preferred || hashSection());
    await showTab(section, { replaceHash: currentPathname() === SETTINGS_PATH });
    return true;
  }

  function closeSettings() {
    overlayOpen = false;
    loaded = null;
    settingsFetch = null;
    const overlay = $("settings-overlay");
    if (overlay) overlay.hidden = true;
    if ($("smtp-password")) $("smtp-password").value = "";
    closeUserForm();
    closeDeleteUser();
    closeRestartService();
    closeRebootHost();
    if (currentPathname() === SETTINGS_PATH && window.history && window.history.pushState) {
      syncingHash = true;
      try {
        window.history.pushState(null, "", "/");
      } finally {
        syncingHash = false;
      }
    }
  }

  async function onSave(event) {
    event.preventDefault();
    try {
      await ensureSettingsLoaded();
      const data = await requestJson("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadFromForm()),
      });
      fillForm(data);
      if ($("smtp-password")) $("smtp-password").value = "";
      setStatus(t("settings.saved"), "state-ok");
      syncHash(currentSection, true);
    } catch (err) {
      setStatus(t("settings.save_failed", { error: err.message }), "state-crit");
    }
  }

  async function onTest() {
    if (currentSection !== "smtp") return;
    try {
      const result = await requestJson("/api/settings/test-email", { method: "POST" });
      if (result && result.ok) {
        setStatus(t("settings.test_ok"), "state-ok");
      } else {
        setStatus(t("settings.test_fail", { error: (result && result.error) || "" }), "state-crit");
      }
    } catch (err) {
      setStatus(t("settings.test_fail", { error: err.message }), "state-crit");
    }
  }

  async function onLocationChange() {
    if (syncingHash) return;
    if (currentRole !== "admin") return;
    if (wantsSettingsFromUrl()) {
      await openSettings(hashSection());
      return;
    }
    if (overlayOpen && currentPathname() !== SETTINGS_PATH) {
      overlayOpen = false;
      loaded = null;
      const overlay = $("settings-overlay");
      if (overlay) overlay.hidden = true;
      closeUserForm();
      closeDeleteUser();
      closeRestartService();
      closeRebootHost();
    }
  }

  function boot() {
    const button = $("settings-button");
    if (!button) return;
    button.addEventListener("click", () => {
      const preferred = wantsSettingsFromUrl() ? hashSection() : DEFAULT_SECTION;
      openSettings(preferred);
    });
    $("settings-close").addEventListener("click", closeSettings);
    $("settings-form").addEventListener("submit", onSave);
    $("settings-test").addEventListener("click", onTest);
    if ($("settings-export")) $("settings-export").addEventListener("click", onExport);
    if ($("settings-token-generate")) $("settings-token-generate").addEventListener("click", onTokenGenerate);
    if ($("settings-token-revoke")) $("settings-token-revoke").addEventListener("click", onTokenRevoke);
    $("settings-overlay").addEventListener("click", (event) => {
      if (event.target === $("settings-overlay")) closeSettings();
    });
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.dataset.tab));
    });
    $("user-add").addEventListener("click", () => openUserForm(null));
    $("user-form").addEventListener("submit", onUserSave);
    $("user-form-close").addEventListener("click", closeUserForm);
    $("user-form-cancel").addEventListener("click", closeUserForm);
    $("user-overlay").addEventListener("click", (event) => {
      if (event.target === $("user-overlay")) closeUserForm();
    });
    $("user-delete-cancel").addEventListener("click", closeDeleteUser);
    $("user-delete-confirm").addEventListener("click", onUserDelete);
    $("user-delete-overlay").addEventListener("click", (event) => {
      if (event.target === $("user-delete-overlay")) closeDeleteUser();
    });
    if ($("restart-service-btn")) $("restart-service-btn").addEventListener("click", openRestartService);
    if ($("restart-service-cancel")) $("restart-service-cancel").addEventListener("click", closeRestartService);
    if ($("restart-service-confirm")) $("restart-service-confirm").addEventListener("click", onRestartServiceConfirm);
    if ($("restart-service-overlay")) {
      $("restart-service-overlay").addEventListener("click", (event) => {
        if (event.target === $("restart-service-overlay")) closeRestartService();
      });
    }
    if ($("reboot-host-btn")) $("reboot-host-btn").addEventListener("click", openRebootHost);
    if ($("reboot-host-cancel")) $("reboot-host-cancel").addEventListener("click", closeRebootHost);
    if ($("reboot-host-continue")) $("reboot-host-continue").addEventListener("click", openRebootHostFinal);
    if ($("reboot-host-overlay")) {
      $("reboot-host-overlay").addEventListener("click", (event) => {
        if (event.target === $("reboot-host-overlay")) closeRebootHost();
      });
    }
    if ($("reboot-host-final-cancel")) $("reboot-host-final-cancel").addEventListener("click", closeRebootHost);
    if ($("reboot-host-final-confirm")) $("reboot-host-final-confirm").addEventListener("click", onRebootHostFinalConfirm);
    if ($("reboot-host-final-overlay")) {
      $("reboot-host-final-overlay").addEventListener("click", (event) => {
        if (event.target === $("reboot-host-final-overlay")) closeRebootHost();
      });
    }
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (overlayVisible("reboot-host-final-overlay")) {
        closeRebootHost();
        return;
      }
      if (overlayVisible("reboot-host-overlay")) {
        closeRebootHost();
        return;
      }
      if (overlayVisible("restart-service-overlay")) {
        closeRestartService();
        return;
      }
      if ($("user-delete-overlay") && !$("user-delete-overlay").hidden) {
        closeDeleteUser();
        return;
      }
      if ($("user-overlay") && !$("user-overlay").hidden) {
        closeUserForm();
        return;
      }
      if ($("settings-overlay") && !$("settings-overlay").hidden) closeSettings();
    });
    window.addEventListener("hashchange", onLocationChange);
    window.addEventListener("popstate", onLocationChange);
  }

  function setRole(role) {
    const next = role === "admin" ? "admin" : "user";
    const changed = next !== currentRole;
    currentRole = next;
    const button = $("settings-button");
    if (button) button.hidden = currentRole !== "admin";
    if (currentRole !== "admin") {
      if (overlayOpen) closeSettings();
      return false;
    }
    if (overlayOpen) return false;
    if (changed && wantsSettingsFromUrl()) return openSettings(hashSection());
    return false;
  }

  window.ServerMeterSettings = {
    SETTINGS_SECTIONS,
    HASH_ALIASES,
    DEFAULT_SECTION,
    canonicalSection,
    hashSection,
    wantsSettingsFromUrl,
    applyVisibility,
    showTab,
    openSettings,
    closeSettings,
    setRole,
    currentSection() {
      return currentSection;
    },
    isOpen() {
      return overlayOpen;
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
