# Webové rozhraní

## Adresa

Po startu služby (port z YAML, výchozí 8080):

```text
http://RPI_IP:8080/
```

`RPI_IP` zjistíte:

```bash
hostname -I
```

Příklad: `http://192.168.1.50:8080/` — `192.168.1.50` je **příklad**.

## Přihlášení

HTML `/` vyžaduje **HTTP Basic Authentication** (`web.auth.enabled: true`).

Prohlížeč zobrazí nativní dialog. Zadejte `web.auth.username` a `web.auth.password` z `/etc/server-meter/config.yaml`.

Heslo se **neposílá v URL**.

Bez správných údajů API vrací **401**. UI po 401 zobrazí text „Authentication required“.

TLS se v aplikaci **není**. Na nedůvěryhodné síti použijte reverse proxy — [SECURITY.md](SECURITY.md).

Statické soubory `/css/style.css`, `/js/app.js`, `/vendor/chart.umd.min.js` autentizaci **nevyžadují** (tak je to v `server_meter/app.py`).

---

## Co dashboard skutečně zobrazuje

Soubory: `web/index.html`, `web/js/app.js`. Texty UI jsou **anglicky**.

### Stavový řádek (čtyři karty)

| Karta | Zdroj API | Obsah |
|---|---|---|
| Server | `/api/status` | `online` / `unreachable`; app uptime v sekundách |
| Sensor | `/api/status` | `ok`, `unavailable`, `initializing`, `error`, `unknown`; stáří vzorku |
| CPU | `/api/system` | teplota °C, CPU %, load1, kmitočet MHz |
| RAM | `/api/system` | využití %, used / total GiB |

Barvy: zelená OK, žlutá varování (CPU ≥ 70 °C, RAM ≥ 70 %), červená (CPU ≥ 80 °C, RAM ≥ 85 %, sensor unavailable).

### Aktuální hodnoty (osm karet)

| Karta | JSON pole | Jednotka v UI |
|---|---|---|
| Temperature | `temperature` | °C |
| Humidity | `humidity` | % |
| Pressure | `pressure` | hPa |
| Gas resistance | `gas_resistance` | kΩ (API je v Ω, UI dělí 1000) |
| IAQ | `iaq` | 0–500 |
| IAQ accuracy | `iaq_accuracy` | 0–3 + popisek |
| eCO2 | `eco2` | ppm |
| bVOC | `bvoc` | ppm |

Chybějící hodnota (typicky bez BSEC) = **—**.

IAQ accuracy popisky v JS: `stabilizing` (0), `low` (1), `medium` (2), `high` (3).

### Grafy (Chart.js, vendored 4.4.1)

| Graf | Pole | Jednotka |
|---|---|---|
| Temperature | `temperature` | °C |
| Humidity | `humidity` | % |
| Pressure | `pressure` | hPa |
| Gas resistance | `gas_resistance` | Ω (ne kΩ) |
| IAQ | `iaq` | IAQ |
| eCO2 | `eco2` | ppm |
| bVOC | `bvoc` | ppm |

Okno: 15 min / 1 h (výchozí) / 6 h / 24 h. Maximálně 720 bodů na graf.

### Polling (zátěž Pi)

| Dotaz | Interval |
|---|---|
| `/api/status` + `/api/current` + `/api/system` | 4 s |
| `/api/history?since=` (přírůstek) | 5 s |
| první / změna okna | `/api/history?seconds=&limit=720` |

Frontend **nestahuje** celou historii každé 4 sekundy.

Animace Chart.js jsou vypnuté (`animation: false`).

---

## Grafy a restart

Data grafů jsou jen z RAM bufferu.

```bash
sudo systemctl restart server-meter
```

Historie se smaže. Grafy jsou prázdné, dokud nedorazí nové vzorky (výchozí interval 5 s).

> Prázdné grafy bezprostředně po restartu **nejsou chyba**.

Patička: `UTC timestamps internally · local time in the browser`.

---

## Raspberry Pi metriky

Z `/proc` a `/sys` (`server_meter/monitoring/system.py`):

- CPU teplota (`thermal_zone0` nebo hwmon)
- load 1/5/15
- CPU % (delta `/proc/stat`)
- kmitočet MHz
- RAM total / used / available / %
- uptime
- volitelně `vcgencmd get_throttled` nebo sysfs, pokud existuje

Na Ubuntu bez `vcgencmd` budou throttle příznaky `null` — to je v pořádku.

---

## OpenAPI

`/docs` a `/redoc` existují jen když `web.api_docs_enabled: true`. V `environment: production` to start **zakáže**.
