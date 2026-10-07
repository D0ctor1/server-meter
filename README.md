# server-meter

`server-meter` je webová monitorovací aplikace určená pro Raspberry Pi 5 a senzor Bosch BME690.

Aplikace poskytuje:

- webový dashboard,
- aktuální hodnoty BME690,
- historické grafy,
- systémové informace Raspberry Pi,
- REST API,
- integraci s Nagios Core,
- RAM-only historii měření.

> Historie měření **není zapisována na SD kartu**.
>
> Po restartu Raspberry Pi je historie prázdná. Prázdné grafy ihned po rebootu **nejsou chyba**.

Verze projektu: **1.0.0** (`server_meter/__init__.py`, `pyproject.toml`).

---

## Pro koho je tento dokument

Máte čistě nainstalovaný Ubuntu Server, Raspberry Pi 5 (4 GB), Kingston Industrial 16 GB microSD, BME690 a STEMMA QT / Qwiic kabel. Začněte zde:

1. [Zapojení hardware](docs/HARDWARE.md) — **nejprve vypněte Pi**
2. [Instalace od nuly](docs/INSTALLATION.md)
3. [YAML konfigurace](docs/CONFIGURATION.md)
4. [Webové rozhraní](docs/WEB-INTERFACE.md)
5. [Nagios Core 4.4.5](docs/NAGIOS.md)

---

## Kompatibilita

| Component | Version |
|---|---|
| Raspberry Pi | 5 / 4 GB |
| Architecture | ARM64 (`aarch64`) |
| Ubuntu Server | 26.04.1 LTS 64-bit |
| Sensor | Bosch Sensortec BME690 |
| Interface | I²C bus 1, adresa `0x76` nebo `0x77` |
| Python | 3.11+ (na Ubuntu 26.04 je výchozí `python3` řady **3.14**; ověřte `python3 --version`) |
| BSEC | proprietární Bosch **3.2.0.0 nebo novější** (není součástí tohoto repozitáře) |
| server-meter | 1.0.0 |
| Nagios Core | 4.4.5 |

---

## Architektura

```text
                  ┌──────────────────────┐
                  │     Bosch BME690     │
                  └──────────┬───────────┘
                             │ I²C
                             │
                  ┌──────────▼───────────┐
                  │   Raspberry Pi 5     │
                  │                      │
                  │     server-meter     │
                  │                      │
                  │  Sensor/BSEC layer   │
                  │         │            │
                  │         ▼            │
                  │     RAM history      │
                  │         │            │
                  │   ┌─────┴─────┐      │
                  │   │           │      │
                  │   ▼           ▼      │
                  │ Web UI      REST API │
                  └───┬───────────┬──────┘
                      │           │
                      │           │ HTTP
                      │           ▼
                 Web browser   Nagios Core
```

Skutečné vrstvy v kódu:

| Vrstva | Soubory |
|---|---|
| I²C | `server_meter/sensor/i2c_bus.py` (`smbus2`) |
| BME690 SensorAPI v1.1.0 | `server_meter/sensor/bme690.py` |
| volitelný BSEC 3.x | `server_meter/sensor/bsec.py` (ctypes, `libalgobsec.so`) |
| mock bez hardware | `server_meter/sensor/mock.py` |
| RAM historie | `server_meter/storage/ram_buffer.py` |
| měřicí smyčka | `server_meter/service.py` |
| HTTP | FastAPI v `server_meter/app.py` a `server_meter/api/` |
| UI | `web/index.html`, `web/js/app.js` |

## Tok dat a SD karta

```text
BME690
   │
   ▼
Measurement
   │
   ▼
RAM BUFFER ───────────────► Web/API
   │
   │ memory pressure
   ▼
delete oldest samples

   X
   │
   ▼
SD CARD
```

> Šipka z RAM na SD kartu záměrně neexistuje.

Aplikace za běhu **nezapisuje** naměřená data, historii ani BSEC stav na disk. Na SD kartě smí být jen kód, venv, YAML a systemd unit. Podrobnosti: [docs/STORAGE-POLICY.md](docs/STORAGE-POLICY.md).

