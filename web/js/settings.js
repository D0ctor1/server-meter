(() => {
  const AUTH_STORAGE_KEY = "server-meter.basic";
  const i18n = window.ServerMeterI18n;
  const t = (key, params) => i18n.t(key, params);

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
    $("threshold-body").querySelectorAll("tr").forEach((row) => {
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
    $("notify-enabled").checked = !!data.enabled;
    $("notify-email-enabled").checked = !!(data.email && data.email.enabled);
    $("notify-recovery").checked = !!(data.email && data.email.notify_recovery);
    $("notify-cooldown").value = data.email ? data.email.cooldown_seconds : 3600;
    const smtp = (data.email && data.email.smtp) || {};
    $("smtp-host").value = smtp.host || "";
    $("smtp-port").value = smtp.port || 587;
    $("smtp-security").value = smtp.security || "starttls";
    $("smtp-username").value = smtp.username || "";
    $("smtp-password").value = "";
    $("smtp-from").value = (data.email && data.email.from) || "";
    $("smtp-to").value = ((data.email && data.email.to) || []).join(", ");
    $("smtp-web-url").value = (data.email && data.email.web_url) || "";
    renderThresholds(data.thresholds || {});
    if (data.delivery_error) {
      setStatus(t("settings.delivery_error", { error: data.delivery_error }), "state-warn");
    } else if (data.writable === false) {
      setStatus(t("settings.not_writable"), "state-warn");
    } else {
      setStatus("", "");
    }
  }

  function payloadFromForm() {
    const password = $("smtp-password").value;
    const smtp = {
      host: $("smtp-host").value.trim(),
      port: parseNum($("smtp-port").value),
      security: $("smtp-security").value,
      username: $("smtp-username").value.trim(),
      timeout_seconds: loaded && loaded.email && loaded.email.smtp
        ? loaded.email.smtp.timeout_seconds
        : 15,
    };
    if (password) smtp.password = password;
    return {
      enabled: $("notify-enabled").checked,
      email: {
        enabled: $("notify-email-enabled").checked,
        notify_recovery: $("notify-recovery").checked,
        cooldown_seconds: parseNum($("notify-cooldown").value),
        from: $("smtp-from").value.trim(),
        to: $("smtp-to").value,
        web_url: $("smtp-web-url").value.trim(),
        smtp,
      },
      thresholds: readThresholds(),
    };
  }

  let editingUserId = null;
  let deletingUser = null;
  let currentRole = "user";

  function showTab(name) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.tab === name);
    });
    document.querySelectorAll("[data-tab-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.tabPanel !== name;
    });
    const formActions = $("settings-form-actions");
    if (formActions) {
      formActions.hidden = name !== "notifications" && name !== "smtp" && name !== "thresholds";
    }
    if (name === "users") loadUsers();
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
        row.innerHTML = `
          <td></td>
          <td></td>
          <td></td>
          <td></td>
          <td class="user-actions"></td>
        `;
        row.children[0].textContent = user.username;
        row.children[1].textContent = roleLabel(user.role);
        row.children[2].textContent = statusLabel(user.enabled);
        row.children[3].textContent = created;
        const edit = document.createElement("button");
        edit.type = "button";
        edit.className = "secondary-btn";
        edit.textContent = t("users.edit");
        edit.addEventListener("click", () => openUserForm(user));
        row.children[4].appendChild(edit);
        const del = document.createElement("button");
        del.type = "button";
        del.className = "danger-btn";
        del.textContent = t("users.delete");
        del.addEventListener("click", () => openDeleteUser(user));
        row.children[4].appendChild(del);
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
    $("user-overlay").hidden = true;
    $("user-password").value = "";
    $("user-password-confirm").value = "";
    editingUserId = null;
  }

  function openDeleteUser(user) {
    deletingUser = user;
    $("user-delete-name").textContent = user.username;
    $("user-delete-overlay").hidden = false;
    i18n.apply($("user-delete-overlay"));
    $("user-delete-name").textContent = user.username;
  }

  function closeDeleteUser() {
    $("user-delete-overlay").hidden = true;
    deletingUser = null;
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
    } catch (err) {
      closeDeleteUser();
      setStatus(userErrorMessage(err), "state-crit");
    }
  }

  async function openSettings() {
    if (currentRole !== "admin") return;
    const overlay = $("settings-overlay");
    overlay.hidden = false;
    i18n.apply(overlay);
    showTab("general");
    try {
      const [data, status] = await Promise.all([
        requestJson("/api/settings", { method: "GET" }),
        requestJson("/api/status", { method: "GET" }),
      ]);
      fillForm(data);
      const locale = status.application && status.application.locale ? status.application.locale : "CZ";
      $("settings-general-info").textContent = t("settings.general_info", {
        locale,
        env: status.application.environment || "",
      });
      $("settings-system-info").textContent = t("settings.system_info", {
        ram: status.memory && status.memory.ram_usage_percent != null
          ? Number(status.memory.ram_usage_percent).toFixed(0)
          : "—",
        samples: status.history ? status.history.samples : 0,
        sensor: status.sensor ? status.sensor.status : "—",
      });
    } catch (err) {
      setStatus(err.message, "state-crit");
    }
  }

  function closeSettings() {
    $("settings-overlay").hidden = true;
    $("smtp-password").value = "";
    closeUserForm();
    closeDeleteUser();
  }

  async function onSave(event) {
    event.preventDefault();
    try {
      const data = await requestJson("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadFromForm()),
      });
      fillForm(data);
      $("smtp-password").value = "";
      setStatus(t("settings.saved"), "state-ok");
    } catch (err) {
      setStatus(t("settings.save_failed", { error: err.message }), "state-crit");
    }
  }

  async function onTest() {
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

  function boot() {
    const button = $("settings-button");
    if (!button) return;
    button.addEventListener("click", openSettings);
    $("settings-close").addEventListener("click", closeSettings);
    $("settings-form").addEventListener("submit", onSave);
    $("settings-test").addEventListener("click", onTest);
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
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!$("user-delete-overlay").hidden) {
        closeDeleteUser();
        return;
      }
      if (!$("user-overlay").hidden) {
        closeUserForm();
        return;
      }
      if (!$("settings-overlay").hidden) closeSettings();
    });
    window.ServerMeterSettings = {
      setRole(role) {
        currentRole = role === "admin" ? "admin" : "user";
        button.hidden = currentRole !== "admin";
        if (currentRole !== "admin") closeSettings();
      },
    };
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
