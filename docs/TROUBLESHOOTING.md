# Řešení problémů

Každá sekce: **co vidíte → co spustit → co máte vidět → co dál**.

Než budete měnit vodiče:

```text
VYPNI RASPBERRY PI A ODPOJ NAPÁJENÍ.
```

---

## `SystemError: buffer overflow` při detekci (Python 3.14)

`smbus2.SMBus()` na Ubuntu 26.04 / Python 3.14 / ARM64 volá ioctl `I2C_FUNCS` se 4bajtovým bufferem; jádro zapisuje 8 bajtů. To **není** špatné zapojení.

Oprava je v `server_meter/sensor/i2c_bus.py` (otevření `/dev/i2c-*` bez tohoto ioctl) a detekce jde přes `i2cget`. Aktualizujte kód a znovu:

```bash
cd ~/server-meter
sudo ./install.sh
```

Ověření chip ID bez Pythonu:

```bash
sudo i2cget -y 1 0x76 0xD0 b
sudo i2cget -y 1 0x77 0xD0 b
```

Očekávané: `0x61`.

---

## BME690 není detekován

### Proveď

```bash
ls -l /dev/i2c*
sudo i2cdetect -y 1
```

### Očekávaný výsledek

Existuje `/dev/i2c-1`. V tabulce je `76` nebo `77`.

Příklad (zařízení na 0x76):

```text
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- 76 -- -- -- -- -- -- -- -- --
```

`76` = slave na adrese **0x76**. Analogicky `77` = **0x77**.

### Error: Could not open file `/dev/i2c-1`

I²C není aktivní, nebo jste na špatném busu.

1. `ls -l /dev/i2c*` — je `i2c-0`, `i2c-1`, `i2c-2`?
2. `grep i2c /boot/firmware/config.txt` — musí být `dtparam=i2c_arm=on`
3. `cat /etc/modules-load.d/server-meter-i2c.conf` — `i2c-dev`
4. `sudo ./scripts/enable_i2c.sh` (nebo z `/opt/server-meter`)
5. `sudo reboot`
6. znovu `ls -l /dev/i2c*`

Na Ubuntu Server **nemusí** existovat `raspi-config`. Skript ho použije jen pokud je v PATH.

> ⚠️ **VYŽADUJE OVĚŘENÍ:** Na konkrétním kernelu Ubuntu 26.04 / Pi 5 může být uživatelský I²C na `/dev/i2c-1` (obvyklé) nebo jiném čísle. Skutečný bus je ten, na kterém `i2cdetect` ukáže 0x76/0x77. Ten samý index dejte do `sensor.i2c.bus`.

### Tabulka plná `--`, žádné 76/77

1. **Vypněte Pi, odpojte USB-C.**
2. RED = PIN 1 (3.3 V), **ne 5 V**.
3. BLACK = PIN 6 GND.
4. BLUE = PIN 3 SDA.
5. YELLOW = PIN 5 SCL.
6. STEMMA QT zacvaknutý na breakoutu.
7. Zapněte Pi, znovu `sudo i2cdetect -y 1`.
8. Zkuste `sudo i2cdetect -y 0` a `-y 2`, pokud `-y 1` je prázdné a jiný bus existuje.

Detail zapojení: [HARDWARE.md](HARDWARE.md).

Chip ID BME690 je **0x61**. Jiný senzor (BME280) na stejné adrese tento driver neodpovídá.

---

## 0x76 vs 0x77

Breakout může mít jumper adresy. Example YAML má **0x77**.

### Proveď

V `/etc/server-meter/config.yaml`:

```yaml
sensor:
  i2c:
    bus: 1
    address: 0x76
```

nebo `0x77` podle tabulky.

```bash
sudo systemctl restart server-meter
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/sensor
```

V `driver` uvidíte `"i2c_address": "0x76"` (hex řetězec ze status API).

Jiné adresy než 0x76/0x77 konfigurace **odmítne**.

---

## Permission denied `/dev/i2c-1`

### Proveď

```bash
ls -l /dev/i2c-1
groups server-meter
id server-meter
```

### Očekávaný výsledek

`/dev/i2c-1` ve skupině `i2c`. Uživatel `server-meter` ve skupině `i2c`.

### Náprava

```bash
sudo groupadd --system i2c || true
sudo usermod -aG i2c server-meter
groups server-meter
sudo systemctl restart server-meter
```

`groups` v **aktuálním** SSH ukáže staré skupiny, dokud se znovu nepřihlásíte. Pro službu rozhoduje restart unit.

Unit má `SupplementaryGroups=i2c` a `DeviceAllow=/dev/i2c-1 rw`.

Test bez root:

```bash
sudo -u server-meter /usr/sbin/i2cdetect -y 1
```

(cesta k `i2cdetect` ověřte `command -v i2cdetect`.)

---

## BSEC nelze načíst

Bez knihovny běží T/p/RH/gas; IAQ/eCO2/bVOC jsou `null`. V logu jednorázový WARNING.

