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

HTML `/` je veřejné, aby šlo lokalizovat přihlašovací formulář. **Data měření** jdou jen přes HTTP Basic Auth na `/api/*` (`web.auth.enabled: true`).

Dashboard zobrazí formulář (CZ: Přihlášení / Uživatelské jméno / Heslo / Přihlásit). Zadejte `web.auth.username` a `web.auth.password` z `/etc/server-meter/config.yaml`. Špatné údaje: **Nesprávné uživatelské jméno nebo heslo** (EN: Invalid username or password).

Heslo se **neposílá v URL**. Prohlížeč ho drží v `sessionStorage` a posílá jako `Authorization: Basic` na API. Nagios a `curl -u` fungují stejně jako dřív.

Bez správných údajů API vrací **401** (`{"detail":"Authentication required"}` / `Invalid credentials` — tyto JSON texty jsou součástí API a nemění se s locale).

Pokud je v YAML stále `password: CHANGE_ME`, dashboard zobrazí žlutý pruh (lokalizovaný podle `web.locale`).

API příznak: `application.default_password_active` (boolean, heslo se neposílá).

TLS se v aplikaci **není**. Na nedůvěryhodné síti použijte reverse proxy — [SECURITY.md](SECURITY.md).

Statické soubory `/css/style.css`, `/js/app.js`, `/js/i18n.js`, `/vendor/chart.umd.min.js` autentizaci **nevyžadují** (tak je to v `server_meter/app.py`).

---

## Jazyk UI

Jazyk určuje jen YAML, ne přepínač na stránce:

```yaml
web:
  locale: "CZ"   # čeština (výchozí)
# locale: "EN"   # angličtina
```

Chybějící klíč = `CZ`. Po změně `sudo systemctl restart server-meter`. Překlady jsou v `web/js/i18n.js`; `app.js` volá `t("sensor.temperature")` a podobné klíče. Jednotky (`°C`, `%`, `hPa`, `Ω`, `ppm`) a zkratky (BME690, BSEC, IAQ, eCO₂, bVOC, CPU, RAM) se nepřekládají. Datum a čas v prohlížeči jde přes `Intl.DateTimeFormat` (`cs-CZ` / `en-GB`). Interní API timestampy zůstávají unix time.

---

## Co dashboard skutečně zobrazuje

Soubory: `web/index.html`, `web/js/app.js`, `web/js/i18n.js`. Texty UI jsou **česky** (`locale: CZ`) nebo **anglicky** (`locale: EN`).

### Stavový řádek (čtyři karty)

| Karta | Zdroj API | Obsah |
|---|---|---|
| Server | `/api/status` | stav `online` / `unreachable` (UI přeloží); app uptime v sekundách |
| Sensor | `/api/status` | API: `ok`, `unavailable`, `initializing`, `error`, `unknown`; UI zobrazí lokalizovaný popisek; stáří vzorku |
| CPU | `/api/system` | teplota °C, CPU %, load1, kmitočet MHz |
| RAM | `/api/system` | využití %, used / total GiB |

Barvy: zelená OK, žlutá varování (CPU ≥ 70 °C, RAM ≥ 70 %), červená (CPU ≥ 80 °C, RAM ≥ 85 %, sensor unavailable).

### Aktuální hodnoty

| Karta | JSON pole | Jednotka v UI |
|---|---|---|
| Teplota / Temperature | `temperature` | °C |
| Vlhkost / Humidity | `humidity` | % |
| Tlak / Pressure | `pressure` | hPa |
| Odpor plynu / Gas resistance | `gas_resistance` | kΩ (API je v Ω, UI dělí 1000) |
| IAQ | `iaq` | 0–500 |
| Přesnost IAQ / IAQ accuracy | `iaq_accuracy` | 0–3 + lokalizovaný popisek |
| Statické IAQ / Static IAQ | `static_iaq` | BSEC, jinak — |
| Přesnost statického IAQ / Static IAQ accuracy | `static_iaq_accuracy` | 0–3 + lokalizovaný popisek |
| eCO₂ | `eco2` | ppm |
| bVOC | `bvoc` | ppm |

Chybějící hodnota (typicky bez BSEC) = **—**.

IAQ accuracy v API zůstává `stabilizing` / `low` / `medium` / `high`. UI to přeloží (CZ: stabilizace, nízká, střední, vysoká).

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

Animace Chart.js jsou vypnuté (`animation: false`). Každý graf sedí v rámečku **220 px** (`.chart-frame`). Výška se nesmí dávat na `<canvas>` — Chart.js `responsive` by jinak kartu při každém `update()` natahoval dolů.

---

## Grafy a restart

Data grafů jsou jen z RAM bufferu.

```bash
sudo systemctl restart server-meter
```

Historie se smaže. Grafy jsou prázdné, dokud nedorazí nové vzorky (výchozí interval 5 s).

> Prázdné grafy bezprostředně po restartu **nejsou chyba**.

Patička (CZ): `Interně časová razítka UTC · v prohlížeči místní čas`.

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
