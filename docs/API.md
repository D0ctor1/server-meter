# REST API

server-meter vystavuje FastAPI endpointy na portu z YAML (`web.port`, výchozí **8080**).

Tento dokument popisuje **skutečné** trasy v `server_meter/api/routes.py`, `server_meter/api/settings.py` a `server_meter/app.py`.

`RPI_IP` a `YOUR_PASSWORD` jsou zástupné hodnoty. IP zjistíte `hostname -I`. Heslo je účet v SQLite (první admin se jednou migrujte z `web.auth` v YAML).

---

## Autentizace

| Trasa | Auth ve výchozím YAML |
|---|---|
| `GET /api/health` | **ne** (`web.health_public: true`) |
| `GET /` (HTML dashboard + login form) | **ne** (API data zůstávají za Basic Auth) |
| `GET /api/status` | HTTP Basic Auth |
| `GET /api/current` | HTTP Basic Auth |
| `GET /api/history` | HTTP Basic Auth |
| `GET /api/system` | HTTP Basic Auth |
| `GET /api/sensor` | HTTP Basic Auth |
| `GET /api/nagios/check` | HTTP Basic Auth |
| `GET /api/monitoring` | HTTP Basic Auth |
| `GET /api/me` | HTTP Basic Auth |
| `GET /api/settings` | HTTP Basic Auth, jen `admin` |
| `PUT /api/settings` | HTTP Basic Auth, jen `admin` |
| `POST /api/settings/test-email` | HTTP Basic Auth, jen `admin` |
| `GET/POST /api/admin/users` | HTTP Basic Auth, jen `admin` |
| `GET/PUT/DELETE /api/admin/users/{id}` | HTTP Basic Auth, jen `admin` |
| `GET /css/*`, `/js/*`, `/vendor/*` | **ne** (statické soubory) |
| `GET /docs`, `/redoc`, `/openapi.json` | v production **vypnuto** (`404`) |

JSON klíče a technické hodnoty API (`temperature`, `status: "warning"`, …) se **nemění** podle `web.locale`. Locale ovlivňuje jen HTML/JS dashboard.

Implementace: `server_meter/api/auth.py` + `server_meter/users.py` (Argon2id, SQLite). Role `user` dostane **403** na admin trasy.

Když `web.auth.enabled: true` a chybí nebo nesouhlasí údaje:

- HTTP **401**
- hlavička `WWW-Authenticate: Basic realm="server-meter"`
- tělo FastAPI: `{"detail":"Authentication required"}` nebo `{"detail":"Invalid credentials"}`

Když `web.health_public: false`, i `/api/health` vyžaduje stejné Basic Auth.

V `environment: production` musí být auth zapnuté. Tovární heslo `CHANGE_ME` je povoleno, aby `install.sh` mohl službu spustit; UI na něj upozorní (`default_password_active`).

> HTTP Basic Authentication přes nešifrované HTTP neposkytuje šifrování hesla. Viz [SECURITY.md](SECURITY.md).

---

## Společné hlavičky odpovědi

Middleware `SecurityHeadersMiddleware` přidává mimo jiné:

| Hlavička | Hodnota |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `no-referrer` |
| `Cache-Control` | `no-store` |
| `X-server-meter` | verze projektu |

Požadavek větší než `web.max_request_bytes` (výchozí 16384) → HTTP **413** `{"error":"request too large"}`.

Neobsloužená výjimka → HTTP **500** `{"error":"internal server error"}`.

---

## GET /api/health

Liveness. **Nesahá** na I²C, **neprochází** historii.

### Proveď

```bash
curl http://127.0.0.1:8080/api/health
```

Z jiného počítače (příklad IP):

```bash
curl http://192.168.1.50:8080/api/health
```

`192.168.1.50` je **příklad**.

### Očekávaný výsledek

- HTTP **200**
- `Content-Type: application/json`

```json
{"status":"healthy","service":"server-meter"}
```

Liveness only. Monitoring values belong on `GET /api/monitoring`.

Pokud `web.health_public: false`:

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/health
```

Bez hesla tehdy **401**.

---

## GET /api/current

Poslední dostupné měření BME690 z RAM (`MeterService.current`).

### Autentizace

HTTP Basic Auth (pokud je zapnutá).

### Parametry

Žádné.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  http://192.168.1.50:8080/api/current
```

