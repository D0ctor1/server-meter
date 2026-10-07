# server-meter

RAM-only BME690 monitor for Raspberry Pi 5 (Ubuntu Server 26.04 ARM64).

## Installation

Connect the BME690 **with the Raspberry Pi powered off**:

```text
RED    → PIN 1   (3.3V)
BLACK  → PIN 6   (GND)
BLUE   → PIN 3   (GPIO2 / SDA)
YELLOW → PIN 5   (GPIO3 / SCL)
```

Do **not** connect VCC to 5 V.

Then, on Ubuntu Server:

```bash
git clone https://github.com/D0ctor1/server-meter.git
cd server-meter
sudo ./install.sh
```

When the installer prints `SERVER-METER INSTALLATION COMPLETE`, open:

```text
http://RPI_IP:8080
```

(`RPI_IP` is shown at the end of `install.sh`, or run `hostname -I`.)

Default login:

```text
Username: admin
Password: CHANGE_ME
```

## ⚠️ IMPORTANT – CHANGE DEFAULT PASSWORD

Change the password in:

```text
/etc/server-meter/config.yaml
```

```yaml
web:
  auth:
    username: "admin"
    password: "CHANGE_ME"
```

Then:

```bash
sudo systemctl restart server-meter
```

That is the only manual configuration step.

## Localization

server-meter supports:

- CZ – Czech
- EN – English

Default:

CZ

Configuration:

```yaml
web:
  locale: "CZ"
```

For English:

```yaml
web:
  locale: "EN"
```

After a change:

```bash
sudo systemctl restart server-meter
```

If `web.locale` is omitted, the UI stays Czech. The installer never rewrites an existing locale. REST API JSON keys and `/api/nagios/check` are not translated.

Upgrade (keeps the password and YAML):

```bash
sudo ./install.sh
```

or:

```bash
sudo ./update.sh
```

Uninstall (keeps config unless you pass `--purge`):

```bash
sudo ./uninstall.sh
```

## What you get

- dashboard (temperature, humidity, pressure, gas, IAQ, eCO2, bVOC, Pi CPU/RAM)
- Settings (gear) for SMTP / email anomaly alerts
- REST API including `GET /api/monitoring`
- Nagios Core: one self-contained `check_server_meter.sh` (curl only; no Python/jq/extra config file)
- history and alarm state **only in RAM** (empty after reboot — by design)

## Nagios Core 4.4.5 integration

Nagios only executes a single plugin. URL, username, password and timeouts live **inside** that script. Do not add `/etc/nagios/server-meter.conf` or install Python 3 on the Nagios host.

```text
Nagios Core 4.4.5
        │
        │ execute (no arguments)
        ▼
check_server_meter.sh     curl + HTTP Basic Auth
        │
        ▼
server-meter  GET /api/monitoring
```

1. **Architecture** — shell plugin on the Nagios host; Raspberry Pi only exposes authenticated HTTP.
2. **Install location** — default `/usr/lib/nagios/plugins/check_server_meter.sh`. Override `PLUGIN_DIR` at the top of `scripts/install_nagios_plugin.sh` (or in the environment) if your Core build uses `/usr/local/nagios/libexec`.
3. **URL** — edit `SERVER_METER_URL` in the installed script (`http://RPI_IP:8080` or `https://…`). `/api/monitoring` is appended when missing.
4. **Username / password** — `SERVER_METER_USERNAME` and `SERVER_METER_PASSWORD` in the same file. The installer sets mode **0700** `nagios:nagios` because the password is in the script. Never world-readable.
5. **Manual test** — `/usr/lib/nagios/plugins/check_server_meter.sh` then `echo $?`. No arguments.
6. **Exit codes** — `0` OK, `1` WARNING, `2` CRITICAL (including unreachable), `3` UNKNOWN (invalid JSON / unconfigured password).
7. **Performance data** — after `|`, e.g. `temperature=24.3;45;50 ram=31.7;70;85`. Values come from `/api/monitoring`; missing sensor fields are omitted.
8. **Nagios command** — `command_line /usr/lib/nagios/plugins/check_server_meter.sh` and `check_command check_server_meter` with no `$ARG$`. Example: `scripts/nagios/server-meter.cfg.example`.
9. **Validate Nagios** — `nagios -v /path/to/nagios.cfg` (or `nagios4 -v /etc/nagios4/nagios.cfg`), then `systemctl reload nagios`.
10. **WARNING / CRITICAL** — raise a threshold on the Pi Settings page or wait for a real anomaly; `overall` from server-meter is the plugin’s state. Unplug the sensor or stop `server-meter` to see CRITICAL unreachable / sensor unavailable.

HTTPS verifies certificates (`CURL_INSECURE=false`). Set `CURL_INSECURE=true` only for a self-signed lab cert.

The installer is idempotent: it updates only `check_server_meter.sh` and keeps an existing configuration block. It does not modify Python or `nagios.cfg`.

Legacy `GET /api/nagios/check` and `scripts/check_server_meter.py` still exist for older setups.

## Bosch BSEC (IAQ)

BSEC is proprietary Bosch software. `sudo ./install.sh` downloads the official 3.2+ ZIP from bosch-sensortec.com, extracts `PiFour_Armv8/libalgobsec.a`, and links `/opt/server-meter/lib/libalgobsec.so` on this Pi. That is not a git-redistributed binary; running the installer accepts the Bosch license.

Without the library, temperature / humidity / pressure / gas still work; IAQ, eCO2 and bVOC stay empty.

## More documentation

| Document | Topic |
|---|---|
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | What `install.sh` does |
| [docs/HARDWARE.md](docs/HARDWARE.md) | Pinout |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | YAML keys |
| [docs/BME690-BSEC.md](docs/BME690-BSEC.md) | BSEC license / ARM64 library |
| [docs/WEB-INTERFACE.md](docs/WEB-INTERFACE.md) | Dashboard |
| [docs/API.md](docs/API.md) | REST |
| [docs/NOTIFICATIONS.md](docs/NOTIFICATIONS.md) | Email alerts, SMTP, thresholds |
| [docs/NAGIOS.md](docs/NAGIOS.md) | Nagios Core 4.4.5 (on another host) |
| [docs/SYSTEMD.md](docs/SYSTEMD.md) | Service / journald |
| [docs/STORAGE-POLICY.md](docs/STORAGE-POLICY.md) | RAM-only policy |
| [docs/SECURITY.md](docs/SECURITY.md) | Auth, firewall, TLS |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Diagnostics |
| [docs/UPDATE.md](docs/UPDATE.md) / [docs/UNINSTALL.md](docs/UNINSTALL.md) | Upgrade / remove |
