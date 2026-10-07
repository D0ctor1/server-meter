# Storage policy

**Sensor data are RAM-only.**

This document is the disk-write audit for server-meter. It exists so an
operator can prove that BME690 samples never land on the Kingston industrial
SD card during normal 24/7 operation.

## What may exist on the SD card

Static, operator-managed files only:

| Path | Why it is on disk | Written at runtime? |
| --- | --- | --- |
| Python sources under `server_meter/` | Application code | No |
| `web/` HTML, CSS, JS, Chart.js | Frontend | No |
| `config/*.yaml` examples and `/etc/server-meter/config.yaml` | Configuration | No — read once at start |
| `systemd/server-meter.service` | Unit file | No |
| `scripts/` | Install / Nagios plugin | No |
| `docs/`, `README.md`, `LICENSE` | Documentation | No |
| Python venv / site-packages | Installed dependencies | Only during install/upgrade |

The process **never** opens a measurement database, CSV, JSON history file,
pickle, shelve, SQLite, or BSEC state file.

## What must stay in RAM

| Data | Location | After reboot |
| --- | --- | --- |
| Current sample | `MeterService.current` | Reloaded from the sensor |
| History | `RamBuffer` (`collections.deque`) | Empty |
| BSEC algorithm state | ctypes instance buffer | Re-initialized (IAQ accuracy starts low) |
| Runtime counters | `RuntimeStats` | Reset |
| Memory-pressure decisions | `MemoryProtector` | Reset |

When RAM is high, the oldest samples are discarded. They are **not** spilled
to disk.

## What the application writes at runtime

Nothing on purpose.

- Python `logging` goes to **stderr**.
- systemd captures stderr as **journald** (`StandardOutput=journal`).
- Uvicorn access logs are **disabled** by default (`logging.access_log: false`).
- Per-sample values are **never** logged.

There is no application `*.log` file and no logrotate snippet, because no
log file is created.

## Where writes can still appear (OS / journald)

The Linux kernel, apt, and journald are outside this process. On Ubuntu they
can write to the SD card if journald is persistent:

```ini
# /etc/systemd/journald.conf
[Journal]
Storage=volatile
RuntimeMaxUse=32M
```

Then:

```bash
sudo systemctl restart systemd-journald
```

`Storage=volatile` keeps logs in `/run/log/journal` (tmpfs), not on the SD
card. This is recommended for 24/7 server-meter hosts.

Swap on the SD card is also a write amplifier. Prefer zram or no swap:

```bash
sudo systemctl mask swap.target   # optional; understand the RAM impact first
```

## BSEC state

Bosch BSEC can export a calibration blob via `bsec_get_state`. server-meter
**does not call this for persistence**. `sensor.bsec.persist_state` cannot be
set to `true`. After reboot, IAQ accuracy may stay at 0–2 until BSEC
re-converges. That is intentional.

If you compiled the community `bme69x` wrapper, do not run its
save-state examples against this host.

## How to verify there are no periodic measurement writes

1. Boot the Pi, start `server-meter`, wait until the UI shows live samples.
2. In one shell, watch block-layer writes:

   ```bash
   sudo iostat -dx 5
   ```

   The SD device (`mmcblk0` or similar) should not show a steady write
   cadence matching `sensor.interval_seconds`.

3. Process-level I/O:

   ```bash
   sudo apt install -y iotop sysstat
   sudo iotop -o -p "$(systemctl show -p MainPID --value server-meter)"
   ```

   The server-meter PID should not be listed as a writer during idle
   polling.

4. Open-file audit:

   ```bash
   sudo ls -l /proc/$(systemctl show -p MainPID --value server-meter)/fd
   ```

   You should see the listening socket, I²C (`/dev/i2c-1`), and read-only
   files (`config.yaml`, static assets). You must **not** see a growing
   history file.

5. Filesystem watch (optional):

   ```bash
   sudo apt install -y inotify-tools
   sudo inotifywait -m -r -e modify,create,attrib /opt/server-meter /etc/server-meter /var/log
   ```

   During normal sampling this should stay quiet except unrelated system
   paths. `/var/log/journal` is the usual suspect if journald is persistent.

6. After `sudo systemctl restart server-meter` (or reboot):

   ```bash
   curl -u admin:PASSWORD http://127.0.0.1:8080/api/history
   ```

   `count` must be `0` (or only samples collected since the restart).
   `persistent` is always `false`.

## Libraries and caches

| Library | Disk risk | Mitigation |
| --- | --- | --- |
| FastAPI / Starlette | None for this usage | No file sessions |
| Uvicorn | Access log / `--reload` watchfiles | Access log off, no reload |
| PyYAML | Reads config once | Never dumped back |
| smbus2 | `/dev/i2c-*` only | Character device |
| ctypes BSEC | Could write if we called get_state | We do not persist state |
| Chart.js | Browser memory only | No server-side cache of samples |
| Python | `__pycache__` `.pyc` | Created at install/import; not measurement data. The unit uses `ProtectSystem=strict` so the live service cannot write `.pyc` under `/opt`. |

pytest, pip, and editors write caches during development. That is not the
production service path.

## Configuration vs sensor data

```
PERSISTENT (SD card, operator-changed):
  config.yaml, source, systemd unit, venv

VOLATILE (RAM, discarded on restart):
  measurements, history, BSEC state, statistics
```