### Očekávaný výsledek — senzor má vzorek

HTTP **200**. Pole odpovídají `Measurement.to_api_dict()` plus `available` a `iaq_accuracy_label`.

Jednotky: teplota °C, tlak hPa, vlhkost % RH, `gas_resistance` Ω, IAQ 0–500, `eco2`/`co2_equivalent` ppm, `bvoc`/`breath_voc_equivalent` ppm.

```json
{
  "timestamp": 1728288000.0,
  "temperature": 24.2,
  "pressure": 1008.2,
  "humidity": 45.3,
  "gas_resistance": 123456.0,
  "iaq": 42.1,
  "iaq_accuracy": 3,
  "static_iaq": null,
  "static_iaq_accuracy": null,
  "co2_equivalent": 600.0,
  "co2_accuracy": null,
  "breath_voc_equivalent": 0.4,
  "breath_voc_accuracy": null,
  "gas_percentage": null,
  "gas_percentage_accuracy": null,
  "tvoc_equivalent": null,
  "tvoc_accuracy": null,
  "raw_temperature": null,
  "raw_humidity": null,
  "raw_pressure": null,
  "stabilization_status": null,
  "run_in_status": null,
  "sensor_status": "ok",
  "eco2": 600.0,
  "bvoc": 0.4,
  "available": true,
  "iaq_accuracy_label": "high"
}
```

Čísla výše jsou **příklad**. `timestamp` je unix time v **UTC** (sekundy, float).

`iaq_accuracy_label` (`server_meter/models/measurement.py`):

| `iaq_accuracy` | label |
|---|---|
| `0` | `stabilizing` |
| `1` | `low` |
| `2` | `medium` |
| `3` | `high` |
| jiné / `null` | `unknown` / `null` |

Bez BSEC jsou `iaq`, `eco2`, `bvoc` a související pole **`null`**. Aplikace hodnoty nevymýšlí.

### Očekávaný výsledek — zatím žádný vzorek

HTTP **200** (ne 503):

```json
{
  "timestamp": null,
  "sensor_status": "unavailable",
  "available": false
}
```

`sensor_status` je aktuální stav služby (`ok`, `unavailable`, `initializing`, `error`, `unknown`).

### HTTP kódy

| Kód | Význam |
|---|---|
| 200 | JSON vrácen (i když `available: false`) |
| 401 | chybí / špatné Basic Auth |
| 500 | neočekávaná chyba procesu |

---

## GET /api/history

Kopie vzorků z RAM bufferu. **Není** to soubor na SD kartě.

### Autentizace

HTTP Basic Auth.

### Query parametry

| Parametr | Typ | Omezení | Význam |
|---|---|---|---|
| `seconds` | float | `> 0`, strop = teoretická kapacita ring bufferu | vzorky za posledních N sekund. `86400` = okno 24 h, **není** retention limit. |
| `limit` | int | `1`–`10000` | nejvýše N **nejnovějších** po filtrování |
| `since` | float | unix time | vzorky s `timestamp > since` |
| `max_points` | int | `1`–`10000` | rovnoměrný downsample filtrovaného okna (zachová tvar) |

`seconds` má přednost před `since` (`RamBuffer.snapshot`). `max_points` má přednost před `limit`. Bez `seconds` (frontend „Vše“) se bere celá RAM historie, downsamplovaná. Bez `limit` i `max_points` se vrací nejvýše 2000 nejnovějších vzorků — API nikdy nepošle automaticky 2 miliony bodů. Grafy používají `max_points=720`.

Neplatný parametr (např. `limit=0`) → HTTP **422**.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  'http://192.168.1.50:8080/api/history?limit=10'
```

Okno jedné hodiny:

```bash
curl -u admin:YOUR_PASSWORD \
  'http://192.168.1.50:8080/api/history?seconds=3600'