---

## Dokumentace

| Dokument | Obsah |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Od čistého Ubuntu po dashboard (krok za krokem) |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Pinout, kabel, bezpečné zapojení |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Každá položka YAML |
| [docs/BME690-BSEC.md](docs/BME690-BSEC.md) | I²C driver, proprietární BSEC, ARM64 |
| [docs/WEB-INTERFACE.md](docs/WEB-INTERFACE.md) | Login, karty, grafy |
| [docs/API.md](docs/API.md) | REST endpointy a curl |
| [docs/NAGIOS.md](docs/NAGIOS.md) | Nagios Core 4.4.5 |
| [docs/SYSTEMD.md](docs/SYSTEMD.md) | Služba, logy, volatile journald |
| [docs/STORAGE-POLICY.md](docs/STORAGE-POLICY.md) | RAM-only, audit zápisů na SD |
| [docs/SECURITY.md](docs/SECURITY.md) | Basic Auth, práva, TLS, firewall |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Diagnostika |
| [docs/UPDATE.md](docs/UPDATE.md) | Upgrade |
| [docs/UNINSTALL.md](docs/UNINSTALL.md) | Odinstalace |

---

## Rychlý přehled po instalaci

| Položka | Hodnota v této implementaci |
|---|---|
| Aplikační adresář | `/opt/server-meter` |
| Python venv | `/opt/server-meter/venv` (**ne** `.venv`) |
| Konfigurace | `/etc/server-meter/config.yaml` |
| Systemd unit | `/etc/systemd/system/server-meter.service` |
| Služba | `server-meter.service` |
| Uživatel | `server-meter` (skupina `i2c`) |
| Poslech | `0.0.0.0:8080` |
| Spuštění | `python -m server_meter --config /etc/server-meter/config.yaml` |
| UI | `http://RPI_IP:8080/` |
| Health | `GET /api/health` (ve výchozím stavu **bez** hesla) |

`RPI_IP` nahraďte adresou z `hostname -I` (příklad: `192.168.1.50`).

---

## Známá omezení implementace

Tyto body **nejsou** zamlčené. Dokumentace je popisuje tam, kde na ně narazíte:

1. Bosch BSEC se **nestahuje automaticky** (proprietární licence). Bez `libalgobsec.so` běží fyzické hodnoty T/p/RH/gas; IAQ, eCO2 a bVOC zůstanou `null`.
2. BSEC wrapper volá `bsec_do_steps`, **nevolá** `bsec_sensor_control`. Heater řídí vlastní forced mode (výchozí 320 °C / 150 ms). Kvalita IAQ se může lišit od oficiálního Bosch integration example.
3. `scripts/install.sh` službu **povolí**, ale **nespustí**. Příklad YAML obsahuje heslo `CHANGE_ME`; v `environment: production` proces **odmítne start**, dokud heslo nezměníte.
4. Statické `/css`, `/js`, `/vendor` **nevyžadují** Basic Auth. HTML `/` a API (kromě health) ano.
5. Výchozí I²C adresa v `config/config.example.yaml` je **0x77**. Po `i2cdetect` ji musíte sladit s realitou (`0x76` nebo `0x77`).
6. `NagiosState.UNKNOWN = 3` je numericky větší než `CRITICAL = 2`. Při současném UNKNOWN (inicializace bez vzorku) a třeba vysoké teplotě CPU zůstane UNKNOWN. Po prvním vzorku se to v běžném provozu neprojeví.
7. `pyproject.toml` classifery uvádějí Python 3.11–3.13; Ubuntu 26.04 dodává **3.14**. `requires-python` je `>=3.11`. Na 3.14 spouštějte testy po instalaci (`python -m pytest`).

---

## Licence

MIT pro server-meter. Kompenzační vzorce BME690 vycházejí z Bosch Sensortec BME690 SensorAPI v1.1.0 (BSD-3-Clause). BSEC zůstává proprietárním softwarem Bosch — musíte ho získat sami. Viz [docs/BME690-BSEC.md](docs/BME690-BSEC.md).
