# server-meter

RAM-only environmental monitor for **Raspberry Pi 5** + **Bosch BME690** on
**Ubuntu Server 26.04.1 LTS** (ARM64).

The process reads the sensor, keeps history in a memory ring buffer, serves a
light HTML UI and REST API, and exposes a Nagios Core 4.4.5 check. After a
reboot the graphs are empty. **Sensor data are never written to the SD card.**

---

## 1. Purpose

Long-running 24/7 monitoring of indoor air and Pi health with:

- almost no SD-card writes (Kingston 16 GB industrial card)
- low CPU / RAM on a 4 GB Pi 5
- a surviving web UI when the BME690 is unplugged
- HTTP Basic Auth from YAML (password is not in source)

## 2. Hardware

| Item | Supported |
| --- | --- |
| Board | Raspberry Pi 5, 4 GB RAM, ARM64 |
| Storage | microSD (application + config only) |
| Sensor | Bosch Sensortec BME690 over I²C |
| Address | `0x76` or `0x77` (YAML) |
| I²C bus | default `1` (`/dev/i2c-1`) |

## 3. Software

- Python 3.11+ (3.12 on current Ubuntu images)
- FastAPI, Uvicorn, Pydantic, PyYAML, smbus2
- Optional proprietary **Bosch BSEC 3.2.0.0+** for IAQ / eCO2 / bVOC
- systemd + journald (prefer volatile journal)
- Nagios Core 4.4.5 via HTTP

No SQLite, Influx, Prometheus TSDB, Redis, CSV, or measurement log files.

## 4. Architecture

```
I²C  →  BME690 SensorAPI port  →  optional BSEC 3.x (RAM state)
                                      ↓
                               normalize (null if missing)
                                      ↓
                          RamBuffer (deque, hard cap)
                                      ↓
                    FastAPI  →  /api/*  +  static UI
```

Layers live in `server_meter/sensor`, `storage`, `monitoring`, `api`.

## 5. Install Ubuntu packages

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev python3-pip \
    build-essential i2c-tools git
```

## 6. Enable I²C

```bash
sudo ./scripts/enable_i2c.sh
sudo reboot   # if /dev/i2c-1 was missing
sudo i2cdetect -y 1
```

Expect `76` or `77` on bus 1.

## 7. Wire the BME690

3.3 V, GND, SDA → GPIO2, SCL → GPIO3. See [docs/bme690-bsec.md](docs/bme690-bsec.md).

## 8. Install BSEC (manual, proprietary)

Bosch BSEC is **not** in this repo and is **not** open source.

1. Accept the Bosch license.
2. Download BSEC **3.2.0.0 or newer** from
   [Bosch BME688/BME690 software](https://www.bosch-sensortec.com/software-tools/software/bme688-and-bme690-software/).
3. Place the **aarch64 / PiFour_Armv8** `libalgobsec.so` on the Pi.
4. Set `sensor.bsec.library_path` in YAML.

Without BSEC the service still runs; IAQ/eCO2/bVOC stay `null`.
Full steps: [docs/bme690-bsec.md](docs/bme690-bsec.md).

## 9. Python environment

From the project tree (or after `scripts/install.sh`):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Dev / tests:

```bash
pip install -r requirements-dev.txt
pytest
```

## 10. YAML configuration

Copy [config/config.example.yaml](config/config.example.yaml) to
`/etc/server-meter/config.yaml` or `config/config.yaml`.

The process **reads** YAML at startup and **never writes it back**.

Production will **refuse to start** if:

- `web.auth.password` is `CHANGE_ME` or shorter than 8 characters
- auth is disabled
- OpenAPI docs are enabled
- I²C address is not `0x76`/`0x77`
- BSEC LP is combined with `interval_seconds < 3`
- warning/critical thresholds are inverted

Desktop without hardware:

```bash
python -m server_meter --config config/config.mock.yaml
```

## 11. Run (foreground)

```bash
python -m server_meter --config /etc/server-meter/config.yaml
```

Override listen address: `--host 0.0.0.0 --port 8080`.

## 12. systemd

```bash
sudo ./scripts/install.sh
# edit /etc/server-meter/config.yaml  (password + I2C address)
sudo systemctl start server-meter
sudo systemctl status server-meter
```

Unit: [systemd/server-meter.service](systemd/server-meter.service)

Hardened (`ProtectSystem=strict`, `DeviceAllow=/dev/i2c-*`, no writable
app paths). The service user is in group `i2c`.

Enable on boot is done by the install script (`systemctl enable`).

## 13. Web UI

`http://<pi-ip>:8080/`

Browser Basic Auth. Cards for temperature, humidity, pressure, gas
resistance, IAQ, IAQ accuracy, eCO2, bVOC. Charts poll incrementally
(`/api/history?since=`) every 5 s and current values every 4 s. Chart.js
animations are off.