```

### Očekávaný výsledek

HTTP **200**:

```json
{
  "count": 1,
  "source": "ram",
  "persistent": false,
  "samples": [
    {
      "timestamp": 1728288000.0,
      "temperature": 24.2,
      "pressure": 1008.2,
      "humidity": 45.3,
      "gas_resistance": 123456.0,
      "iaq": 42.1,
      "iaq_accuracy": 3,
      "static_iaq": null,
      "static_iaq_accuracy": null,
      "co2_equivalent": 600.0,
      "co2_accuracy": null,
      "breath_voc_equivalent": 0.4,
      "breath_voc_accuracy": null,
      "gas_percentage": null,
      "gas_percentage_accuracy": null,
      "tvoc_equivalent": null,
      "tvoc_accuracy": null,
      "raw_temperature": null,
      "raw_humidity": null,
      "raw_pressure": null,
      "stabilization_status": null,
      "run_in_status": null,
      "sensor_status": "ok",
      "eco2": 600.0,
      "bvoc": 0.4
    }
  ]
}
```

Po `systemctl restart server-meter` je `count` **0** (nebo jen vzorky od nového startu). To je záměr.

`"source": "ram"` a `"persistent": false` jsou pevné — API **neumí** číst historii z disku.

---

## GET /api/status

Souhrn aplikace, senzoru, RAM bufferu, SYSTEM HEALTH a Raspberry Pi. **Neobsahuje** heslo. Pole `system_health` je jazykově neutrální (`ok` / `warning` / `critical` / `off`). Historie v `history` zahrnuje `memory_bytes` a stáří nejstaršího/nejnovějšího vzorku.

### Autentizace

HTTP Basic Auth.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  http://192.168.1.50:8080/api/status
```

### Očekávaný výsledek (struktura)

HTTP **200**. Příklad (čísla se liší):

```json
{
  "application": {
    "name": "server-meter",
    "environment": "production",
    "sensor_driver": "bme690",
    "sensor_type": "BME690",
    "i2c_bus": 1,
    "i2c_address": "0x76",
    "interval_seconds": 5.0,
    "bsec_enabled": true,
    "history_max_samples": 2000000,
    "history_max_age_seconds": 10000000,
    "memory_protection": true,
    "api_docs_enabled": false,
    "auth_enabled": true,
    "default_password_active": false,
    "locale": "CZ"
  },
  "uptime_seconds": 120.5,
  "sensor": {
    "status": "ok",
    "health": "healthy",
    "driver": {
      "driver": "bme690",
      "chip": "BME690",
      "chip_id": "0x61",
      "variant_id": "0x0",
      "i2c_bus": 1,
      "i2c_address": "0x76",
      "bsec_loaded": true,
      "bsec_version": "3.2.0.0",
      "opened": true
    },
    "last_success_at": 1728288000.0,
    "last_error_at": null,
    "last_error": null,
    "age_seconds": 2.1,
    "successes": 20,
    "errors": 0,
    "recoveries": 0
  },
  "history": {
    "samples": 20,
    "max_samples": 2000000,
    "hard_max_samples": 2000000,
    "max_age_seconds": 10000000.0,
    "max_age_auto": true,
    "theoretical_max_age_seconds": 10000000.0,
    "actual_span_seconds": 100.0,
    "dropped_oldest": 0,
    "trim_events": 0,
    "oldest_timestamp": 1728287900.0,
    "newest_timestamp": 1728288000.0
  },
  "memory": {
    "pressure": "normal",
    "ram_usage_percent": 31.2,
    "process_rss_bytes": 45000000
  },
  "system": {
    "cpu_temperature_c": 48.2,
    "cpu_usage_percent": 4.1,
    "cpu_load_1m": 0.12,
    "uptime_seconds": 3600.0,
    "ram_usage_percent": 31.2
  },
  "last_measurement_timestamp": 1728288000.0
}
```

`application` pochází z `AppConfig.public_status_dict()` — klíč `password` tam **není**.

`memory.pressure`: `normal` | `warning` | `critical` | `emergency`.

`sensor.health`: `healthy` | `degraded` | `failed` | `unknown`.

`sensor.status`: `ok` | `unavailable` | `initializing` | `error` | `unknown`.

---

## GET /api/system

Kompletní snímek `SystemMetrics` (`/proc`, `/sys`). Žádný zápis na disk.

### Autentizace

