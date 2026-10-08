# Konfigurace YAML

Aplikace **čte** YAML při startu. Měření a stav alarmu zůstávají v RAM. Blok `notifications` smí Settings UI atomicky zapsat zpět (temp + fsync + rename). Sensor history se do YAML nikdy nedává.

## Kde soubor leží

Pořadí hledání, pokud nespustíte `--config` (`server_meter/config.py`):

1. proměnná prostředí `SERVER_METER_CONFIG`
2. `/etc/server-meter/config.yaml`
3. `<kořen projektu>/config/config.yaml`
4. `<kořen projektu>/config/config.example.yaml`

Systemd unit vždy předává:

```text
--config /etc/server-meter/config.yaml
```

Příklady v git stromu:

| Soubor | Účel |
|---|---|
| `config/config.example.yaml` | produkční šablona (heslo `CHANGE_ME`) |
| `config/config.yaml.example` | zkrácená kopie šablony |
| `config/config.mock.yaml` | vývoj bez BME690 |

`install.sh` kopíruje example do `/etc/server-meter/config.yaml` **jen pokud ten soubor ještě neexistuje**. Při upgradu se v existujícím YAML změní pouze starý výchozí `history.max_samples: 10000` (nebo 20000) na `2000000`. Hesla, SMTP, locale a záměrně menší cap se nepřepisují. Stejná jednoklíčová migrace probíhá při startu služby.

---

## Kompletní produkční příklad

Toto je **skutečný** model (`AppConfig`, extra klíče jsou zakázané):

```yaml
application:
  name: server-meter
  environment: production

web:
  host: "0.0.0.0"
  port: 8080
  locale: "CZ"
  api_docs_enabled: false
  health_public: true
  max_request_bytes: 16384
  users_db: "/var/lib/server-meter/users.db"
  auth:
    enabled: true
    username: "admin"
    password: "YOUR_PASSWORD"

sensor:
  type: "BME690"
  driver: "bme690"
  i2c:
    bus: 1
    address: 0x76
  interval_seconds: 5
  heater_temperature_c: 320
  heater_duration_ms: 150
  retry_initial_seconds: 2
  retry_max_seconds: 30
  i2c_timeout_seconds: 1.0
  bsec:
    enabled: true
    library_path: "/opt/server-meter/lib/libalgobsec.so"
    config_blob_path: ""
    sample_rate: "lp"
    temperature_offset: 0.0
    persist_state: false

history:
  max_samples: 2000000
  max_age_seconds: 86400
  min_samples_keep: 64

memory_protection:
  enabled: true
  warning_percent: 70
  critical_percent: 80
  emergency_percent: 90
  warning_trim_fraction: 0.10
  critical_trim_fraction: 0.25
  emergency_trim_fraction: 0.50
  check_interval_seconds: 15

nagios:
  enabled: true
  sensor_max_age_seconds: 30
  thresholds:
    cpu_temperature_warning: 70
    cpu_temperature_critical: 80
    ram_usage_warning: 70
    ram_usage_critical: 85
    iaq_warning: 150
    iaq_critical: 250
    cpu_load_warning: 2.0
    cpu_load_critical: 4.0

logging:
  level: INFO
  access_log: false

notifications:
  enabled: false
  max_queue_size: 10
  email:
    enabled: false
    cooldown_seconds: 3600
    notify_recovery: true
    from: ""
    to: []
    web_url: ""
    smtp:
      host: ""
      port: 587
      security: "starttls"
      username: ""
      password: ""
      timeout_seconds: 15
```

Kompletní výchozí prahy: [NOTIFICATIONS.md](NOTIFICATIONS.md). Chybějící blok `notifications` e-maily nespouští.

`YOUR_PASSWORD` nahraďte vlastním heslem. `0x76` nahraďte výsledkem `i2cdetect`.

---

## Položka po položce

### application

| Klíč | Význam | Omezení |
|---|---|---|
| `name` | jméno v logu / status | řetězec |
| `environment` | `production`, `development`, `test` | v `production` platí tvrdá bezpečnostní pravidla |

V `production`:

- `web.api_docs_enabled` musí být `false`
- `web.auth.enabled` musí být `true`
- heslo nesmí být prázdné ani kratší než 8 znaků
- `CHANGE_ME` je tovární heslo (instalátor s ním službu spustí); UI zobrazí `default_password_active`

`test` vypíná automatickou měřicí smyčku v `create_app` (pro pytest).

### web

| Klíč | Význam | Výchozí |
|---|---|---|
| `host` | bind adresa | `0.0.0.0` |
| `port` | TCP port | `8080` (1–65535) |
| `locale` | jazyk webu: `CZ` (čeština) nebo `EN` (angličtina) | `CZ` |
| `api_docs_enabled` | `/docs`, `/redoc`, `/openapi.json` | `false` |
| `health_public` | `/api/health` bez hesla | `true` |
| `max_request_bytes` | limit Content-Length | `16384` |
| `users_db` | SQLite soubor s účty, historií alarmů a monitoring tokenem (ne historie měření) | `/var/lib/server-meter/users.db` |
| `auth.enabled` | HTTP Basic Auth | `true` |
| `auth.username` | uživatel | `admin` |
| `auth.password` | heslo (jen YAML, ne zdrojáky) | `CHANGE_ME` |