### Proveď

```bash
uname -m
ls -l /opt/server-meter/lib/libalgobsec.so
journalctl -u server-meter --no-pager -n 80 | grep -i bsec
```

`uname -m` musí být `aarch64`. 32bit `.so` na Pi 5 Ubuntu 64-bit **nesedí**.

Bosch složka: **PiFour_Armv8** / `aarch64-linux-gnu`. `sudo ./install.sh` oficiální ZIP stáhne samo. Když soubor chybí: `SERVER_METER_BSEC_REFRESH=1 sudo ./install.sh`.

Log `bsec_update_subscription failed: 14` je Bosch **varování** (nesoulad vzorkovací frekvence), ne chybějící knihovna. Aplikace ho bere jako úspěch. Postup: [BME690-BSEC.md](BME690-BSEC.md).

Když IAQ a eCO2 jsou čísla, ale bVOC je `null`: TVOC (id 31) nesmí shodit subscribe bVOC (id 4). V logu hledejte `BSEC subscribed outputs` a `breath_voc_equivalent`. Status −35 (`BSEC_E_CONFIG_FEATUREMISMATCH`) patří k TVOC/selectivity, ne k bVOC. Aplikace TVOC zahodí a bVOC ponechá.

YAML:

```yaml
sensor:
  bsec:
    enabled: true
    library_path: "/opt/server-meter/lib/libalgobsec.so"
    persist_state: false
```

`persist_state: true` start **zakáže**.

Knihovna se hledá i v `$SERVER_METER_BSEC_LIB`, `/usr/local/lib/libalgobsec.so`, `/usr/lib/libalgobsec.so`, `/opt/bosch/bsec/libalgobsec.so`.

> Wrapper volá `bsec_do_steps`, **nevolá** `bsec_sensor_control`. Pokud IAQ nesedí s oficiálním Bosch příkladem, toto je známé omezení kódu.

---

## Web se neotevře

### Proveď

```bash
systemctl status server-meter --no-pager
ss -lntp | grep 8080
curl -sS -D - http://127.0.0.1:8080/api/health
```

### Očekávaný výsledek

`Active: active (running)`, poslouchá `*:8080` nebo `0.0.0.0:8080`, health HTTP 200.

Z PC:

```bash
hostname -I
curl -sS http://RPI_IP:8080/api/health
```

### Pokud localhost funguje a LAN ne

UFW viz [SECURITY.md](SECURITY.md). `web.host` nesmí zůstat `127.0.0.1` (to je jen mock YAML).

Prohlížeč: `http://RPI_IP:8080/` — ne HTTPS, pokud nemáte proxy.

---

## HTTP 401

Špatné jméno nebo heslo, nebo chybí `-u`.

```bash
curl -sS -D - http://127.0.0.1:8080/api/current
```

Musí být `401` a `WWW-Authenticate: Basic realm="server-meter"`.

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/current
```

Heslo v YAML v uvozovkách, bez trailing mezery. Po změně YAML **restart** služby (config se čte jen při startu).

Dashboard po 401 ukáže přihlašovací formulář (CZ: „Nesprávné uživatelské jméno nebo heslo“). JSON API dál vrací `Authentication required` / `Invalid credentials`.

---

## Graf je po restartu prázdný

**Normální stav.**

```bash
sudo systemctl restart server-meter
```

Historie je RAM. Po několika intervalech (`interval_seconds`, výchozí 5) se křivky začnou kreslit. UI polluje current ~4 s a history ~5 s (`web/js/app.js`).

API:

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
```

`"source":"ram"`, `"persistent":false`.

---

## IAQ accuracy je po startu nízká

BSEC stav se **neukládá**. Po bootu accuracy 0 (`stabilizing`) nebo 1 (`low`) je očekávaná.

Počkejte desítky minut až hodiny s BSEC LP (vzorkování ~3 s, aplikace default interval 5 s). Nepřepínejte `persist_state`.

Bez `libalgobsec.so` je IAQ trvale `—` / `null`. To není low accuracy, to je chybějící algoritmus.

---

## Sensor unavailable

Web běží i bez senzoru. Karty ukazují `unavailable` / `—`.

### Diagnostika

1. `sudo i2cdetect -y 1`
2. adresa v YAML
3. `groups server-meter` obsahuje `i2c`
4. `journalctl -u server-meter -n 100 --no-pager`
5. `curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/sensor`

JSON: `"status":"unavailable"`, `last_error` text, HTTP 200.

Senzor se znovu otevírá s backoff (`retry_initial_seconds` → `retry_max_seconds`).

Forced heater 320 °C / 150 ms je v YAML; špatný breakout to nemění na „unavailable“ samo o sobě, ale I²C NACK ano.

---

## RAM usage vysoké

```bash
free -h
ps aux --sort=-%mem | head
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/status
```