HTTP Basic Auth.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  http://192.168.1.50:8080/api/system
```

### Očekávaný výsledek

HTTP **200**:

```json
{
  "timestamp": 1728288000.0,
  "cpu_temperature_c": 48.2,
  "cpu_load_1m": 0.12,
  "cpu_load_5m": 0.18,
  "cpu_load_15m": 0.21,
  "cpu_usage_percent": 4.1,
  "cpu_frequency_mhz": 1800.0,
  "ram_total_bytes": 4294967296,
  "ram_used_bytes": 1342177280,
  "ram_available_bytes": 2952790016,
  "ram_usage_percent": 31.2,
  "uptime_seconds": 3600.0,
  "throttle_raw": 0,
  "throttle_flags": {
    "under_voltage": false,
    "arm_freq_capped": false,
    "throttled": false,
    "soft_temp_limit": false,
    "under_voltage_occurred": false,
    "arm_freq_capped_occurred": false,
    "throttled_occurred": false,
    "soft_temp_limit_occurred": false
  },
  "process_rss_bytes": 45000000
}
```

Pokud Ubuntu nevystaví throttle sysfs/`vcgencmd`, budou `throttle_raw` a `throttle_flags` **`null`**. Teplota CPU se čte z `/sys/class/thermal/thermal_zone0/temp` (nebo hwmon). Chybějící hodnota = `null`, ne nula.

---

## GET /api/sensor

Stav driveru a poslední vzorek (nebo `null`).

### Autentizace

HTTP Basic Auth.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  http://192.168.1.50:8080/api/sensor
```

### Očekávaný výsledek

HTTP **200** i při výpadku I²C:

```json
{
  "status": "ok",
  "health": "healthy",
  "driver": {
    "driver": "bme690",
    "chip": "BME690",
    "chip_id": "0x61",
    "i2c_address": "0x76",
    "bsec_loaded": false,
    "opened": true
  },
  "age_seconds": 2.1,
  "current": { },
  "successes": 20,
  "errors": 0,
  "recoveries": 0,
  "last_error": null
}
```

`current` je `to_api_dict()` nebo `null`. Přesný obsah `driver` závisí na `describe()` daného driveru (`bme690` / `mock` / `bme69x_python`).

---

## GET /api/nagios/check

Plain-text výstup pro Nagios plugin. Podrobnosti: [NAGIOS.md](NAGIOS.md).

### Autentizace

HTTP Basic Auth. Endpoint **neobchází** přihlášení.

### Parametry

Žádné.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  -D - \
  http://192.168.1.50:8080/api/nagios/check
