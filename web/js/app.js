(() => {
  const POLL_CURRENT_MS = 4000;
  const POLL_HISTORY_MS = 5000;
  const MAX_POINTS = 720;
  const AUTH_STORAGE_KEY = "server-meter.basic";
  const i18n = window.ServerMeterI18n;
  const t = (key, params) => i18n.t(key, params);

  const CARDS = [
    { key: "temperature", labelKey: "sensor.temperature", unit: "°C", digits: 1 },
    { key: "humidity", labelKey: "sensor.humidity", unit: "%", digits: 1 },
    { key: "pressure", labelKey: "sensor.pressure", unit: "hPa", digits: 1 },
    { key: "gas_resistance", labelKey: "sensor.gas_resistance", helpKey: "sensor.help.gas_resistance", unit: "kΩ", digits: 1, scale: 0.001 },
    { key: "iaq", labelKey: "sensor.iaq", helpKey: "sensor.help.iaq", unit: "", digits: 0 },
    { key: "iaq_accuracy", labelKey: "sensor.iaq_accuracy", unit: "", digits: 0 },
    { key: "static_iaq", labelKey: "sensor.static_iaq", helpKey: "sensor.help.static_iaq", unit: "", digits: 0 },
    { key: "static_iaq_accuracy", labelKey: "sensor.static_iaq_accuracy", helpKey: "sensor.help.static_iaq_accuracy", unit: "", digits: 0 },
    { key: "eco2", labelKey: "sensor.eco2", helpKey: "sensor.help.eco2", unit: "ppm", digits: 0 },
    { key: "bvoc", labelKey: "sensor.bvoc", helpKey: "sensor.help.bvoc", unit: "ppm", digits: 3 },
    { key: "tvoc", labelKey: "sensor.tvoc", helpKey: "sensor.help.tvoc", unit: "ppb", digits: 0 },
  ];

  const CHARTS = [
    { key: "temperature", labelKey: "sensor.temperature", unit: "°C" },
    { key: "humidity", labelKey: "sensor.humidity", unit: "%" },
    { key: "pressure", labelKey: "sensor.pressure", unit: "hPa" },
    { key: "gas_resistance", labelKey: "sensor.gas_resistance", helpKey: "sensor.help.gas_resistance", unit: "Ω" },
    { key: "iaq", labelKey: "sensor.iaq", helpKey: "sensor.help.iaq", unit: "IAQ" },
    { key: "static_iaq", labelKey: "sensor.static_iaq", helpKey: "sensor.help.static_iaq", unit: "IAQ" },
    { key: "eco2", labelKey: "sensor.eco2", helpKey: "sensor.help.eco2", unit: "ppm" },
    { key: "bvoc", labelKey: "sensor.bvoc", helpKey: "sensor.help.bvoc", unit: "ppm" },
    { key: "tvoc", labelKey: "sensor.tvoc", helpKey: "sensor.help.tvoc", unit: "ppb" },
    { key: "cpu_temperature", labelKey: "system.cpu_temperature", unit: "°C" },
    { key: "cpu_load", labelKey: "system.cpu_load", unit: "%" },
    { key: "ram_usage", labelKey: "system.ram_usage", unit: "%" },
  ];

  const HEALTH_ITEMS = [
    { key: "bme690", labelKey: "health.bme690" },
    { key: "bsec", labelKey: "health.bsec" },
    { key: "i2c", labelKey: "health.i2c" },
    { key: "sensor_data", labelKey: "health.sensor_data" },
    { key: "smtp", labelKey: "health.smtp" },
    { key: "ram_protection", labelKey: "health.ram_protection" },
    { key: "web_api", labelKey: "health.web_api" },
  ];

  const state = {
    lastTs: 0,
    historyCount: 0,
    lastRole: null,
    charts: {},
    timerCurrent: null,
    timerHistory: null,
    dashboardReady: false,
  };

  const $ = (id) => document.getElementById(id);

  function fmt(value, digits = 1, scale = 1) {
    if (value === null || value === undefined || Number.isNaN(value)) return "—";
    return (Number(value) * scale).toFixed(digits);
  }

  function fmtBytes(bytes) {
    if (!bytes && bytes !== 0) return "—";
    const gb = bytes / (1024 ** 3);
    return `${gb.toFixed(2)} GiB`;
  }

  function localTime(ts) {
    return i18n.formatDateTimeFromTs(ts);
  }

  function stateClass(kind) {
    if (kind === "ok" || kind === "healthy" || kind === "online") return "state-ok";
    if (kind === "warning" || kind === "degraded") return "state-warn";
    if (kind === "critical" || kind === "failed" || kind === "unavailable" || kind === "error" || kind === "unreachable") {
      return "state-crit";
    }
    return "state-unknown";
  }

  function statusText(kind) {
    if (!kind) return t("status.unknown");
    const key = `status.${kind}`;
    const translated = t(key);
    return translated === key ? String(kind) : translated;
  }

  function accuracyText(value) {
    return ({
      0: t("accuracy.stabilizing"),
      1: t("accuracy.low"),
      2: t("accuracy.medium"),
      3: t("accuracy.high"),
    })[value] || "—";
  }

  function authHeader() {
    const token = sessionStorage.getItem(AUTH_STORAGE_KEY);
    return token ? { Authorization: `Basic ${token}` } : {};
  }

  function storeAuth(username, password) {
    sessionStorage.setItem(AUTH_STORAGE_KEY, btoa(`${username}:${password}`));
  }

  function clearAuth() {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store", headers: authHeader() });
    if (response.status === 401) {
      const err = new Error("unauthorized");
      err.code = 401;
      throw err;
    }
    if (!response.ok) throw new Error(t("error.http", { code: response.status }));
    return response.json();
  }

  function closeInfoTips(except) {
    document.querySelectorAll(".info-tip.is-open").forEach((el) => {
      if (el !== except) el.classList.remove("is-open");
    });
  }

  function appendInfoIcon(parent, helpKey) {
    if (!helpKey) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "info-tip";
    btn.setAttribute("aria-label", t("help.icon_label"));
    const mark = document.createElement("span");
    mark.className = "info-tip-mark";
    mark.textContent = "i";
    const bubble = document.createElement("span");
    bubble.className = "info-tip-bubble";
    bubble.setAttribute("role", "tooltip");
    bubble.textContent = t(helpKey);
    btn.append(mark, bubble);
    btn.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const open = btn.classList.contains("is-open");
      closeInfoTips(btn);
      btn.classList.toggle("is-open", !open);
    });
    parent.append(btn);
  }

  function renderCards() {
    const root = $("value-cards");
    root.innerHTML = "";
    for (const spec of CARDS) {
      const el = document.createElement("article");
      el.className = "value-card";
      el.id = `card-${spec.key}`;
      const heading = document.createElement("h3");
      heading.append(document.createTextNode(t(spec.labelKey)));
      appendInfoIcon(heading, spec.helpKey);
      const value = document.createElement("p");
      value.className = "value";
      value.id = `val-${spec.key}`;
      value.textContent = "—";
      const unit = document.createElement("p");
      unit.className = "unit";
      unit.textContent = spec.unit;
      const sub = document.createElement("p");
      sub.className = "sub";
      sub.id = `sub-${spec.key}`;
      el.append(heading, value, unit, sub);
      root.appendChild(el);
    }
  }

  function updateCards(current) {
    for (const spec of CARDS) {
      const raw = current ? current[spec.key] : null;
      const node = $(`val-${spec.key}`);
      if (spec.key === "iaq_accuracy" || spec.key === "static_iaq_accuracy") {
        node.textContent = raw === null || raw === undefined ? "—" : `${raw} (${accuracyText(raw)})`;
      } else {
        node.textContent = fmt(raw, spec.digits, spec.scale || 1);
      }
    }
    const subIaq = $("sub-iaq");
    if (subIaq) {
      subIaq.textContent = current && current.iaq_accuracy !== null && current.iaq_accuracy !== undefined
        ? t("sensor.accuracy_sub", { label: accuracyText(current.iaq_accuracy) })
        : "";
    }
  }

  function makeChart(canvas, label) {
    return new Chart(canvas, {
      type: "line",
      data: { datasets: [{ label, data: [], borderColor: "#6cb6ff", backgroundColor: "rgba(108,182,255,0.12)", fill: true, pointRadius: 0, borderWidth: 2, tension: 0.25 }] },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        resizeDelay: 50,
        parsing: false,
        normalized: true,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: "linear",
            ticks: {
              color: "#93a0b5",
              maxTicksLimit: 6,
              callback: (value) => i18n.formatTime(new Date(value)),
            },
            grid: { color: "rgba(42,54,72,0.65)" },
          },
          y: { ticks: { color: "#93a0b5", maxTicksLimit: 5 }, grid: { color: "rgba(42,54,72,0.65)" } },
        },
      },
    });
  }

  function destroyCharts() {
    for (const chart of Object.values(state.charts)) {
      chart.destroy();
    }
    state.charts = {};
  }

  function renderCharts() {
    const root = $("charts");
    root.innerHTML = "";
    destroyCharts();
    for (const spec of CHARTS) {
      const card = document.createElement("article");
      card.className = "chart-card";
      const title = document.createElement("h3");
      title.append(document.createTextNode(`${t(spec.labelKey)} `));
      const unit = document.createElement("span");
      unit.className = "unit";
      unit.textContent = spec.unit;
      title.append(unit);
      appendInfoIcon(title, spec.helpKey);
      const frame = document.createElement("div");
      frame.className = "chart-frame";
      const canvas = document.createElement("canvas");
      canvas.id = `chart-${spec.key}`;
      frame.append(canvas);
      card.append(title, frame);
      root.appendChild(card);
      state.charts[spec.key] = makeChart(canvas, t(spec.labelKey));
    }
  }

  function resetCharts() {
    state.lastTs = 0;
    for (const chart of Object.values(state.charts)) {
      chart.data.datasets[0].data = [];
      chart.update("none");
    }
  }

  function downsampleEven(samples, maxPoints) {
    const n = samples.length;
    if (n <= maxPoints) return samples;
    const out = [];
    const seen = new Set();
    for (let i = 0; i < maxPoints; i += 1) {
      const idx = Math.round((i * (n - 1)) / (maxPoints - 1));
      if (seen.has(idx)) continue;
      seen.add(idx);
      out.push(samples[idx]);
    }
    return out;
  }

  function appendSamples(samples) {
    if (!samples.length) return;
    if (samples.length > MAX_POINTS) samples = downsampleEven(samples, MAX_POINTS);
    for (const sample of samples) {
      const x = sample.timestamp * 1000;
      for (const spec of CHARTS) {
        const y = sample[spec.key];
        if (y === null || y === undefined) continue;
        const series = state.charts[spec.key].data.datasets[0].data;
        series.push({ x, y });
        if (series.length > MAX_POINTS) series.splice(0, series.length - MAX_POINTS);
      }
      if (sample.timestamp > state.lastTs) state.lastTs = sample.timestamp;
    }
    const windowVal = $("history-window").value;
    if (windowVal !== "all") {
      const cutoff = Date.now() - Number(windowVal) * 1000;
      for (const chart of Object.values(state.charts)) {
        const series = chart.data.datasets[0].data;
        const idx = series.findIndex((p) => p.x >= cutoff);
        if (idx > 0) series.splice(0, idx);
      }
    }
    for (const chart of Object.values(state.charts)) {
      chart.update("none");
    }
    const empty = $("history-empty");
    if (empty) {
      const any = Object.values(state.charts).some((chart) => chart.data.datasets[0].data.length);
      empty.hidden = any;
    }
  }

  function fmtMem(bytes) {
    if (!bytes && bytes !== 0) return "—";
    return `${(Number(bytes) / (1024 * 1024)).toFixed(1)} MB`;
  }

  function renderHealth(payload) {
    const root = $("health-grid");
    const overall = $("system-health-overall");
    if (!root || !payload) return;
    const items = payload.items || {};
    root.innerHTML = "";
    for (const spec of HEALTH_ITEMS) {
      const item = items[spec.key] || {};
      const row = document.createElement("div");
      row.className = "health-row";
      const label = document.createElement("span");
      label.textContent = t(spec.labelKey);
      const value = document.createElement("span");
      const status = item.status || "unknown";
      value.className = stateClass(status);
      if (spec.key === "sensor_data" && item.age_seconds != null) {
        value.textContent = t("health.sensor_age", { age: Math.round(item.age_seconds) });
      } else if (spec.key === "i2c" && item.bus) {
        value.textContent = `${statusText(status)} · ${item.bus} · ${item.address || ""}`;
      } else if (spec.key === "bsec" && item.version) {
        value.textContent = `${statusText(status)} · ${item.version}`;
      } else {
        value.textContent = statusText(status === "off" ? "off" : status);
      }
      row.append(label, value);
      root.appendChild(row);
    }
    const word = (payload.overall || "unknown").toUpperCase();
    overall.textContent = word;
    overall.className = `health-overall ${stateClass(payload.overall)}`;
  }

  function renderAlerts(alarms) {
    const root = $("active-alerts");
    if (!root) return;
    root.innerHTML = "";
    const entries = Object.entries(alarms || {}).filter(([, alarm]) => {
      return alarm && (alarm.state === "WARNING" || alarm.state === "CRITICAL" || alarm.state === "NORMAL");
    });
    const active = entries.filter(([, alarm]) => alarm.state === "WARNING" || alarm.state === "CRITICAL");
    if (!active.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = t("dashboard.no_alerts");
      root.appendChild(empty);
      return;
    }
    for (const [name, alarm] of active) {
      const card = document.createElement("article");
      card.className = `alert-card ${stateClass(alarm.state.toLowerCase())}`;
      const kind = document.createElement("p");
      kind.className = "alert-kind";
      kind.textContent = alarm.state;
      const metric = document.createElement("h3");
      metric.textContent = t(`settings.metric.${name}`) === `settings.metric.${name}` ? name : t(`settings.metric.${name}`);
      const value = document.createElement("p");
      value.className = "alert-value";
      value.textContent = alarm.value == null ? "—" : `${alarm.value} ${alarm.unit || ""}`.trim();
      const since = document.createElement("p");
      since.className = "meta";
      since.textContent = alarm.since ? t("dashboard.since", { time: localTime(alarm.since) }) : "";
      card.append(kind, metric, value, since);
      root.appendChild(card);
    }
  }

  function renderAlarmHistory(rows) {
    const body = $("alarm-history-body");
    if (!body) return;
    body.innerHTML = "";
    if (!rows || !rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 4;
      td.textContent = t("alarms.empty");
      tr.appendChild(td);
      body.appendChild(tr);
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      const time = document.createElement("td");
      time.textContent = localTime(row.created_at);
      const kind = document.createElement("td");
      kind.textContent = row.kind;
      kind.className = stateClass(String(row.kind).toLowerCase() === "recovery" ? "ok" : String(row.kind).toLowerCase());
      const metric = document.createElement("td");
      const key = `settings.metric.${row.metric}`;
      metric.textContent = t(key) === key ? row.metric : t(key);
      const value = document.createElement("td");
      value.textContent = row.value == null ? "—" : `${row.value} ${row.unit || ""}`.trim();
      tr.append(time, kind, metric, value);
      body.appendChild(tr);
    }
  }

  function setText(id, text, cls) {
    const node = $(id);
    node.textContent = text;
    node.className = `big ${cls || ""}`;
  }

  function setValuesError(message) {
    const node = $("values-error");
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.textContent = message;
  }

  function showLogin(message) {
    stopPolling();
    $("app").hidden = true;
    $("login-overlay").hidden = false;
    const err = $("login-error");
    if (message) {
      err.hidden = false;
      err.textContent = message;
    } else {
      err.hidden = true;
      err.textContent = "";
    }
    $("login-password").value = "";
    $("login-username").focus();
  }

  function showDashboard() {
    $("login-overlay").hidden = true;
    $("app").hidden = false;
    if (!state.dashboardReady) {
      renderCards();
      renderCharts();
      $("history-window").addEventListener("change", () => pollHistory(true));
      state.dashboardReady = true;
    }
    startPolling();
  }

  async function pollCurrent() {
    try {
      const [status, current, system] = await Promise.all([
        getJson("/api/status"),
        getJson("/api/current"),
        getJson("/api/system"),
      ]);
      if (status.application && status.application.locale) {
        i18n.setLocale(status.application.locale);
      }
      const banner = $("password-banner");
      const role = status.current_user && status.current_user.role === "admin" ? "admin" : "user";
      if (state.lastRole !== role) {
        state.lastRole = role;
        if (window.ServerMeterSettings && window.ServerMeterSettings.setRole) {
          window.ServerMeterSettings.setRole(role);
        } else {
          const gear = $("settings-button");
          if (gear) gear.hidden = role !== "admin";
        }
      }
      if (banner) {
        banner.hidden = !(status.application.default_password_active && role === "admin");
      }
      const logout = $("logout-button");
      if (logout) {
        logout.hidden = !status.application.auth_enabled;
      }
      setText("server-status", statusText("online"), "state-ok");
      $("app-uptime").textContent = t("system.app_host_uptime", {
        app: i18n.formatDuration(status.uptime_seconds),
        host: i18n.formatDuration(system.uptime_seconds),
      });
      const sensorState = status.sensor.status;
      setText("sensor-status", statusText(sensorState), stateClass(sensorState));
      const age = status.sensor.age_seconds;
      $("sensor-age").textContent = age == null
        ? t("sensor.no_sample")
        : t("sensor.last_sample", { age: Math.round(age), time: localTime(status.last_measurement_timestamp) });
      $("cpu-temp").textContent = system.cpu_temperature_c == null ? "—" : `${system.cpu_temperature_c.toFixed(1)} °C`;
      $("cpu-temp").className = `big ${system.cpu_temperature_c >= 80 ? "state-crit" : system.cpu_temperature_c >= 70 ? "state-warn" : "state-ok"}`;
      $("cpu-load").textContent = t("system.cpu_load_meta", {
        cpu: fmt(system.cpu_usage_percent, 0),
        load: fmt(system.cpu_load_1m, 2),
        freq: fmt(system.cpu_frequency_mhz, 0),
      });
      $("ram-usage").textContent = system.ram_usage_percent == null ? "—" : `${system.ram_usage_percent.toFixed(0)}%`;
      $("ram-usage").className = `big ${system.ram_usage_percent >= 85 ? "state-crit" : system.ram_usage_percent >= 70 ? "state-warn" : "state-ok"}`;
      $("ram-detail").textContent = t("system.ram_detail", {
        used: fmtBytes(system.ram_used_bytes),
        total: fmtBytes(system.ram_total_bytes),
      });
      const ramBanner = $("ram-banner");
      if (ramBanner) {
        const pressure = status.memory && status.memory.pressure;
        ramBanner.hidden = !(pressure && pressure !== "normal");
      }
      renderHealth(status.system_health);
      renderAlerts(status.alarms);
      pollAlarmHistory();
      $("history-info").textContent = t("history.samples_in_ram", {
        count: status.history.samples,
        max: status.history.max_samples,
        dropped: status.history.dropped_oldest,
        memory: fmtMem(status.history.memory_bytes),
        oldest: status.history.oldest_age_seconds == null ? "—" : i18n.formatDuration(status.history.oldest_age_seconds),
        newest: status.history.newest_age_seconds == null ? "—" : i18n.formatDuration(status.history.newest_age_seconds),
      });
      if (status.history.samples < state.historyCount) resetCharts();
      state.historyCount = status.history.samples;
      if (current.available) {
        setValuesError("");
        updateCards(current);
      } else {
        setValuesError(t("sensor.unavailable_message"));
        updateCards(null);
      }
    } catch (err) {
      if (err.code === 401) {
        clearAuth();
        showLogin(t("login.invalid"));
        return;
      }
      setText("server-status", statusText("unreachable"), "state-crit");
      setValuesError(t("error.load_current"));
    }
  }

  async function pollHistory(initial) {
    try {
      const windowVal = $("history-window").value;
      let url;
      if (windowVal === "all") {
        url = (initial || state.lastTs === 0)
          ? `/api/history?max_points=${MAX_POINTS}`
          : `/api/history?since=${state.lastTs}&limit=200`;
      } else {
        const windowSec = Number(windowVal);
        url = initial || state.lastTs === 0
          ? `/api/history?seconds=${windowSec}&max_points=${MAX_POINTS}`
          : `/api/history?since=${state.lastTs}&limit=200`;
      }
      const payload = await getJson(url);
      if (initial) resetCharts();
      appendSamples(payload.samples || []);
    } catch (err) {
      if (err.code === 401) {
        clearAuth();
        showLogin(t("login.invalid"));
      }
    }
  }

  function tickClock() {
    $("local-clock").textContent = i18n.formatTime(new Date());
  }

  function stopPolling() {
    if (state.timerCurrent) {
      clearInterval(state.timerCurrent);
      state.timerCurrent = null;
    }
    if (state.timerHistory) {
      clearInterval(state.timerHistory);
      state.timerHistory = null;
    }
  }

  function startPolling() {
    stopPolling();
    pollCurrent();
    pollHistory(true);
    pollAlarmHistory();
    state.timerCurrent = setInterval(pollCurrent, POLL_CURRENT_MS);
    state.timerHistory = setInterval(() => pollHistory(false), POLL_HISTORY_MS);
  }

  async function pollAlarmHistory() {
    try {
      const payload = await getJson("/api/alarms/history?limit=50");
      renderAlarmHistory(payload.alarms || []);
    } catch (_err) {
      // History table is optional; dashboard values still update.
    }
  }

  async function tryExistingSession() {
    try {
      await getJson("/api/status");
      return true;
    } catch (err) {
      if (err.code === 401) return false;
      return true;
    }
  }

  async function onLoginSubmit(event) {
    event.preventDefault();
    const username = $("login-username").value;
    const password = $("login-password").value;
    storeAuth(username, password);
    try {
      await getJson("/api/status");
      showDashboard();
    } catch (err) {
      clearAuth();
      showLogin(err.code === 401 ? t("login.invalid") : t("error.load_current"));
    }
  }

  function onLogout() {
    clearAuth();
    stopPolling();
    state.lastRole = null;
    showLogin("");
  }

  async function start() {
    i18n.setLocale(document.documentElement.dataset.locale || "CZ");
    i18n.apply();
    tickClock();
    setInterval(tickClock, 1000);
    $("login-form").addEventListener("submit", onLoginSubmit);
    $("logout-button").addEventListener("click", onLogout);
    document.addEventListener("click", () => closeInfoTips());
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeInfoTips();
    });
    const ok = await tryExistingSession();
    if (ok) showDashboard();
    else showLogin("");
  }

  start();
})();
