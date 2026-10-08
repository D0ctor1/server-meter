(() => {
  const TRANSLATIONS = {
    CZ: {
      "app.title": "server-meter",
      "app.name": "server-meter",
      "app.eyebrow": "Raspberry Pi 5 · BME690 · pouze RAM",

      "banner.default_password_html":
        "Je aktivní výchozí heslo. Změňte je v Nastavení → Uživatelé.",

      "dashboard.server": "Server",
      "dashboard.sensor": "Senzor",
      "dashboard.cpu": "CPU",
      "dashboard.ram": "RAM",
      "dashboard.system_health": "SYSTEM HEALTH",
      "dashboard.active_alerts": "Aktivní alarmy",
      "dashboard.alarm_history": "Historie alarmů",
      "dashboard.no_alerts": "Žádné aktivní alarmy",
      "dashboard.since": "od {time}",
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
      "sensor.tvoc": "TVOC",
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
      "sensor.help.bvoc": "Odhad ekvivalentu dechových VOC (bVOC) v ppm z Bosch BSEC. Vychází ze statického IAQ a laboratorní směsi b-VOC (typické složení vydechovaného vzduchu, např. ethanol, aceton, isopren). Nejde o přímou chemickou identifikaci jednotlivých plynů. BSEC 3.3 IAQ tento výstup často neodebírá.",
      "sensor.help.tvoc": "TVOC equivalent z Bosch BSEC 3.x v ppb (id 31). Oficiální IAQ příklad BSEC 3.3.0.1 odebírá TVOC v LP režimu. Není to totéž co bVOC (id 4, ppm) a není to náhrada z IAQ, eCO₂ ani odporu plynu.",
      "system.cpu_load_placeholder": "zátěž — · frekvence —",
      "system.cpu_load_meta": "CPU {cpu}% · zátěž {load} · {freq} MHz",
      "system.ram_placeholder": "použito — / —",
      "system.ram_detail": "{used} použito / {total}",

      "history.window_15m": "15 min",
      "history.window_1h": "1 hodina",
      "history.window_6h": "6 hodin",
      "history.window_24h": "24 hodin",
      "history.window_all": "Vše",
      "history.empty": "Žádná historická data.",
      "history.samples_placeholder": "0 / 0 vzorků v RAM",
      "history.samples_in_ram": "{count} / {max} vzorků · {memory} · nejstarší {oldest} · nejnovější {newest} · zahozeno {dropped}",
      "health.bme690": "BME690",
      "health.bsec": "BSEC",
      "health.i2c": "I²C",
      "health.sensor_data": "Data senzoru",
      "health.smtp": "SMTP",
      "health.ram_protection": "Ochrana RAM",
      "health.web_api": "Web API",
      "health.sensor_age": "{age} s",
      "health.ram_protection_active": "WARNING — ochrana RAM je aktivní, nejstarší vzorky se odstraňují.",
      "system.cpu_temperature": "Teplota CPU",
      "system.cpu_load": "Zátěž CPU",
      "system.ram_usage": "Využití RAM",
      "alarms.col.time": "Čas",
      "alarms.col.kind": "Stav",
      "alarms.col.metric": "Metrika",
      "alarms.col.value": "Hodnota",
      "alarms.empty": "Žádné záznamy alarmů.",
      "status.off": "Vypnuto",
      "status.recovered": "Obnoveno",

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

      "settings.open": "Nastavení",
      "settings.close": "Zavřít",
      "settings.title": "Nastavení",
      "settings.save": "Uložit",
      "settings.save_smtp": "Uložit SMTP",
      "settings.saved": "✓ Nastavení bylo uloženo.",
      "settings.save_failed": "✗ Nastavení se nepodařilo uložit. {error}",
      "settings.readonly": "Pouze ke čtení",
      "settings.nav": "Sekce nastavení",
      "settings.notifications": "Notifikace",
      "settings.master": "Hlavní vypínač notifikací",
      "settings.email_enabled": "E-mailové notifikace",
      "settings.recovery": "E-mail při návratu do NORMAL",
      "settings.cooldown": "Cooldown mezi e-maily (s)",
      "settings.smtp": "SMTP",
      "settings.smtp_host": "SMTP server",
      "settings.smtp_port": "Port",
      "settings.smtp_security": "Zabezpečení",
      "settings.smtp_security_none": "Žádné",
      "settings.smtp_security_starttls": "STARTTLS",
      "settings.smtp_security_tls": "TLS",
      "settings.smtp_username": "Uživatelské jméno",
      "settings.smtp_password": "Heslo",
      "settings.smtp_password_hint": "Nechte prázdné pro zachování stávajícího hesla",
      "settings.smtp_from": "Odesílatel",
      "settings.smtp_to": "Příjemce",
      "settings.smtp_to_hint": "admin@example.com",
      "settings.web_url": "URL server-meter",
      "settings.test_email": "Odeslat testovací email",
      "settings.test_ok": "Testovací email byl úspěšně odeslán.",
      "settings.test_fail": "Odeslání emailu selhalo: {error}",
      "settings.thresholds": "Prahové hodnoty",
      "settings.disclaimer": "Výchozí hodnoty slouží k detekci výrazných odchylek a nejsou zdravotními limity.",
      "settings.air_note": "IAQ, eCO₂ a bVOC jsou indikátory kvality vzduchu z BME690/BSEC, nikoliv certifikované měření škodlivin.",
      "settings.col.metric": "Metrika",
      "settings.col.enabled": "Zapnuto",
      "settings.col.warning": "WARNING",
      "settings.col.critical": "CRITICAL",
      "settings.col.warning_low": "WARNING low",
      "settings.col.critical_low": "CRITICAL low",
      "settings.col.hysteresis": "Hystereze",
      "settings.col.duration": "Trvání (s)",
      "settings.metric.temperature": "Teplota BME690",
      "settings.metric.humidity": "Vlhkost BME690",
      "settings.metric.pressure": "Tlak BME690",
      "settings.metric.gas_resistance": "Odpor plynu",
      "settings.metric.iaq": "IAQ",
      "settings.metric.iaq_accuracy": "Přesnost IAQ",
      "settings.metric.static_iaq": "Statické IAQ",
      "settings.metric.eco2": "eCO₂",
      "settings.metric.bvoc": "bVOC",
      "settings.metric.tvoc": "TVOC",
      "settings.metric.cpu_temperature": "Teplota CPU",
      "settings.metric.cpu_usage": "Využití CPU",
      "settings.metric.ram_usage": "Využití RAM",
      "settings.metric.sensor_unavailable": "Senzor nedostupný",
      "settings.unit_suffix": "{unit}",
      "settings.delivery_error": "Poslední chyba doručení: {error}",
      "settings.not_writable": "Konfigurační soubor nelze zapsat (chmod 660).",
      "settings.tab.general": "Obecné",
      "settings.tab.users": "Uživatelé",
      "settings.tab.notifications": "Notifikace",
      "settings.tab.smtp": "SMTP",
      "settings.tab.thresholds": "Alarmy",
      "settings.tab.alarms": "Alarmy",
      "settings.tab.system": "Systém",
      "settings.general.locale": "Jazyk",
      "settings.general.environment": "Prostředí",
      "settings.general.interval": "Interval měření",
      "settings.general.max_samples": "Maximální počet vzorků",
      "settings.general.max_age": "Maximální stáří historie",
      "settings.general.ram_protection": "Ochrana RAM",
      "settings.general.sensor_type": "Typ senzoru",
      "settings.enabled_on": "Zapnuto",
      "settings.enabled_off": "Vypnuto",
      "settings.users": "Uživatelé",
      "settings.general_hint": "Jazyk webu se nastavuje v YAML (web.locale). Účty jsou v SQLite, historie měření zůstává jen v RAM.",
      "settings.general_info": "Jazyk: {locale} · prostředí: {env}",
      "settings.system_info": "Senzor: {sensor} · RAM {ram}% · vzorků v RAM: {samples}",
      "settings.diagnostics": "Diagnostika",
      "settings.token": "Nagios monitoring token",
      "settings.token_hint": "Volitelný token jen pro GET /api/monitoring. Stávající Basic Auth plugin zůstává.",
      "settings.token_generate": "Vygenerovat token",
      "settings.token_revoke": "Zrušit token",
      "settings.token_none": "Token není nastaven.",
      "settings.token_configured": "Token je aktivní (hodnota se znovu nezobrazuje).",
      "settings.token_once": "Zkopírujte teď: {token}",
      "settings.token_generated": "Token byl vytvořen. Uložte ho, znovu se nezobrazí.",
      "settings.token_revoked": "Token byl zrušen.",
      "settings.export": "Exportovat konfiguraci",
      "settings.export_ok": "Konfigurace byla stažena (hesla jsou REDACTED).",
      "diag.app_version": "Verze aplikace",
      "diag.python": "Python",
      "diag.os": "OS",
      "diag.kernel": "Kernel",
      "diag.uptime": "Doba běhu",
      "diag.cpu": "CPU",
      "diag.cpu_temp": "Teplota CPU",
      "diag.ram": "RAM",
      "diag.i2c_bus": "I²C sběrnice",
      "diag.address": "Adresa BME690",
      "diag.i2c_status": "Stav I²C",
      "diag.bsec_version": "Verze BSEC",
      "diag.bsec_status": "Stav BSEC",
      "diag.iaq_accuracy": "Přesnost IAQ",
      "diag.static_iaq_accuracy": "Přesnost statického IAQ",
      "diag.bme690_status": "Stav BME690",
      "diag.sensor_age": "Stáří dat senzoru",
      "diag.history_samples": "Vzorky v RAM",
      "diag.ram_history": "Využití RAM historií",
      "diag.ram_protection_status": "Stav ochrany RAM",
      "users.add": "+ Přidat uživatele",
      "users.add_title": "Přidat uživatele",
      "users.edit_title": "Upravit uživatele",
      "users.edit": "Upravit",
      "users.delete": "Odstranit",
      "users.delete_confirm": "Opravdu chcete tohoto uživatele odstranit?",
      "users.cancel": "Zrušit",
      "users.save": "Uložit",
      "users.saved": "Uživatel byl uložen.",
      "users.deleted": "Uživatel byl odstraněn.",
      "users.username": "Uživatelské jméno",
      "users.password": "Heslo",
      "users.password_confirm": "Potvrzení hesla",
      "users.password_keep": "Nechte prázdné pro zachování stávajícího hesla",
      "users.password_mismatch": "Hesla se neshodují.",
      "users.password_required": "Heslo je povinné.",
      "users.role": "Role",
      "users.role_admin": "Administrátor",
      "users.role_user": "Uživatel",
      "users.status": "Stav",
      "users.active": "Aktivní",
      "users.disabled": "Neaktivní",
      "users.col.username": "Uživatelské jméno",
      "users.col.role": "Role",
      "users.col.status": "Stav",
      "users.col.created": "Vytvořen",
      "users.col.actions": "Akce",
      "users.last_admin": "Nelze odstranit nebo deaktivovat posledního aktivního administrátora.",
      "users.duplicate": "Toto uživatelské jméno už existuje.",
    },
    EN: {
      "app.title": "server-meter",
      "app.name": "server-meter",
      "app.eyebrow": "Raspberry Pi 5 · BME690 · RAM-only",

      "banner.default_password_html":
        "The default password is active. Change it in Settings → Users.",

      "dashboard.server": "Server",
      "dashboard.sensor": "Sensor",
      "dashboard.cpu": "CPU",
      "dashboard.ram": "RAM",
      "dashboard.system_health": "SYSTEM HEALTH",
      "dashboard.active_alerts": "Active alerts",
      "dashboard.alarm_history": "Alarm history",
      "dashboard.no_alerts": "No active alerts",
      "dashboard.since": "since {time}",
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
      "sensor.tvoc": "TVOC",
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
      "sensor.help.bvoc": "Breath-VOC equivalent estimate in ppm from Bosch BSEC. It is derived from static IAQ and Bosch laboratory tests with a b-VOC mixture that represents typical compounds in exhaled breath (for example ethanol, acetone and isoprene). It is not a direct chemical identification of those gases. BSEC 3.3 IAQ often does not subscribe this output.",
      "sensor.help.tvoc": "Bosch BSEC 3.x TVOC equivalent in ppb (id 31). The official BSEC 3.3.0.1 IAQ example subscribes TVOC in LP mode. It is not the same as bVOC (id 4, ppm) and is not derived from IAQ, eCO₂ or gas resistance.",
      "system.cpu_load_placeholder": "load — · freq —",
      "system.cpu_load_meta": "CPU {cpu}% · load {load} · {freq} MHz",
      "system.ram_placeholder": "used — / —",
      "system.ram_detail": "{used} used / {total}",

      "history.window_15m": "15 min",
      "history.window_1h": "1 hour",
      "history.window_6h": "6 hours",
      "history.window_24h": "24 hours",
      "history.window_all": "All",
      "history.empty": "No historical data available.",
      "history.samples_placeholder": "0 / 0 samples in RAM",
      "history.samples_in_ram": "{count} / {max} samples · {memory} · oldest {oldest} · newest {newest} · dropped {dropped}",
      "health.bme690": "BME690",
      "health.bsec": "BSEC",
      "health.i2c": "I²C",
      "health.sensor_data": "Sensor data",
      "health.smtp": "SMTP",
      "health.ram_protection": "RAM protection",
      "health.web_api": "Web API",
      "health.sensor_age": "{age} s",
      "health.ram_protection_active": "WARNING — RAM protection active – oldest history samples are being removed.",
      "system.cpu_temperature": "CPU temperature",
      "system.cpu_load": "CPU load",
      "system.ram_usage": "RAM usage",
      "alarms.col.time": "Time",
      "alarms.col.kind": "Status",
      "alarms.col.metric": "Metric",
      "alarms.col.value": "Value",
      "alarms.empty": "No alarm history records.",
      "status.off": "Off",
      "status.recovered": "Recovered",

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

      "settings.open": "Settings",
      "settings.close": "Close",
      "settings.title": "Settings",
      "settings.save": "Save",
      "settings.save_smtp": "Save SMTP",
      "settings.saved": "✓ Settings saved.",
      "settings.save_failed": "✗ Failed to save settings. {error}",
      "settings.readonly": "Read-only",
      "settings.nav": "Settings sections",
      "settings.notifications": "Notifications",
      "settings.master": "Master notification switch",
      "settings.email_enabled": "Email notifications",
      "settings.recovery": "Email on return to NORMAL",
      "settings.cooldown": "Cooldown between emails (s)",
      "settings.smtp": "SMTP",
      "settings.smtp_host": "SMTP server",
      "settings.smtp_port": "Port",
      "settings.smtp_security": "Security",
      "settings.smtp_security_none": "None",
      "settings.smtp_security_starttls": "STARTTLS",
      "settings.smtp_security_tls": "TLS",
      "settings.smtp_username": "Username",
      "settings.smtp_password": "Password",
      "settings.smtp_password_hint": "Leave blank to keep the current password",
      "settings.smtp_from": "Sender",
      "settings.smtp_to": "Recipient",
      "settings.smtp_to_hint": "admin@example.com",
      "settings.web_url": "server-meter URL",
      "settings.test_email": "Send test email",
      "settings.test_ok": "Test email was sent successfully.",
      "settings.test_fail": "Email delivery failed: {error}",
      "settings.thresholds": "Thresholds",
      "settings.disclaimer": "Default values are intended to detect significant anomalies and are not medical or safety limits.",
      "settings.air_note": "IAQ, eCO₂ and bVOC are BME690/BSEC air-quality indicators, not certified measurements of hazardous gases.",
      "settings.col.metric": "Metric",
      "settings.col.enabled": "Enabled",
      "settings.col.warning": "WARNING",
      "settings.col.critical": "CRITICAL",
      "settings.col.warning_low": "WARNING low",
      "settings.col.critical_low": "CRITICAL low",
      "settings.col.hysteresis": "Hysteresis",
      "settings.col.duration": "Duration (s)",
      "settings.metric.temperature": "BME690 temperature",
      "settings.metric.humidity": "BME690 humidity",
      "settings.metric.pressure": "BME690 pressure",
      "settings.metric.gas_resistance": "Gas resistance",
      "settings.metric.iaq": "IAQ",
      "settings.metric.iaq_accuracy": "IAQ accuracy",
      "settings.metric.static_iaq": "Static IAQ",
      "settings.metric.eco2": "eCO₂",
      "settings.metric.bvoc": "bVOC",
      "settings.metric.tvoc": "TVOC",
      "settings.metric.cpu_temperature": "CPU temperature",
      "settings.metric.cpu_usage": "CPU usage",
      "settings.metric.ram_usage": "RAM usage",
      "settings.metric.sensor_unavailable": "Sensor unavailable",
      "settings.unit_suffix": "{unit}",
      "settings.delivery_error": "Last delivery error: {error}",
      "settings.not_writable": "Configuration file is not writable (chmod 660).",
      "settings.tab.general": "General",
      "settings.tab.users": "Users",
      "settings.tab.notifications": "Notifications",
      "settings.tab.smtp": "SMTP",
      "settings.tab.thresholds": "Alarms",
      "settings.tab.alarms": "Alarms",
      "settings.tab.system": "System",
      "settings.general.locale": "Language",
      "settings.general.environment": "Environment",
      "settings.general.interval": "Measurement interval",
      "settings.general.max_samples": "Maximum samples",
      "settings.general.max_age": "Maximum history age",
      "settings.general.ram_protection": "RAM protection",
      "settings.general.sensor_type": "Sensor type",
      "settings.enabled_on": "Enabled",
      "settings.enabled_off": "Disabled",
      "settings.users": "Users",
      "settings.general_hint": "UI language is set in YAML (web.locale). Accounts are stored in SQLite; sensor history stays in RAM only.",
      "settings.general_info": "Language: {locale} · environment: {env}",
      "settings.system_info": "Sensor: {sensor} · RAM {ram}% · RAM samples: {samples}",
      "settings.diagnostics": "Diagnostics",
      "settings.token": "Nagios monitoring token",
      "settings.token_hint": "Optional read-only token for GET /api/monitoring. Existing Basic Auth Nagios plugin still works.",
      "settings.token_generate": "Generate token",
      "settings.token_revoke": "Revoke token",
      "settings.token_none": "No monitoring token is configured.",
      "settings.token_configured": "A token is active (the secret is not shown again).",
      "settings.token_once": "Copy now: {token}",
      "settings.token_generated": "Token created. Store it; it will not be shown again.",
      "settings.token_revoked": "Monitoring token revoked.",
      "settings.export": "Export configuration",
      "settings.export_ok": "Configuration downloaded (secrets are REDACTED).",
      "diag.app_version": "Application version",
      "diag.python": "Python",
      "diag.os": "OS",
      "diag.kernel": "Kernel",
      "diag.uptime": "Uptime",
      "diag.cpu": "CPU",
      "diag.cpu_temp": "CPU temperature",
      "diag.ram": "RAM",
      "diag.i2c_bus": "I²C bus",
      "diag.address": "BME690 address",
      "diag.i2c_status": "I²C status",
      "diag.bsec_version": "BSEC version",
      "diag.bsec_status": "BSEC status",
      "diag.iaq_accuracy": "IAQ accuracy",
      "diag.static_iaq_accuracy": "Static IAQ accuracy",
      "diag.bme690_status": "BME690 status",
      "diag.sensor_age": "Sensor data age",
      "diag.history_samples": "History samples",
      "diag.ram_history": "RAM history usage",
      "diag.ram_protection_status": "RAM protection status",
      "users.add": "+ Add user",
      "users.add_title": "Add user",
      "users.edit_title": "Edit user",
      "users.edit": "Edit",
      "users.delete": "Delete",
      "users.delete_confirm": "Do you really want to delete this user?",
      "users.cancel": "Cancel",
      "users.save": "Save",
      "users.saved": "User saved.",
      "users.deleted": "User deleted.",
      "users.username": "Username",
      "users.password": "Password",
      "users.password_confirm": "Confirm password",
      "users.password_keep": "Leave blank to keep the current password",
      "users.password_mismatch": "Passwords do not match.",
      "users.password_required": "Password is required.",
      "users.role": "Role",
      "users.role_admin": "Administrator",
      "users.role_user": "User",
      "users.status": "Status",
      "users.active": "Active",
      "users.disabled": "Disabled",
      "users.col.username": "Username",
      "users.col.role": "Role",
      "users.col.status": "Status",
      "users.col.created": "Created",
      "users.col.actions": "Actions",
      "users.last_admin": "Cannot remove or disable the last active administrator.",
      "users.duplicate": "This username already exists.",
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