```

### Očekávaný výsledek

- HTTP status je **vždy 200**, pokud proces odpoví
- `Content-Type: text/plain; charset=utf-8`
- `Cache-Control: no-store`
- `X-Nagios-Status` / `x-nagios-status`: `0` | `1` | `2` | `3`
- `X-Nagios-State` / `x-nagios-state`: `OK` | `WARNING` | `CRITICAL` | `UNKNOWN`
- tělo začíná stejným slovem a končí `\n`

Příklad:

```text
OK - BME690 reachable; temperature=24.1C, humidity=45.2%, pressure=1008.2hPa, gas=123.4kOhm, sensor_age=2s, cpu_temp=48.2C, ram=31%
```

**HTTP 200 není totéž co Nagios OK.** Stav je v těle a v hlavičkách, ne v HTTP kódu.

Když proces neběží, `curl` selže spojení — to **není** HTTP 200.

---

## GET /

HTML dashboard (`web/index.html`) včetně přihlašovacího formuláře. **Bez** Basic Auth, aby šel lokalizovat. Měření pořád chrání `/api/*`.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8080/
```

Očekávaný kód: **200**. Jazyk stránky (`lang`, `data-locale`) bere z `web.locale` (`CZ` nebo `EN`). JSON klíče API se locale nemění.

---

## OpenAPI `/docs`

V `environment: production` musí být `web.api_docs_enabled: false` — jinak konfigurace **odmítne start**.

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/docs
```

V production: **404**.

V `config/config.mock.yaml` (`environment: development`, `api_docs_enabled: true`) je Swagger na `http://127.0.0.1:8080/docs`.

---

## Endpointy, které **neexistují**

Aplikace **nemá**:

- `POST` / `PUT` / `DELETE` měření (historie je RAM-only)
- `/api/history/download`
- websocket
- GraphQL
- Prometheus `/metrics`
- zápis měření do SQLite

`PUT /api/settings` ukládá jen administrativní blok `notifications` (SMTP/prahy), nikoli vzorky senzoru.

---

## GET /api/alarms/history

Historie výskytu alarmů a výsledků odeslání e-mailu. **Pouze RAM**, prázdná po startu procesu. Stará SQLite tabulka `alarm_history` (pokud v `users.db` zbývá) se **nečte**.

### Autentizace

HTTP Basic Auth (`admin` i `user`).

### Parametry

| Query | Význam |
|---|---|
| `limit` | 1–500, výchozí 100. Nejnovější záznamy první. |

`kind` je jazykově neutrální: `WARNING`, `CRITICAL`, `RECOVERY`, `EMAIL_OK`, `EMAIL_FAIL`.

### Očekávaný výsledek

HTTP **200**:

```json
{
  "alarms": [],
  "source": "ram",
  "persistent": false
}
```

Po `systemctl restart server-meter` je `alarms` vždy `[]`, dokud v aktuálním běhu nevznikne nová událost.

---

## GET /api/monitoring

JSON pro Nagios shell plugin a další dohled. **Jazykově neutrální** (nezávislé na `web.locale`). Autoritativní Nagios stav je `overall` / `status` (`OK`/`WARNING`/`CRITICAL`/`UNKNOWN`) z notifikačního enginu. SMTP heslo se neposílá.

Vedle vnořených `sensor` / `system` / `thresholds` / `alarms` endpoint vrací i ploché klíče, aby `check_server_meter.sh` uměl JSON parsovat bez dalších nástrojů: `temperature_c`, `humidity_percent`, `pressure_hpa`, `gas_resistance_ohm`, `iaq`, `iaq_accuracy`, `static_iaq`, `static_iaq_accuracy`, `eco2_ppm`, `bvoc_ppm`, `cpu_temperature_c`, `cpu_load_percent`, `ram_used_percent`, `uptime_seconds`, `sensor_age_seconds`, `sensor_available` a `*_warning` / `*_critical`. Jeden endpoint stačí — plugin si z JSON vybere metriku podle `$ARG1$`.

### Autentizace

HTTP Basic Auth. Volitelný read-only monitoring token (`Authorization: Bearer …` nebo `X-Monitoring-Token`) čte **jen** `GET /api/monitoring`. Admin ho vydá v Nastavení → Systém. Token **nenahrazuje** stávající Basic Auth plugin.

Admin export konfigurace: `GET /api/admin/export` (hesla, SMTP heslo a tokeny = `REDACTED`). Systémové informace: `GET /api/admin/system`. Historie alarmů (RAM-only, `persistent: false`): `GET /api/alarms/history`.

### Proveď

```bash
curl -u admin:YOUR_PASSWORD \
  http://192.168.1.50:8080/api/monitoring
```

---

## GET /api/me

HTTP Basic Auth. Vrátí `{ "username": "jan", "role": "user" }`. Role jsou jazykově neutrální (`admin` / `user`).

## GET /api/admin/users

Jen `role=admin` (jinak **403**). Seznam účtů bez `password_hash`.

## POST /api/admin/users

Tělo: `{ "username", "password", "role", "enabled" }`. Heslo se uloží jako Argon2.

## GET / PUT / DELETE `/api/admin/users/{id}`

Úprava a smazání. Prázdné heslo při PUT = beze změny. Posledního aktivního admina nelze smazat, deaktivovat ani změnit na `user` (**409**, `error: last_admin`).

## GET /api/settings

Jen `role=admin`. SMTP a prahy pro webové Nastavení. `email.smtp.password` **chybí**; je tu `password_set`.

## PUT /api/settings

Stejné JSON (bez hesla, nebo s novým heslem). Prázdné heslo = ponechat stávající. Atomický zápis YAML + reload v procesu.

## POST /api/settings/test-email

Ověří SMTP (connect → auth → send). Subject `[server-meter][TEST]`. Odpověď `{ "ok": true }` nebo `{ "ok": false, "error": "…" }` bez hesla.
