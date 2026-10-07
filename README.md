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
- Nagios Core: one self-contained `check_server_meter.sh` (curl only; no extra plugin config file). `$ARG1$` selects the metric so each value is its own Nagios service and performance-data series.
- history and alarm state **only in RAM** (empty after reboot — by design)

## Nagios Core 4.4.5

Nagios Core does not graph. It runs a check, stores the current state, and (when enabled) appends performance data for a graphing backend such as PNP4Nagios or Nagiosgraph.

One shell plugin on the Nagios host talks to the Pi. Do not add `/etc/nagios/server-meter.conf` and do not install extra interpreters on the Nagios host.

```text
Nagios Core 4.4.5
        │
        │  check_server_meter.sh $ARG1$
        ▼
check_server_meter.sh
        │  GET /api/monitoring  (once per check)
        ▼
server-meter on the Raspberry Pi
```

### Why one plugin and many services

- **One plugin** — URL, username, password, timeouts and WARNING/CRITICAL limits live in `check_server_meter.sh`. Every service calls that same file.
- **Many services** — `$ARG1$` is the metric name (`temperature`, `iaq`, `ram`, …). Each service has its own state, output line and `| perfdata` series, so PNP4Nagios/Nagiosgraph can draw one graph per value.
- **Health without an argument** — `check_server_meter.sh` or `check_server_meter.sh health` is the overall reachability check (compatible with the previous single service).

### Install / upgrade on the Nagios host

```bash
sudo ./scripts/install_nagios_plugin.sh
```

The installer:

1. Updates `/usr/local/nagios/libexec/check_server_meter.sh` when that directory exists, otherwise `/usr/lib/nagios/plugins/check_server_meter.sh`. Override with `PLUGIN_DIR`.
2. Preserves the configuration block already in the installed script (URL/password/thresholds).
3. Installs `server-meter.cfg` (command + host + services) into the Nagios objects directory. Re-running overwrites that same file — no `check_server_meter_2`.
4. Skips `define host` when `host_name server-meter` already exists (`INCLUDE_HOST=auto`).
5. Adds `cfg_file=` to `nagios.cfg` only when that path is not already included.
6. Runs `$NAGIOS_BIN -v $NAGIOS_CFG` (default `/usr/local/nagios/bin/nagios -v /usr/local/nagios/etc/nagios.cfg`). On failure it does **not** reload. On success it reloads Nagios (`NAGIOS_RELOAD=0` to skip).

Mode **0700**, owner `nagios:nagios`. The password is in the script.

### Plugin configuration (inside the `.sh` only)

```bash
SERVER_METER_URL="http://RPI_IP:8080"
SERVER_METER_USERNAME="admin"
SERVER_METER_PASSWORD="YOUR_PASSWORD"
TEMP_WARNING=45
TEMP_CRITICAL=50
CPU_TEMP_WARNING=70
CPU_TEMP_CRITICAL=80
RAM_WARNING=85
RAM_CRITICAL=95
```

Those constants are the Nagios thresholds. Email Settings on the Pi are a separate SMTP path (hysteresis/duration) and are not a second plugin config file.

HTTPS verifies certificates (`CURL_INSECURE=false`). Set `CURL_INSECURE=true` only for a self-signed lab cert.

### Command, host, services

```nagios
define command {
    command_name    check_server_meter
    command_line    /usr/local/nagios/libexec/check_server_meter.sh $ARG1$
}
```

`check_command check_server_meter!temperature` passes `temperature` as `$ARG1$`. Add a metric by handling it in the script `case` and adding one `define service`. Template: `scripts/nagios/server-meter.cfg`.

Nagios should show:

```text
server-meter
├── Server Meter Health
├── Sensor Availability
├── BME690 Temperature / Humidity / Pressure / Gas Resistance
├── BME690 IAQ / IAQ Accuracy / Static IAQ / Static IAQ Accuracy
├── BME690 eCO2 / bVOC
├── CPU Temperature / CPU Load
└── RAM Usage
```

IAQ numbers are BSEC anomaly indexes, not medical limits.

### Performance data and graphs

Each numeric check prints Nagios perfdata after `|`:

```text
OK - BME690 temperature=24.3 C | temperature=24.3;45;50
OK - CPU temperature=48.1 C | cpu_temperature=48.1;70;80
OK - RAM usage=31.7 % | ram=31.7;85;95
```

- **Nagios service** = current state + current value + perfdata in the check result.
- **Graphing backend** = history / RRD / graphs (PNP4Nagios, Nagiosgraph, or whatever already processes perfdata).

Nagios Core itself does not create those graphs. Enable `process_performance_data=1` and keep the existing PNP4Nagios/Nagiosgraph integration if you already have one — do not install a second graphing stack. Details: [docs/NAGIOS.md](docs/NAGIOS.md).

### Manual tests

```bash
/usr/local/nagios/libexec/check_server_meter.sh --help
/usr/local/nagios/libexec/check_server_meter.sh
/usr/local/nagios/libexec/check_server_meter.sh temperature
/usr/local/nagios/libexec/check_server_meter.sh iaq
/usr/local/nagios/libexec/check_server_meter.sh cpu_temperature
echo $?
```

Exit codes: `0` OK, `1` WARNING, `2` CRITICAL (including unreachable HTTP), `3` UNKNOWN (invalid JSON, missing metric, unconfigured password).

The plugin never writes JSON, cache or sensor history to disk.

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
