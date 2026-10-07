# Politika úložiště (RAM-only)

server-meter je navržený tak, aby **naměřená data BME690 nikdy neputovala na microSD**.

Kingston Industrial 16 GB vydrží déle, když na ni 24/7 nesypete JSON/CSV/SQLite historii.

> Šipka z RAM na SD kartu záměrně neexistuje.

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

Test v CI: `tests/test_disk_policy.py` (`sqlite3` jen pro účty v `users.py`, žádný `FileHandler`, žádné volání `bsec_get_state(`).

---

## SD karta — povoleno

Statické, spravované operátorem. Aplikace to za běhu **nepřepisuje**:

| Položka | Typická cesta |
|---|---|
| OS Ubuntu | partition na microSD |
| Zdrojový kód server-meter | `/opt/server-meter/server_meter/` |
| Statický frontend | `/opt/server-meter/web/` |
| Python venv | `/opt/server-meter/venv/` |
| YAML konfigurace (včetně SMTP) | `/etc/server-meter/config.yaml` |
| SQLite uživatelské účty | `/var/lib/server-meter/users.db` (ne historie měření) |
| systemd unit | `/etc/systemd/system/server-meter.service` |
| BSEC `.so` (volitelně) | `/opt/server-meter/lib/libalgobsec.so` |
| Dokumentace | `/opt/server-meter/docs/` |

Zápis na SD probíhá při **instalaci / upgradu / uložení Settings (SMTP/prahy)**, ne při každém vzorku. Stav alarmu a historie měření zůstávají v RAM.

---

## RAM — povinné

| Data | Kde v procesu | Po rebootu |
|---|---|---|
| aktuální vzorek | `MeterService.current` | znovu ze senzoru |
| historie / grafy | `RamBuffer` (`collections.deque`) | **prázdné** |
| BSEC algoritmický stav | ctypes instance v `BsecProcessor` | **nová inicializace** |
| statistiky smyčky | `RuntimeStats` | vynulované |
| memory pressure | `MemoryProtector` | vynulované |
| CPU usage delta | `SystemMonitor._prev_cpu` | vynulované |
| stav alarmu / e-mailová fronta | `NotificationEngine` | vynulované |

BSEC `persist_state: true` konfigurace **odmítne** (`ConfigError`). Wrapper **nevolá** `bsec_get_state`.

Po restartu může chvíli trvat, než BSEC dosáhne vyšší IAQ accuracy. To je důsledek RAM-only stavu, ne chyba SD karty.

---

## Zakázáno (aplikace to nedělá)

- SQLite / jiná databáze měření (`users.db` drží jen účty, ne vzorky)
- CSV / JSON soubor historie
- pickle / shelve
- periodický export měření na disk
- `FileHandler` log měření
- persistace BSEC kalibrace
- InfluxDB, Redis, Prometheus client v runtime závislostech

`requirements.txt` obsahuje FastAPI, Uvicorn, Pydantic, PyYAML, smbus2 a argon2-cffi (hashe hesel). `sqlite3` je ve stdlib a používá se jen pro tabulku `users`.

---

## Ochrana RAM

Kód: `server_meter/storage/ram_buffer.py`, `server_meter/monitoring/memory.py`.

### Limity historie

| YAML | Význam | Výchozí |
|---|---|---|
| `history.max_samples` | kapacita deque | 10000 |
| `history.max_age_seconds` | starší vzorky se maže | 86400 (24 h) |
| `history.min_samples_keep` | spodní mez při trimu | 64 |
| tvrdý strop v kódu | `HISTORY_HARD_MAX_SAMPLES` | **20000** |

Přetečení `max_samples`: deque zahodí **nejstarší** vzorek. Nikam se neukládá.

Přetečení stáří: `popleft()` dokud je nejstarší pod cutoff; alespoň 1 vzorek zůstane.

### Memory protection

Sleduje se **systémové** `ram_usage_percent` (MemTotal/MemAvailable), ne jen RSS procesu.

