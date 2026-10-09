# systemd služba server-meter

Jednotka v gitu: `systemd/server-meter.service`.

`install.sh` ji zkopíruje na:

```text
/etc/systemd/system/server-meter.service
```

a provede `systemctl daemon-reload` + `systemctl enable`. **Nespouští** `start`.

Administrátorské restartovací akce používají dvě oneshot helper jednotky, které se **neenableují** po bootu:

```text
/etc/systemd/system/server-meter-self-restart.service
/etc/systemd/system/server-meter-host-reboot.service
/etc/polkit-1/rules.d/50-server-meter.rules
```

Aplikace (uživatel `server-meter`, `NoNewPrivileges=true`) spouští jen `systemctl start` těchto dvou jednotek. Polkit nepovoluje žádný jiný unit ani obecný shell.

---

## Co unit skutečně obsahuje

| Položka | Hodnota |
|---|---|
| `User` / `Group` | `server-meter` |
| `SupplementaryGroups` | `i2c` |
| `WorkingDirectory` | `/opt/server-meter` |
| `ExecStart` | `/opt/server-meter/venv/bin/python -m server_meter --config /etc/server-meter/config.yaml` |
| `Restart` | `always` (5 s) |
| `StandardOutput` / `StandardError` | `journal` |
| `SyslogIdentifier` | `server-meter` |
| `PrivateTmp` | `true` (privátní tmpfs, ne SD) |
| `ProtectSystem` | `strict` |
| `ReadOnlyPaths` | `/opt/server-meter` `/etc/server-meter` |
| Config dir | `/etc/server-meter` mode **0750** `root:server-meter` (uživatel služby musí umět adresář projít; 640 jen na YAML nestačí) |
| `ReadWritePaths` | prázdné |
| `DeviceAllow` | `/dev/i2c-0`, `/dev/i2c-1`, `/dev/i2c-2` rw |

**Není** nastaveno `RuntimeDirectory=`. Aplikace za běhu **nevytváří** soubory v `/run/server-meter` ani v `/opt/server-meter`. Historie je jen v RAM procesu.

`MemoryDenyWriteExecute=false` — ctypes načítá `libalgobsec.so`.

---

## Instalace jednotky (pokud jste nepoužili install.sh)

### 1. Proveď

```bash
sudo install -m 0644 /opt/server-meter/systemd/server-meter.service \
  /etc/systemd/system/server-meter.service
sudo systemctl daemon-reload
sudo systemctl enable server-meter
sudo systemctl start server-meter
```

### 2. Ověř

```bash
systemctl status server-meter --no-pager
```

### Očekávaný výsledek

Řádek:

```text
Active: active (running)
```

a

```text
Loaded: loaded (/etc/systemd/system/server-meter.service; enabled; ...
```

`enabled` = start po bootu.

---

## Běžné příkazy

Start:

```bash
sudo systemctl start server-meter
```

Stop:

```bash
sudo systemctl stop server-meter
```

Restart (vyprázdní RAM historii):

```bash
sudo systemctl restart server-meter
```

Status:

```bash
systemctl status server-meter --no-pager
```

Povolit po bootu:

```bash
sudo systemctl enable server-meter
```

Zakázat po bootu (služba může dál běžet, dokud ji nestopnete):

```bash
sudo systemctl disable server-meter
```

Stop + disable:

```bash
sudo systemctl disable --now server-meter
```

---

## Test po rebootu

```bash
sudo reboot
```

Po SSH:

```bash
systemctl is-enabled server-meter
systemctl is-active server-meter
systemctl status server-meter --no-pager
curl http://127.0.0.1:8080/api/health
```

Očekávané:

```text
enabled
active
```

a health JSON `{"status":"healthy","service":"server-meter"}`.

Historie:

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
```

`"persistent": false`. Grafy začínají prázdné — **není to chyba**.

---

## Logy (journald)

Aplikace **nevytváří** soubor `/var/log/server-meter.log` ani rotované `*.log` s měřeními.

Čtení:

```bash
journalctl -u server-meter --no-pager -n 100
```

Sledování:

```bash
journalctl -u server-meter -f
```

Od posledního bootu:

```bash
journalctl -u server-meter -b --no-pager
```

Úroveň v YAML (`logging.level`) jde na stderr → journal. `logging.access_log: false` (výchozí) vypíná uvicorn access log, aby se journal neplnil každým requestem.

Jednotlivá měření T/p/RH se **nelogují**.

---

## Volatile journald

**Proč:** Ubuntu ve výchozím stavu může journal ukládat na SD (`/var/log/journal`). Cílem server-meter je SD kartu šetřit.

Šablona v gitu: `docs/journald-volatile.conf`.

### 1. Proveď

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp /opt/server-meter/docs/journald-volatile.conf \
  /etc/systemd/journald.conf.d/server-meter-volatile.conf
sudo systemctl restart systemd-journald
```

Obsah souboru:

```ini
[Journal]
Storage=volatile
RuntimeMaxUse=32M
RuntimeMaxFileSize=8M
Compress=yes
```

### 2. Ověř

```bash
systemd-analyze cat-config systemd/journald.conf | grep -A6 '\[Journal\]'
ls -d /run/log/journal
```

`Storage=volatile` musí být vidět. Runtime logy jsou na tmpfs `/run/log/journal`.

### Důsledek

> Po rebootu budou journal logy ztraceny.

Pro tento projekt je to přijatelné. Diagnostiku dělejte za běhu (`journalctl -f`), ne po výpadku napájení.

Starý adresář `/var/log/journal` může zůstat z dřívějška. Nové záznamy tam journald s `Storage=volatile` **nepíše**. Volitelně po ověření můžete starý strom smazat (to **není** součást aplikace; jde o data OS).

---

## tmpfs a runtime data

| Cesta | Použití server-meter |
|---|---|
| `/opt/server-meter` | kód + venv, **read-only** pro proces (`ProtectSystem=strict`) |
| `/etc/server-meter` | mode **0750** `root:server-meter` — proces musí adresář projít |
| `/etc/server-meter/config.yaml` | čtení při startu (640 `root:server-meter`), nikdy zápis zpět |
| `/tmp` procesu | `PrivateTmp=true` (RAM), aplikace ho k měřením nepoužívá |
| `/run/server-meter` | **neexistuje** — unit ho nevytváří |

Nevytvářejte runtime soubory v `/opt/server-meter`. Pokud byste unit upravili a přidali zápis historie, porušíte storage policy.

---

## Restart loop

`StartLimitIntervalSec=120`, `StartLimitBurst=10`, `Restart=on-failure`, `RestartSec=3`.

Když YAML obsahuje prázdné nebo příliš krátké heslo, proces končí kódem **2**. Stejný kód 2 dává i `Configuration file not found`, když `/etc/server-meter` není 0750 `root:server-meter` (uživatel služby adresář neprojde, i když YAML existuje). Systemd ho restartuje, až narazí na limit → `failed`. Tovární `CHANGE_ME` (9 znaků) start **povolí**.

### Ověř

```bash
systemctl status server-meter --no-pager
journalctl -u server-meter --no-pager -n 50
```

Hledejte `server-meter configuration error`.

Opravte YAML, pak:

```bash
sudo systemctl reset-failed server-meter
sudo systemctl start server-meter
```

---

## Port already in use

Pokud ruční `python -m server_meter` ještě běží, systemd start selže (`OSError` / address already in use).

```bash
ss -lntp | grep 8080
```

Ukončete ruční proces (`Ctrl+C`) nebo cizí službu na 8080, pak `sudo systemctl start server-meter`.