`web.locale` ovládá texty dashboardu **a e-mailových notifikací** (`CZ` = čeština, `EN` = angličtina). REST API a Nagios plugin zůstávají jazykově neutrální. Pokud klíč v YAML chybí, aplikace použije `CZ` — existující instalace se nemění a soubor se nepřepisuje. Nepovolená hodnota (např. `DE`) službu nespustí:

```text
Invalid locale 'DE'.

Supported locales:
- CZ
- EN
```

Po změně locale:

```bash
sudo systemctl restart server-meter
```

Heslo **nikdy** není v API odpovědích (`public_status_dict` vrací `auth_enabled`, `locale` a boolean `default_password_active`, nikoli plaintext).

Basic Auth **bez TLS nešifruje** heslo. Viz [SECURITY.md](SECURITY.md).

### sensor

| Klíč | Význam |
|---|---|
| `type` | musí být `BME690` nebo `BME69X` při driveru `bme690` |
| `driver` | `bme690` (produkce), `mock` (bez hardware), `bme69x_python` (komunitní wrapper) |
| `i2c.bus` | Linux bus, na Pi 5 GPIO header = **1** |
| `i2c.address` | jen `0x76` nebo `0x77` (YAML hex `0x76` PyYAML načte jako číslo) |
| `interval_seconds` | perioda smyčky (1–3600). S BSEC LP **≥ 3**. S BSEC ULP **≥ 300**. |
| `heater_temperature_c` | 200–400, výchozí 320 |
| `heater_duration_ms` | 1–2000, výchozí 150 |
| `retry_initial_seconds` | backoff po chybě I²C |
| `retry_max_seconds` | strop backoffu |
| `i2c_timeout_seconds` | timeout I²C |

### sensor.bsec

| Klíč | Význam |
|---|---|
| `enabled` | pokusit se načíst BSEC |
| `library_path` | cesta k `libalgobsec.so` (`install.sh` vyplní `/opt/server-meter/lib/libalgobsec.so`; prázdné = výchozí seznam cest) |
| `config_blob_path` | volitelný read-only blob z Bosch ZIP |
| `sample_rate` | `lp` (3 s) nebo `ulp` (300 s) |
| `temperature_offset` | BSEC `HEATSOURCE` (°C) |
| `persist_state` | **musí zůstat `false`** — start jinak selže |

Hledání knihovny (`server_meter/sensor/bsec.py`):

1. `sensor.bsec.library_path`
2. env `SERVER_METER_BSEC_LIB`
3. `/opt/server-meter/lib/libalgobsec.so`
4. `/usr/local/lib/libalgobsec.so`
5. `/usr/lib/libalgobsec.so`
6. `/opt/bosch/bsec/libalgobsec.so`
7. `libalgobsec.so` z dynamického linkeru

### history

| Klíč | Význam | Limit |
|---|---|---|
| `max_samples` | max. vzorků v deque | 1–2000000 (`HISTORY_HARD_MAX_SAMPLES`). Výchozí 2000000. Není to prealokace. |
| `max_age_seconds` | max. stáří | 60–15552000 (180 dní). Výchozí 86400. |
| `min_samples_keep` | podlaha při trimu | 1–1000, nejvýše `max_samples` |

### memory_protection

Při vysokém RAM% se **mažou nejstarší** vzorky. Nikdy se neukládají na disk.

| Klíč | Význam | Výchozí |
|---|---|---|
| `enabled` | zapnout ochranu | `true` |
| `warning_percent` | ≥ → trim 10 % | 70 |
| `critical_percent` | ≥ → trim 25 % | 80 |
| `emergency_percent` | ≥ → trim 50 % | 90 |
| `warning_trim_fraction` | 0.10 | |
| `critical_trim_fraction` | 0.25 | |
| `emergency_trim_fraction` | 0.50 | |
| `check_interval_seconds` | min. 5 s | 15 |

Musí platit `warning < critical < emergency`.

### nagios

| Klíč | Význam |
|---|---|
| `enabled` | `false` → endpoint vrací `UNKNOWN - Nagios checks disabled` |
| `sensor_max_age_seconds` | CRITICAL když je poslední vzorek starší |
| `thresholds.*` | CPU teplota, RAM %, IAQ, load1 — warning musí být **menší** než critical |

### notifications

Výchozí stav: `enabled: false` (upgrade bez překvapení). SMTP heslo je jen v YAML; API vrací `password_set`. Podrobnosti, hystereze, cooldown a tabulka prahů: [NOTIFICATIONS.md](NOTIFICATIONS.md).

### logging

| Klíč | Význam |
|---|---|
| `level` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` |
| `access_log` | uvicorn access log do journald; nechte `false` kvůli SD kartě |

Aplikace **nikdy neloguje každé měření**.

---

## Mock režim (bez BME690)

Soubor `config/config.mock.yaml`:

- `environment: development` (povolí `/docs`)
- `driver: mock`
- `bsec.enabled: false`
- heslo `devpass1`
- `host: 127.0.0.1`

```bash
cd /opt/server-meter
/opt/server-meter/venv/bin/python -m server_meter --config /opt/server-meter/config/config.mock.yaml
```

Dashboard: `http://127.0.0.1:8080/` uživatel `admin` / `devpass1`.

Návrat do produkce: `driver: bme690`, `environment: production`, reálné heslo, `--config /etc/server-meter/config.yaml`.

---

## Neplatná konfigurace

Při chybě proces vypíše na stderr `server-meter configuration error: ...` a skončí kódem **2**. Systemd to bude restartovat — opravte YAML dřív, než službu zapnete.
