(() => {
  const TRANSLATIONS = {
    CZ: {
      "app.title": "server-meter",
      "app.name": "server-meter",
      "app.eyebrow": "Raspberry Pi 5 · BME690 · pouze RAM",

      "banner.default_password_html":
        "Je aktivní výchozí heslo. Změňte heslo v souboru <code>/etc/server-meter/config.yaml</code> a poté spusťte <code>sudo systemctl restart server-meter</code>.",

      "dashboard.server": "Server",
      "dashboard.sensor": "Senzor",
      "dashboard.cpu": "CPU",
      "dashboard.ram": "RAM",
      "dashboard.current_values": "Aktuální hodnoty",
      "dashboard.history": "Historie (RAM)",
      "dashboard.history_window": "Okno",
      "dashboard.history_hint":
        "Grafy jsou po každém restartu prázdné. Vzorky se na SD kartu nikdy nezapisují.",
      "dashboard.footer_time": "Interně časová razítka UTC · v prohlížeči místní čas",
      "dashboard.clock_placeholder": "--:--:--",

      "nav.logout": "Odhlásit",

      "sensor.temperature": "Teplota",
      "sensor.humidity": "Vlhkost",
      "sensor.pressure": "Tlak",
      "sensor.gas_resistance": "Odpor plynu",
      "sensor.iaq": "IAQ",
      "sensor.iaq_accuracy": "Přesnost IAQ",
      "sensor.static_iaq": "Statické IAQ",
      "sensor.static_iaq_accuracy": "Přesnost statického IAQ",
      "sensor.eco2": "eCO₂",
      "sensor.bvoc": "bVOC",
      "sensor.accuracy_sub": "přesnost {label}",
      "sensor.last_sample": "poslední měření před {age}s · {time}",
      "sensor.no_sample": "zatím žádné měření",
      "sensor.unavailable_message": "Senzor není dostupný.",

      "system.uptime_placeholder": "doba běhu —",
      "system.app_host_uptime": "aplikace {app} · host {host}",
      "duration.seconds": "{n} s",
      "duration.minutes": "{n} min",
      "duration.hours": "{n} h",
      "duration.days": "{n} d",

      "help.icon_label": "Vysvětlení hodnoty",
      "sensor.help.gas_resistance": "Odpor plynu měřený senzorem BME690 v ohmech. Podle Bosch BSEC se odpor mění s koncentrací VOC: čím vyšší koncentrace redukujících VOC, tím nižší odpor, a naopak.",
      "sensor.help.iaq": "Index for Air Quality (IAQ) 0–500 z Bosch BSEC. Udává relativní změnu okolních TVOC detekovaných BME690. 0 je čistý vzduch, 500 silně znečištěný. Algoritmus se automaticky kalibruje na prostředí; IAQ 50 odpovídá typicky dobrému vzduchu a IAQ 200 typicky znečištěnému (datasheet BME690, tabulka 6).",
      "sensor.help.static_iaq": "Statické IAQ je podle Bosch BSEC neskalovaný odhad Index for Air Quality. Na rozdíl od IAQ se citlivost automaticky nepřizpůsobuje nedávnému prostředí, proto se hodí pro stálé umístění. Nižší hodnota znamená čistší vzduch.",
      "sensor.help.static_iaq_accuracy": "Stav kalibrace statického IAQ z Bosch BSEC (0–3): 0 senzor se stabilizuje (typicky několik minut po startu) nebo došlo k narušení časování, 1 nejistá historie pozadí, 2 kalibrace probíhá, 3 úspěšně zkalibrováno. Odhad je spolehlivější od stupně 2–3.",
      "sensor.help.eco2": "Odhad ekvivalentu CO₂ v ppm z Bosch BSEC. BME690 není čidlo CO₂, ale TVOC senzor; výstup je úměrný celkové koncentraci VOC a odhaduje ekvivalent CO₂ (typicky od cca 400 ppm) za předpokladu, že zdrojem je lidský dech.",
      "sensor.help.bvoc": "Odhad ekvivalentu dechových VOC (bVOC) v ppm z Bosch BSEC. Vychází ze statického IAQ a laboratorní směsi b-VOC (typické složení vydechovaného vzduchu, např. ethanol, aceton, isopren). Nejde o přímou chemickou identifikaci jednotlivých plynů.",
      "system.cpu_load_placeholder": "zátěž — · frekvence —",
      "system.cpu_load_meta": "CPU {cpu}% · zátěž {load} · {freq} MHz",
      "system.ram_placeholder": "použito — / —",
      "system.ram_detail": "{used} použito / {total}",

      "history.window_15m": "15 min",
      "history.window_1h": "1 hodina",
      "history.window_6h": "6 hodin",
      "history.window_24h": "24 hodin",
      "history.samples_placeholder": "0 vzorků v RAM",
      "history.samples_in_ram": "{count} vzorků v RAM · zahozeno {dropped}",

      "status.ok": "OK",
      "status.warning": "Varování",
      "status.critical": "Kritický stav",
      "status.unknown": "Neznámý stav",
      "status.online": "Online",
      "status.offline": "Offline",
      "status.unavailable": "Nedostupný",
      "status.initializing": "Inicializace",
      "status.error": "Chyba",
      "status.healthy": "V pořádku",
      "status.degraded": "Zhoršený",
      "status.failed": "Selhání",
      "status.starting": "Spouštění",
      "status.unreachable": "Nedostupný",
      "status.loading": "Načítání",

      "accuracy.stabilizing": "stabilizace",
      "accuracy.low": "nízká",
      "accuracy.medium": "střední",
      "accuracy.high": "vysoká",

      "login.title": "Přihlášení",
      "login.username": "Uživatelské jméno",
      "login.password": "Heslo",
      "login.submit": "Přihlásit",
      "login.invalid": "Nesprávné uživatelské jméno nebo heslo",
      "login.logout": "Odhlásit",

      "error.load_current": "Nepodařilo se načíst aktuální hodnoty.",
      "error.auth_required": "Vyžadováno přihlášení",
      "error.http": "HTTP {code}",
    },
    EN: {
      "app.title": "server-meter",
      "app.name": "server-meter",
      "app.eyebrow": "Raspberry Pi 5 · BME690 · RAM-only",

      "banner.default_password_html":
        "Default password is active. Please change the password in <code>/etc/server-meter/config.yaml</code> then run <code>sudo systemctl restart server-meter</code>.",

      "dashboard.server": "Server",
      "dashboard.sensor": "Sensor",
      "dashboard.cpu": "CPU",
      "dashboard.ram": "RAM",
      "dashboard.current_values": "Current values",
      "dashboard.history": "History (RAM)",
      "dashboard.history_window": "Window",
      "dashboard.history_hint":
        "Charts start empty after every reboot. Samples are never written to the SD card.",
      "dashboard.footer_time": "UTC timestamps internally · local time in the browser",
      "dashboard.clock_placeholder": "--:--:--",

      "nav.logout": "Logout",

      "sensor.temperature": "Temperature",
      "sensor.humidity": "Humidity",
      "sensor.pressure": "Pressure",
      "sensor.gas_resistance": "Gas resistance",
      "sensor.iaq": "IAQ",
      "sensor.iaq_accuracy": "IAQ accuracy",
      "sensor.static_iaq": "Static IAQ",
      "sensor.static_iaq_accuracy": "Static IAQ accuracy",
      "sensor.eco2": "eCO₂",
      "sensor.bvoc": "bVOC",
      "sensor.accuracy_sub": "accuracy {label}",
      "sensor.last_sample": "last sample {age}s ago · {time}",
      "sensor.no_sample": "no sample yet",
      "sensor.unavailable_message": "Sensor is unavailable.",

      "system.uptime_placeholder": "uptime —",
      "system.app_host_uptime": "app {app} · host {host}",
      "duration.seconds": "{n} s",
      "duration.minutes": "{n} min",
      "duration.hours": "{n} h",
      "duration.days": "{n} d",

      "help.icon_label": "Value explanation",
      "sensor.help.gas_resistance": "Gas resistance measured by the BME690 in ohms. Per Bosch BSEC, the resistance changes with VOC concentration: the higher the concentration of reducing VOCs, the lower the resistance, and vice versa.",
      "sensor.help.iaq": "Index for Air Quality (IAQ) 0–500 from Bosch BSEC. It indicates the relative change in ambient TVOCs detected by the BME690. 0 is clean air, 500 is heavily polluted air. The algorithm auto-calibrates to its environment so that IAQ 50 is typical good air and IAQ 200 is typical polluted air (BME690 datasheet, Table 6).",
      "sensor.help.static_iaq": "Static IAQ is Bosch BSEC’s unscaled Index for Air Quality estimate. Unlike IAQ, sensitivity is not auto-scaled to the recent environment, so it is intended for a fixed location. Lower values mean cleaner air.",
      "sensor.help.static_iaq_accuracy": "Bosch BSEC calibration status for static IAQ (0–3): 0 the sensor is stabilizing (typically a few minutes after start) or a timing violation occurred, 1 uncertain background history, 2 currently calibrating, 3 successfully calibrated. The estimate is more reliable from accuracy 2–3.",
      "sensor.help.eco2": "CO₂ equivalent estimate in ppm from Bosch BSEC. The BME690 is a TVOC sensor, not a CO₂ sensor; the output tracks total VOC concentration and estimates equivalent CO₂ (typically from about 400 ppm) assuming human breath as the pollution source.",
      "sensor.help.bvoc": "Breath-VOC equivalent estimate in ppm from Bosch BSEC. It is derived from static IAQ and Bosch laboratory tests with a b-VOC mixture that represents typical compounds in exhaled breath (for example ethanol, acetone and isoprene). It is not a direct chemical identification of those gases.",
      "system.cpu_load_placeholder": "load — · freq —",
      "system.cpu_load_meta": "CPU {cpu}% · load {load} · {freq} MHz",
      "system.ram_placeholder": "used — / —",
      "system.ram_detail": "{used} used / {total}",

      "history.window_15m": "15 min",
      "history.window_1h": "1 hour",
      "history.window_6h": "6 hours",
      "history.window_24h": "24 hours",
      "history.samples_placeholder": "0 samples in RAM",
      "history.samples_in_ram": "{count} samples in RAM · dropped {dropped}",

      "status.ok": "OK",
      "status.warning": "Warning",
      "status.critical": "Critical",
      "status.unknown": "Unknown",
      "status.online": "Online",
      "status.offline": "Offline",
      "status.unavailable": "Unavailable",
      "status.initializing": "Initializing",
      "status.error": "Error",
      "status.healthy": "Healthy",
      "status.degraded": "Degraded",
      "status.failed": "Failed",
      "status.starting": "Starting",
      "status.unreachable": "Unreachable",
      "status.loading": "Loading",

      "accuracy.stabilizing": "stabilizing",
      "accuracy.low": "low",
      "accuracy.medium": "medium",
      "accuracy.high": "high",

      "login.title": "Login",
      "login.username": "Username",
      "login.password": "Password",
      "login.submit": "Sign in",
      "login.invalid": "Invalid username or password",
      "login.logout": "Logout",

      "error.load_current": "Unable to load current values.",
      "error.auth_required": "Authentication required",
      "error.http": "HTTP {code}",
    },
  };

  const BROWSER_LOCALES = { CZ: "cs-CZ", EN: "en-GB" };
  const HTML_LANG = { CZ: "cs", EN: "en" };

  let locale = "CZ";

  function hasLocale(code) {
    return Object.prototype.hasOwnProperty.call(TRANSLATIONS, code);
  }

  function setLocale(code) {
    const normalized = String(code || "CZ").trim().toUpperCase();
    locale = hasLocale(normalized) ? normalized : "CZ";
    const root = globalThis.document && document.documentElement;
    if (root) {
      root.lang = HTML_LANG[locale];
      root.dataset.locale = locale;
    }
    return locale;
  }

  function dict() {
    return TRANSLATIONS[locale] || TRANSLATIONS.CZ;
  }

  function t(key, params) {
    const table = dict();
    let text = table[key];
    if (text === undefined) {
      text = TRANSLATIONS.EN[key] || TRANSLATIONS.CZ[key] || key;
    }
    if (params) {
      text = text.replace(/\{(\w+)\}/g, (_, name) => (
        params[name] === undefined || params[name] === null ? `{${name}}` : String(params[name])
      ));
    }
    return text;
  }

  function formatDateTime(date) {
    const d = date instanceof Date ? date : new Date(date);
    if (Number.isNaN(d.getTime())) return "—";
    const parts = new Intl.DateTimeFormat(BROWSER_LOCALES[locale], {
      day: "numeric",
      month: locale === "CZ" ? "numeric" : "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      hourCycle: "h23",
    }).formatToParts(d);
    const get = (type) => (parts.find((part) => part.type === type) || {}).value || "";
    const time = `${get("hour")}:${get("minute")}:${get("second")}`;
    if (locale === "CZ") {
      return `${get("day")}. ${get("month")}. ${get("year")} ${time}`;
    }
    return `${get("day")} ${get("month")} ${get("year")} ${time}`;
  }

  function formatTime(date) {
    const d = date instanceof Date ? date : new Date(date);
    if (Number.isNaN(d.getTime())) return "—";
    return new Intl.DateTimeFormat(BROWSER_LOCALES[locale], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      hourCycle: "h23",
    }).format(d);
  }

  function formatDateTimeFromTs(ts) {
    if (!ts) return "—";
    return formatDateTime(new Date(Number(ts) * 1000));
  }

  function formatDuration(totalSeconds) {
    if (totalSeconds === null || totalSeconds === undefined || Number.isNaN(Number(totalSeconds))) {
      return "—";
    }
    let seconds = Math.max(0, Math.round(Number(totalSeconds)));
    const days = Math.floor(seconds / 86400);
    seconds %= 86400;
    const hours = Math.floor(seconds / 3600);
    seconds %= 3600;
    const minutes = Math.floor(seconds / 60);
    seconds %= 60;
    const parts = [];
    if (days) parts.push(t("duration.days", { n: days }));
    if (hours) parts.push(t("duration.hours", { n: hours }));
    if (minutes && !days) parts.push(t("duration.minutes", { n: minutes }));
    if ((!days && !hours && (seconds || parts.length === 0)) || parts.length === 0) {
      parts.push(t("duration.seconds", { n: seconds }));
    }
    return parts.slice(0, 2).join(" ");
  }

  function apply(root) {
    const scope = root || (globalThis.document && document);
    if (!scope || !scope.querySelectorAll) return;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.getAttribute("data-i18n"));
    });
    scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
      el.innerHTML = t(el.getAttribute("data-i18n-html"));
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      el.setAttribute("placeholder", t(el.getAttribute("data-i18n-placeholder")));
    });
    scope.querySelectorAll("[data-i18n-aria]").forEach((el) => {
      el.setAttribute("aria-label", t(el.getAttribute("data-i18n-aria")));
    });
    if (globalThis.document) {
      document.title = t("app.title");
    }
  }

  function bootFromDocument() {
    const fromHtml = globalThis.document && document.documentElement
      && document.documentElement.dataset
      && document.documentElement.dataset.locale;
    setLocale(fromHtml || "CZ");
    apply();
  }

  const api = {
    translations: TRANSLATIONS,
    t,
    setLocale,
    getLocale: () => locale,
    apply,
    formatDateTime,
    formatTime,
    formatDateTimeFromTs,
    formatDuration,
    browserLocale: () => BROWSER_LOCALES[locale],
  };

  globalThis.ServerMeterI18n = api;
  if (globalThis.document) {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", bootFromDocument);
    } else {
      bootFromDocument();
    }
  }
})();
