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
- REST API
- Nagios Core endpoint `GET /api/nagios/check`
- history **only in RAM** (empty after reboot — by design)

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
| [docs/NAGIOS.md](docs/NAGIOS.md) | Nagios Core 4.4.5 (on another host) |
| [docs/SYSTEMD.md](docs/SYSTEMD.md) | Service / journald |
| [docs/STORAGE-POLICY.md](docs/STORAGE-POLICY.md) | RAM-only policy |
| [docs/SECURITY.md](docs/SECURITY.md) | Auth, firewall, TLS |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Diagnostics |
| [docs/UPDATE.md](docs/UPDATE.md) / [docs/UNINSTALL.md](docs/UNINSTALL.md) | Upgrade / remove |