After reboot the charts start empty.

## 14. REST API

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| GET | `/api/health` | optional | liveness, no history |
| GET | `/api/status` | yes | counters, no secrets |
| GET | `/api/current` | yes | latest sample (`null` if missing) |
| GET | `/api/history` | yes | `?seconds=` `?limit=` `?since=` |
| GET | `/api/system` | yes | Pi CPU/RAM/uptime |
| GET | `/api/sensor` | yes | driver + health |
| GET | `/api/nagios/check` | yes | plugin text + headers |
| GET | `/` | yes | UI |
| GET | `/docs` `/redoc` | n/a | only if `api_docs_enabled` |

Missing sensor values are JSON `null`, never invented numbers.
`/api/history` reads RAM only (`"persistent": false`).

## 15. Nagios

See [docs/nagios.md](docs/nagios.md). Example:

```nagios
define command {
    command_name    check_server_meter
    command_line    $USER1$/check_server_meter.py --url http://$HOSTADDRESS$:8080/api/nagios/check --user $ARG1$ --password $ARG2$
}

define service {
    use                 generic-service
    host_name           raspberrypi
    service_description server-meter
    check_command       check_server_meter!admin!YOUR_PASSWORD
}
```

Exit codes: 0 OK, 1 WARNING, 2 CRITICAL, 3 UNKNOWN.

## 16. Troubleshooting

| Symptom | Check |
| --- | --- |
| Service exits immediately | `journalctl -u server-meter -e` — usually `CHANGE_ME` password |
| UI 401 | username/password in YAML |
| Sensor unavailable, UI up | expected if wiring/I²C is down; watch recoveries in `/api/status` |
| `i2cdetect` empty | `enable_i2c.sh`, 3.3 V, address, `dtoverlay` |
| Chip ID error | not a BME690, or bus noise |
| IAQ always null | BSEC `.so` not installed or `bsec.enabled: false` |
| IAQ accuracy 0 after reboot | RAM-only BSEC state; wait for convergence |
| High journal writes | `logging.access_log: false`, journald `Storage=volatile` |
| Permission denied `/dev/i2c-1` | user in group `i2c`, `DeviceAllow` in the unit |

## 17. SD-card protection

- No measurement database or CSV
- No application `.log` files
- No BSEC state file
- Access log off
- systemd `ProtectSystem=strict` and empty `ReadWritePaths`
- Documented volatile journald — [docs/storage-policy.md](docs/storage-policy.md)

## 18. RAM-only history

```yaml
history:
  max_samples: 10000          # also capped internally at 20000
  max_age_seconds: 86400
memory_protection:
  enabled: true
  warning_percent: 70         # drop oldest 10%
  critical_percent: 80        # drop oldest 25%
  emergency_percent: 90       # drop oldest 50%
```

Oldest samples go first. Remaining history stays contiguous. Nothing is
spilled to disk.

## 19. Backup

Backup **only** configuration and the application tree:

```bash
sudo cp /etc/server-meter/config.yaml /root/server-meter-config.yaml
```

There is no measurement backup. That is the product requirement.

## 20. Upgrade

```bash
cd /path/to/new-tree
sudo ./scripts/install.sh
sudo systemctl restart server-meter
```

`/etc/server-meter/config.yaml` is kept. History in RAM resets.

## 21. Uninstall

```bash
sudo ./scripts/uninstall.sh          # keeps /etc/server-meter
sudo ./scripts/uninstall.sh --purge  # also deletes config and the service user
```

---

## Security notes

- Production debug/docs are off.
- Tracebacks are not sent to clients.
- Passwords never appear in `/api/status` or logs.
- HTTP Basic Auth is **not encrypted**. Use a reverse proxy with TLS off
  the Pi if the network is not a trusted LAN.
- Request size is capped (`web.max_request_bytes`).

## Dependencies (why each exists)

| Package | Reason |
| --- | --- |
| fastapi | REST + static UI |
| uvicorn | ASGI server |
| pydantic | config/API validation |
| PyYAML | YAML config |
| smbus2 | Linux I²C |
| httpx / pytest (dev) | tests only |

psutil is **not** used; `/proc` and `/sys` provide system metrics.

## Project layout

```
server-meter/
├── README.md
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── config/
├── server_meter/
│   ├── api/
│   ├── sensor/
│   ├── storage/
│   ├── monitoring/
│   └── models/
├── web/
├── systemd/
├── scripts/
├── tests/
└── docs/
```

## License

MIT for server-meter. BME690 compensation is a port of Bosch Sensortec
BME690 SensorAPI v1.1.0 (BSD-3-Clause). BSEC remains Bosch proprietary
software that you must obtain yourself.