| Stupeň | Výchozí práh | Co se smaže |
|---|---|---|
| normal | pod 70 % | nic |
| warning | ≥ 70 % | 10 % vzorků (`warning_trim_fraction`) |
| critical | ≥ 80 % | 25 % |
| emergency | ≥ 90 % | 50 % |

Algoritmus:

```text
oldest samples
      ↓
REMOVE  (trim_fraction, ale ne pod min_samples_keep)
      ↓
newest samples remain
```

Nikdy:

```text
RAM → SD card
```

Kontrola probíhá každých `check_interval_seconds` (výchozí 15, minimum 5). Při critical/emergency se trim spustí i mimo interval.

Log (journal, ne soubor): `memory pressure=… trimmed_oldest=…` nejvýše jednou za 30 s.

---

## Kontrola RAM

Na Pi:

```bash
free -h
```

Očekávejte, že volná RAM klesá s počtem vzorků, ale **SSD/SD usage** kvůli historii neroste.

Největší procesy:

```bash
ps aux --sort=-%mem | head
```

Hledejte `python -m server_meter`. RSS desítky MB je běžné; stovky MB při 10k vzorcích stále bez zápisu historie na disk.

Z API:

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/status
```

Pole `memory.pressure`, `history.samples`, `history.dropped_oldest`, `history.trim_events`.

---

## Kontrola I/O na SD kartě

**Cíl:** ověřit, že proces server-meter **pravidelně nezapisuje měření**.

Systém (apt, kernel, filesystem journaling) **může** na SD zapisovat z jiných důvodů. To není důkaz, že server-meter ukládá historii.

### 1. Nainstalujte iotop

```bash
sudo apt update
sudo apt install -y iotop
```

### 2. Proveď

PID služby:

```bash
systemctl show -p MainPID --value server-meter
```

Sledování (potřebuje root):

```bash
sudo iotop -o -p "$(systemctl show -p MainPID --value server-meter)"
```

`-o` = jen procesy s I/O. Nechte běžet minutu, mezitím obnovte dashboard.

### Očekávaný výsledek

Řádek python procesu **nemá** setrvalý DISK WRITE odpovídající intervalu měření (5 s). Občasný šum kernelu je možný; proud megabajtů/s není.

Širší pohled (všechny zapisující procesy):

```bash
sudo iotop -o
```

### Doplňkově: otevřené soubory procesu

```bash
PID=$(systemctl show -p MainPID --value server-meter)
sudo ls -l /proc/$PID/fd | grep -v 'socket:\|anon_inode:\|pipe:'
```

Neměli byste vidět něco jako `/var/lib/server-meter/history.sqlite` — takový soubor projekt **nemá**.

`ProtectSystem=strict` a prázdné `ReadWritePaths` procesu brání zápisu do `/opt` a `/etc`.

### volitelně sysstat

```bash
sudo apt install -y sysstat
pidstat -d -p "$(systemctl show -p MainPID --value server-meter)" 5 6
```

Sloupec kB_wr/s u pythonu by měl zůstat na nule nebo blízko nule.

---

## Swap na SD

Swap partition/file na microSD je zesilovač zápisu. Není součástí server-meter.

Zkontrolujte:

```bash
swapon --show
free -h
```

Pokud je swap na SD a chcete ho vypnout, pochopte riziko OOM na 4 GB Pi. `zram` je šetrnější než swap na kartě. Tento projekt zram **nespravuje**.

---

## journald

I když aplikace neměří do souboru, persistentní journald zapisuje na SD. Viz [SYSTEMD.md](SYSTEMD.md) sekce **Volatile journald**.

---

## Potvrzení po restartu

```bash
sudo systemctl restart server-meter
sleep 2
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
```

`count` je 0 nebo jen nové vzorky. `"source":"ram"`, `"persistent":false`.

To je důkaz, že historie nebyla na kartě.
