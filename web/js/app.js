(() => {
  const POLL_CURRENT_MS = 4000;
  const POLL_HISTORY_MS = 5000;
  const MAX_POINTS = 720;

  const CARDS = [
    { key: "temperature", label: "Temperature", unit: "°C", digits: 1 },
    { key: "humidity", label: "Humidity", unit: "%", digits: 1 },
    { key: "pressure", label: "Pressure", unit: "hPa", digits: 1 },
    { key: "gas_resistance", label: "Gas resistance", unit: "kΩ", digits: 1, scale: 0.001 },
    { key: "iaq", label: "IAQ", unit: "", digits: 0 },
    { key: "iaq_accuracy", label: "IAQ accuracy", unit: "", digits: 0 },
    { key: "eco2", label: "eCO2", unit: "ppm", digits: 0 },
    { key: "bvoc", label: "bVOC", unit: "ppm", digits: 3 },
  ];

  const CHARTS = [
    { key: "temperature", label: "Temperature", unit: "°C" },
    { key: "humidity", label: "Humidity", unit: "%" },
    { key: "pressure", label: "Pressure", unit: "hPa" },
    { key: "gas_resistance", label: "Gas resistance", unit: "Ω" },
    { key: "iaq", label: "IAQ", unit: "IAQ" },
    { key: "eco2", label: "eCO2", unit: "ppm" },
    { key: "bvoc", label: "bVOC", unit: "ppm" },
  ];

  const state = {
    lastTs: 0,
    historyCount: 0,
    charts: {},
    timerCurrent: null,
    timerHistory: null,
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
    if (!ts) return "—";
    return new Date(ts * 1000).toLocaleString();
  }

  function stateClass(kind) {
    if (kind === "ok" || kind === "healthy") return "state-ok";
    if (kind === "warning" || kind === "degraded") return "state-warn";
    if (kind === "critical" || kind === "failed" || kind === "unavailable" || kind === "error") return "state-crit";
    return "state-unknown";
  }

  function accuracyText(value) {
    return ({ 0: "stabilizing", 1: "low", 2: "medium", 3: "high" })[value] || "—";
  }

  async function getJson(url) {
    const response = await fetch(url, { cache: "no-store" });
    if (response.status === 401) {
      document.body.innerHTML = "<main style='padding:40px'><h1>Authentication required</h1><p>Reload and sign in.</p></main>";
      throw new Error("unauthorized");
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function renderCards() {
    const root = $("value-cards");
    root.innerHTML = "";
    for (const spec of CARDS) {
      const el = document.createElement("article");
      el.className = "value-card";
      el.id = `card-${spec.key}`;
      el.innerHTML = `<h3>${spec.label}</h3><p class="value" id="val-${spec.key}">—</p><p class="unit">${spec.unit}</p><p class="sub" id="sub-${spec.key}"></p>`;
      root.appendChild(el);
    }
  }

  function updateCards(current) {
    for (const spec of CARDS) {
      const raw = current ? current[spec.key] : null;
      const node = $(`val-${spec.key}`);
      if (spec.key === "iaq_accuracy") {
        node.textContent = raw === null || raw === undefined ? "—" : `${raw} (${accuracyText(raw)})`;
      } else {
        node.textContent = fmt(raw, spec.digits, spec.scale || 1);
      }
    }
    const subIaq = $("sub-iaq");
    if (subIaq) subIaq.textContent = current && current.iaq_accuracy_label ? `accuracy ${current.iaq_accuracy_label}` : "";
  }

  function makeChart(canvas, label) {
    return new Chart(canvas, {
      type: "line",
      data: { datasets: [{ label, data: [], borderColor: "#6cb6ff", backgroundColor: "rgba(108,182,255,0.12)", fill: true, pointRadius: 0, borderWidth: 2, tension: 0.25 }] },
      options: {
        animation: false,
        responsive: true,
        maintainAspectRatio: false,
        parsing: false,
        normalized: true,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            type: "linear",
            ticks: {
              color: "#93a0b5",
              maxTicksLimit: 6,
              callback: (value) => new Date(value).toLocaleTimeString(),
            },
            grid: { color: "rgba(42,54,72,0.65)" },
          },
          y: { ticks: { color: "#93a0b5", maxTicksLimit: 5 }, grid: { color: "rgba(42,54,72,0.65)" } },
        },
      },
    });
  }

  function renderCharts() {
    const root = $("charts");
    root.innerHTML = "";
    for (const spec of CHARTS) {
      const card = document.createElement("article");
      card.className = "chart-card";
      card.innerHTML = `<h3>${spec.label} <span class="unit">${spec.unit}</span></h3><canvas id="chart-${spec.key}"></canvas>`;
      root.appendChild(card);
      const canvas = card.querySelector("canvas");
      state.charts[spec.key] = makeChart(canvas, spec.label);
    }
  }

  function resetCharts() {
    state.lastTs = 0;
    for (const chart of Object.values(state.charts)) {
      chart.data.datasets[0].data = [];
      chart.update("none");
    }
  }

  function appendSamples(samples) {
    if (!samples.length) return;
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
    const windowSec = Number($("history-window").value);
    const cutoff = Date.now() - windowSec * 1000;
    for (const chart of Object.values(state.charts)) {
      const series = chart.data.datasets[0].data;
      const idx = series.findIndex((p) => p.x >= cutoff);
      if (idx > 0) series.splice(0, idx);
      chart.update("none");
    }
  }

  function setText(id, text, cls) {
    const node = $(id);
    node.textContent = text;
    node.className = `big ${cls || ""}`;
  }

  async function pollCurrent() {
    try {
      const [status, current, system] = await Promise.all([
        getJson("/api/status"),
        getJson("/api/current"),
        getJson("/api/system"),
      ]);
      setText("server-status", "online", "state-ok");
      $("app-uptime").textContent = `app uptime ${Math.round(status.uptime_seconds || 0)}s`;
      const sensorState = status.sensor.status;
      setText("sensor-status", sensorState, stateClass(sensorState));
      const age = status.sensor.age_seconds;
      $("sensor-age").textContent = age == null ? "no sample yet" : `last sample ${Math.round(age)}s ago · ${localTime(status.last_measurement_timestamp)}`;
      $("cpu-temp").textContent = system.cpu_temperature_c == null ? "—" : `${system.cpu_temperature_c.toFixed(1)} °C`;
      $("cpu-temp").className = `big ${system.cpu_temperature_c >= 80 ? "state-crit" : system.cpu_temperature_c >= 70 ? "state-warn" : "state-ok"}`;
      $("cpu-load").textContent = `CPU ${fmt(system.cpu_usage_percent, 0)}% · load ${fmt(system.cpu_load_1m, 2)} · ${fmt(system.cpu_frequency_mhz, 0)} MHz`;
      $("ram-usage").textContent = system.ram_usage_percent == null ? "—" : `${system.ram_usage_percent.toFixed(0)}%`;
      $("ram-usage").className = `big ${system.ram_usage_percent >= 85 ? "state-crit" : system.ram_usage_percent >= 70 ? "state-warn" : "state-ok"}`;
      $("ram-detail").textContent = `${fmtBytes(system.ram_used_bytes)} used / ${fmtBytes(system.ram_total_bytes)}`;
      $("history-info").textContent = `${status.history.samples} samples in RAM · dropped ${status.history.dropped_oldest}`;
      if (status.history.samples < state.historyCount) resetCharts();
      state.historyCount = status.history.samples;
      updateCards(current.available ? current : null);
    } catch (err) {
      if (err.message !== "unauthorized") {
        setText("server-status", "unreachable", "state-crit");
      }
    }
  }

  async function pollHistory(initial) {
    try {
      const windowSec = Number($("history-window").value);
      const url = initial || state.lastTs === 0
        ? `/api/history?seconds=${windowSec}&limit=${MAX_POINTS}`
        : `/api/history?since=${state.lastTs}&limit=200`;
      const payload = await getJson(url);
      if (initial) resetCharts();
      appendSamples(payload.samples || []);
    } catch (_err) {
      /* keep last chart; next poll retries */
    }
  }

  function tickClock() {
    $("local-clock").textContent = new Date().toLocaleTimeString();
  }

  function start() {
    renderCards();
    renderCharts();
    tickClock();
    setInterval(tickClock, 1000);
    pollCurrent();
    pollHistory(true);
    state.timerCurrent = setInterval(pollCurrent, POLL_CURRENT_MS);
    state.timerHistory = setInterval(() => pollHistory(false), POLL_HISTORY_MS);
    $("history-window").addEventListener("change", () => pollHistory(true));
  }

  start();
})();