Sledujte `memory.pressure` a `history.samples`. Při warning/critical/emergency se maže **nejstarší** historie, ne odkládá na SD. Viz [STORAGE-POLICY.md](STORAGE-POLICY.md).

Snižte `history.max_samples` a restartujte službu (nový limit platí po startu).

---

## systemd restart loop

```bash
systemctl status server-meter --no-pager
journalctl -u server-meter --no-pager -n 100
```

Časté příčiny:

| Log | Náprava |
|---|---|
| password too short / empty | YAML `web.auth.password` (min. 8 znaků) |
| `Configuration file not found` / `No configuration file found` | soubor může existovat; `/etc/server-meter` musí být **0750** `root:server-meter` |
| `Configuration directory not accessible` | `sudo chown root:server-meter /etc/server-meter && sudo chmod 0750 /etc/server-meter` |
| `Configuration file not readable` | `sudo chmod 660 /etc/server-meter/config.yaml && sudo chown root:server-meter /etc/server-meter/config.yaml` |
| `Address already in use` | cizí proces na 8080 |
| `Failed to start` limit burst | `sudo systemctl reset-failed server-meter` po opravě |

Když journal říká `Configuration file not found: /etc/server-meter/config.yaml`, ale `sudo cat` ten soubor ukáže, jde o **práva adresáře**, ne o chybějící YAML. `Path.is_file()` bez práva `+x` na rodiči vrátí false.

```bash
stat -c '%a %U %G %n' /etc/server-meter /etc/server-meter/config.yaml
sudo chown root:server-meter /etc/server-meter
sudo chmod 0750 /etc/server-meter
sudo chmod 660 /etc/server-meter/config.yaml
sudo chown root:server-meter /etc/server-meter/config.yaml
sudo systemctl reset-failed server-meter
sudo systemctl start server-meter
```

Ruční start (vidíte stderr):

```bash
sudo systemctl stop server-meter
sudo -u server-meter /opt/server-meter/venv/bin/python -m server_meter --config /etc/server-meter/config.yaml
```

---

## Port already in use

```bash
ss -lntp | grep 8080
```

Uvidíte PID. Pokud je to ruční python, ukončete ho. Pokud jiná služba, změňte `web.port` v YAML **a** případně unit nespouští jiný port — unit port neobsahuje, čte se z YAML.

Po změně portu:

```bash
sudo systemctl restart server-meter
ss -lntp | grep NOVELY_PORT
```

---

## Mock režim (diagnostika bez hardware)

Když chcete oddělit „I²C vs aplikace“:

```bash
sudo systemctl stop server-meter
sudo -u server-meter /opt/server-meter/venv/bin/python -m server_meter \
  --config /opt/server-meter/config/config.mock.yaml
```

Mock YAML: `driver: mock`, heslo `devpass1`, `host: 127.0.0.1`, `environment: development`.

```bash
curl -u admin:devpass1 http://127.0.0.1:8080/api/current
```

Musí být `available: true` a syntetické hodnoty. Dashboard: `http://127.0.0.1:8080/`.

Návrat: Ctrl+C, YAML produkce `driver: bme690`, `sudo systemctl start server-meter`.

Nespouštějte mock unit souběžně s produkcí na stejném portu.

---

## Testy pytest

```bash
cd /opt/server-meter
sudo -u server-meter /opt/server-meter/venv/bin/pip install -r /opt/server-meter/requirements-dev.txt
sudo -u server-meter /opt/server-meter/venv/bin/python -m pytest
```

Testy používají mock, fyzický BME690 nepotřebují. `install.sh` **neinstaluje** `requirements-dev.txt`.

---

## Kompletní diagnostický checklist

Spouštějte **postupně** na Raspberry Pi:

```bash
uname -a
uname -m
cat /etc/os-release
python3 --version
hostnamectl
timedatectl
ls -l /dev/i2c*
sudo i2cdetect -y 1
id server-meter
groups server-meter
stat -c '%a %U %G' /etc/server-meter /etc/server-meter/config.yaml
sudo -u server-meter test -r /etc/server-meter/config.yaml && echo readable
ls -l /opt/server-meter/venv/bin/python
ls -l /opt/server-meter/lib/libalgobsec.so
free -h
ps aux --sort=-%mem | head
systemctl is-enabled server-meter
systemctl is-active server-meter
systemctl status server-meter --no-pager
journalctl -u server-meter --no-pager -n 100
ss -lntp | grep 8080
curl -sS -D - http://127.0.0.1:8080/api/health
curl -sS -D - -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/current
curl -sS -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/sensor
curl -sS -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
curl -sS -D - -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/nagios/check
sudo iotop -o -p "$(systemctl show -p MainPID --value server-meter)"
```

`YOUR_PASSWORD` dosadíte. `iotop` nainstalujte podle [STORAGE-POLICY.md](STORAGE-POLICY.md).

Architektura musí být `aarch64`. Health bez hesla (výchozí). Current bez `-u` musí dát 401.
