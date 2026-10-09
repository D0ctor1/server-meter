# Instalace server-meter od čistého Ubuntu

**Běžný postup je jeden příkaz.** Po zapojení BME690 (Pi vypnuté, viz [HARDWARE.md](HARDWARE.md)):

```bash
git clone https://github.com/D0ctor1/server-meter.git
cd server-meter
sudo ./install.sh
```

Skript nainstaluje závislosti, zapne I²C, najde BME690 (chip ID `0x61` na `0x76`/`0x77`), vytvoří uživatele, venv, YAML, systemd, volatile journald a spustí službu. Heslo v YAML **nesmaže** při opakovaném spuštění. Adresář `/opt/server-meter/lib` (BSEC) a existující `venv` se při `rsync` nemažou. Přihlášení bere SQLite `/var/lib/server-meter/users.db`; YAML `web.auth.password` je jen semínko prvního administrátora. Reinstalace existující účty nepřepisuje. Instalační test `/api/current` použije YAML heslo jen tehdy, když se stále shoduje se SQLite; jinak ověří `/api/health` a že chráněné API vrací 401.

Jediný ruční zásah po úspěchu: přihlásit se jako admin (YAML heslo se jednou migrujte do SQLite) a změnit heslo v Nastavení → Uživatelé. YAML se při upgradu nepřepisuje.

Níže je referenční popis toho, co instalátor dělá, plus Ubuntu z Imageru.

Tento návod předpokládá **Raspberry Pi 5 (4 GB)**, **Kingston Industrial 16 GB microSD** a **Ubuntu Server 26.04.1 LTS 64-bit (ARM64)**.

Cíl: po `install.sh` otevřete v prohlížeči `http://RPI_IP:8080/` a uvidíte dashboard.

`RPI_IP` je příklad — vždy použijte výstup `hostname -I`.

Než začnete se softwarem, zapojte BME690 podle [HARDWARE.md](HARDWARE.md) (**Pi je vypnuté**).

---

## Co budete potřebovat

- Raspberry Pi 5, oficiální (nebo kvalitní) USB-C zdroj
- microSD 16 GB, čtečka
- počítač s [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
- síť (Ethernet je nejjednodušší)
- účet, který umí `sudo`

---

## 1. Instalace Ubuntu Server 26.04.1

### 1.1 Zápis obrazu

**Co:** Na SD kartu nahrajete ARM64 obraz Ubuntu Server pro Raspberry Pi.

**Proč:** server-meter je určený pro Ubuntu Server 26.04.1, ne pro Raspberry Pi OS.

V Raspberry Pi Imager:

1. Device: **Raspberry Pi 5**
2. OS: **Ubuntu Server 26.04.1 LTS (64-bit)** — varianta **arm64+raspi** / preinstalled server
3. Storage: Kingston 16 GB
4. V nastavení (ozubené kolo) doporučujeme:
   - hostname: `server-meter`
   - uživatel a heslo (zapamatujte si je)
   - SSH: povolit (heslo nebo klíč)
   - Wi-Fi jen pokud nemáte Ethernet
5. Write → vyjměte kartu → vložte do Pi

> ⚠️ **VYŽADUJE OVĚŘENÍ:** Přesný název položky v Imageru se může lišit (`Ubuntu Server 26.04.1` vs. `26.04 LTS`). Vyberte 64-bit server obraz pro Raspberry Pi, ne desktop.

### 1.2 První start

Zapojte Ethernet, USB-C napájení, **nechte Pi naběhnout 1–3 minuty**.

Z jiného počítače:

```bash
ssh VASE_JMENO@server-meter.local
```

Pokud `.local` nefunguje, zjistěte IP v routeru a použijte:

```bash
ssh VASE_JMENO@RPI_IP
```

`VASE_JMENO` je uživatel z Imageru. Při prvním přihlášení může Ubuntu chtít změnu hesla.

### 1.3 Ověření architektury

```bash
uname -a
uname -m
```

**Očekávaný výsledek:** `aarch64` (ne `armv7l`).

```bash
cat /etc/os-release
```

Měli byste vidět Ubuntu 26.04 (Resolute).

```bash
python3 --version
```

Na Ubuntu 26.04 je výchozí `python3` řady **3.14** (balíček `python3` závisí na `python3.14`). Projekt vyžaduje Python **≥ 3.11** (`pyproject.toml`).

---

## 2. Aktualizace systému

**Proč:** bezpečnostní záplaty a aktuální jádro pro Pi 5.

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

Po rebootu se znovu přihlaste SSH a zopakujte:

```bash
uname -m
```

Stále `aarch64`.

---

## 3. Hostname

Doporučený hostname: `server-meter`.

### Proveď

```bash
sudo hostnamectl set-hostname server-meter
```

Upravte `/etc/hosts`, aby lokální jméno ukazovalo na loopback Pi (typický řádek `127.0.1.1`):

```bash
hostname
```

Pokud `hostname` ještě není `server-meter`, zkontrolujte:

```bash
hostnamectl
```

Do `/etc/hosts` přidejte nebo upravte (jako root):

```text
127.0.1.1    server-meter
```

Příklad editoru:

```bash
sudo nano /etc/hosts
```

Uložte (Ctrl+O, Enter, Ctrl+X v nano).

### Ověř

```bash
hostnamectl
```

**Očekávaný výsledek:** `Static hostname: server-meter`.

---

## 4. Čas a časové pásmo

Aplikace ukládá timestampy interně jako **UTC epoch** (`time.time()` v `server_meter/service.py`). Webový frontend zobrazuje **lokální čas prohlížeče**.

### Proveď

```bash
timedatectl
```

Pro české prostředí:

```bash
sudo timedatectl set-timezone Europe/Prague
```

Zapněte NTP, pokud není aktivní:

```bash
sudo timedatectl set-ntp true
```

### Ověř

```bash
timedatectl
```

**Očekávaný výsledek:** `Time zone: Europe/Prague (...)` a `System clock synchronized: yes` (nebo NTP aktivní).

---

## 5. Aktivace I²C (Ubuntu Server na Pi 5)

**Proč:** BME690 visí na I2C1 (SDA PIN 3, SCL PIN 5). Bez `/dev/i2c-1` driver nefunguje.

Na Ubuntu **není** spolehlivé spoléhat na `raspi-config` (na Ubuntu Server často vůbec není). Oficiální Ubuntu dokumentace používá `/boot/firmware/config.txt`.

### 5.1 Balíčky

```bash
sudo apt install -y i2c-tools python3 python3-venv python3-dev python3-pip build-essential git
```

### Ověř

```bash
dpkg -l i2c-tools python3 | awk '/^ii/'
which i2cdetect
```

### 5.2 Device-tree parametr

```bash
ls -l /boot/firmware/config.txt /boot/config.txt 2>/dev/null
```

Na Ubuntu pro Raspberry Pi má existovat **`/boot/firmware/config.txt`**.

Zkontrolujte, zda už I²C není zapnuté (na některých Ubuntu obrazech **už je** `dtparam=i2c_arm=on`):

```bash
grep -n 'i2c' /boot/firmware/config.txt
```

Pokud řádek **`dtparam=i2c_arm=on`** chybí nebo je zakomentovaný (`#`), přidejte ho. Skript v projektu to umí:

```bash
# až budete mít naklonovaný kód, lze použít:
# sudo /opt/server-meter/scripts/enable_i2c.sh
```

Teď, ještě před klonováním, ručně:

```bash
sudo nano /boot/firmware/config.txt
```

Do souboru (sekce `[all]`, **před** další `dtoverlay=` podle Ubuntu docs) přidejte:

```text
dtparam=i2c_arm=on
```

Uložte.

Načtěte modul `i2c-dev` teď a po každém bootu:

```bash
echo 'i2c-dev' | sudo tee /etc/modules-load.d/server-meter-i2c.conf
sudo modprobe i2c-dev
```

### 5.3 Reboot po změně config.txt

```bash
sudo reboot
```

Znovu SSH.

### 5.4 Ověření zařízení

```bash
ls -l /dev/i2c*
```

**Očekávaný výsledek** na Pi 5: minimálně `/dev/i2c-1` (mohou existovat i další sběrnice HDMI DDC — ty nepoužívejte).

```bash
i2cdetect -l
```

Hledejte bus **1**.

Pokud `/dev/i2c-1` chybí:

```
Error: Could not open file `/dev/i2c-1`: No such file or directory
```

→ znovu zkontrolujte `dtparam=i2c_arm=on`, reboot, `modprobe i2c-dev`. Další kroky: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

> ⚠️ **VYŽADUJE OVĚŘENÍ na konkrétním obrazu 26.04.1:** starší Ubuntu na Pi občas četlo overlay z `/boot/firmware/usercfg.txt` místo `config.txt`. Pokud po rebootu `/dev/i2c-1` není a `config.txt` je v pořádku, zkontrolujte `ls /boot/firmware/*.txt` a zda `config.txt` obsahuje `include` na `usercfg.txt`.

---

## 6. Detekce BME690

**Předpoklad:** zapojení podle [HARDWARE.md](HARDWARE.md) je hotové a Pi už znovu běží.

```bash
sudo i2cdetect -y 1
```

### Očekávaný výsledek (příklad 0x76)

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

`76` = zařízení na adrese **0x76**.  
Pokud uvidíte `77`, adresa je **0x77**.

Tuto adresu zapíšete do YAML jako `sensor.i2c.address`.

Pokud je tabulka samé `--`:

1. `sudo poweroff`, odpojte USB-C
2. zkontrolujte 3.3 V (PIN 1), GND (PIN 6), SDA (PIN 3), SCL (PIN 5)
3. zkontrolujte STEMMA západku
4. znovu zapněte a `sudo i2cdetect -y 1`

---

## 7. Získání zdrojového kódu

```bash
cd ~
sudo apt install -y git
git clone https://github.com/D0ctor1/server-meter.git
cd server-meter
```

Výchozí větev po sloučení PR je `main`. Pokud `docs/INSTALLATION.md` v klonu ještě není česky / chybí soubory z této dokumentace:

```bash
git fetch origin
git checkout cursor/server-meter-0002
```

> ⚠️ **VYŽADUJE OVĚŘENÍ:** URL forku a název výchozí větve zkontrolujte na GitHubu. Nepoužívejte náhodný `curl | sudo bash`.

### Ověř

```bash
ls scripts/install.sh systemd/server-meter.service config/config.example.yaml server_meter/__main__.py
```

Všechny tyto soubory musí existovat.

---

## 8. Instalační skript (uživatel, venv, systemd unit)

Hlavní vstup je kořenový **`./install.sh`** (wrapper `scripts/install.sh` ho jen spustí). Skript **skutečně** dělá toto:

- nainstaluje `python3`, `python3-venv`, `python3-dev`, `python3-pip`, `build-essential`, `i2c-tools`, `adduser`
- vytvoří systémového uživatele `server-meter`
- přidá ho do skupiny `i2c`, **pokud skupina už existuje**
- zkopíruje strom do `/opt/server-meter`
- vytvoří venv **`/opt/server-meter/venv`** (ne `.venv`)
- `pip install -r /opt/server-meter/requirements.txt`
- stáhne oficiální Bosch BSEC 3.2+ ZIP, z `PiFour_Armv8/libalgobsec.a` sestaví `/opt/server-meter/lib/libalgobsec.so` (rsync knihovnu nemaže)
- pokud chybí `/etc/server-meter/config.yaml`, zkopíruje example (heslo `CHANGE_ME`)
- `chmod 0750` a `chown root:server-meter` na `/etc/server-meter` (uživatel služby musí adresář projít)
- `chmod 660` a `chown root:server-meter` na YAML (služba musí umět uložit SMTP z webu)
- ověří `test -r` jako uživatel `server-meter`
- nainstaluje unit do `/etc/systemd/system/server-meter.service`
- nainstaluje helper units `server-meter-self-restart.service` a `server-meter-host-reboot.service` (nespínají se po bootu)
- nainstaluje polkit pravidlo `/etc/polkit-1/rules.d/50-server-meter.rules` (jen `systemctl start` těchto dvou jednotek)
- `systemctl daemon-reload`, `systemctl enable` a `systemctl start`

### Proveď

```bash
cd ~/server-meter
sudo ./scripts/install.sh
```

Skript musí běžet jako root (`sudo`).

### Ověř uživatele a skupiny

```bash
id server-meter
groups server-meter
ls -l /opt/server-meter/venv/bin/python
ls -ld /etc/server-meter
ls -l /etc/server-meter/config.yaml
systemctl is-enabled server-meter
```

**Očekávaný výsledek:**

- uživatel `server-meter` existuje, shell `/usr/sbin/nologin`
- v `groups` je ideálně `i2c` (pokud ne, viz krok 8.1)
- adresář je `drwxr-x--- root server-meter` (0750)
- YAML je `-rw-r----- root server-meter`
- služba je `enabled`

### 8.1 Skupina i2c, pokud chybí

`install.sh` má `usermod -aG i2c || true`. Pokud `i2c` ještě neexistovala, uživatel ve skupině **není**.

```bash
getent group i2c
```

Pokud skupina chybí:

```bash
sudo ./scripts/enable_i2c.sh
sudo usermod -aG i2c server-meter
groups server-meter
```

`enable_i2c.sh` zapne `dtparam=i2c_arm=on` (pokud chybí), `i2c-dev`, vytvoří skupinu `i2c`. Po změně `config.txt` je potřeba reboot.

---

## 9. Bosch BSEC (IAQ)

`install.sh` krok 6 stáhne oficiální Bosch ZIP a nainstaluje ARM64 knihovnu. Bez ní **web i API běží**, ale `iaq`, `eco2` a `bvoc` budou `null`.

Kompletní licence, URL a ruční nouzový postup: **[BME690-BSEC.md](BME690-BSEC.md)**.

---

## 10. YAML — heslo a I²C adresa (povinné před startem)

```bash
sudo nano /etc/server-meter/config.yaml
```

Změňte minimálně:

```yaml
application:
  environment: production

web:
  auth:
    username: "admin"
    password: "YOUR_PASSWORD"

sensor:
  driver: "bme690"
  i2c:
    bus: 1
    address: 0x76    # nebo 0x77 podle i2cdetect
  interval_seconds: 5
  bsec:
    enabled: true
    library_path: "/opt/server-meter/lib/libalgobsec.so"
    persist_state: false
```

`YOUR_PASSWORD` musí mít v production **alespoň 8 znaků**. Tovární `CHANGE_ME` službu spustí; změňte ho a restartujte unit.

Adresu I²C nastaví `install.sh` podle chip ID. Ruční přepis je potřeba jen když senzor vyměníte.

Kompletní vysvětlení klíčů: [CONFIGURATION.md](CONFIGURATION.md).

### Ověř práva

```bash
stat -c '%a %U %G' /etc/server-meter /etc/server-meter/config.yaml
sudo -u server-meter test -r /etc/server-meter/config.yaml && echo readable
```

**Očekávaný výsledek:** `750 root server-meter`, `640 root server-meter` a `readable`.

(Skript nastavuje 0750 na adresáři a 640 na YAML, ne 600, aby uživatel služby ve skupině `server-meter` soubor přečetl. 640 jen na souboru nestačí, pokud adresář zůstane `root:root`.)

---

## 11. První manuální start (ještě bez systemd)

**Proč:** uvidíte chybu konfigurace nebo I²C dřív, než vás systemd začne restartovat ve smyčce.

Otevřete **druhé** SSH jen pokud chcete; stačí jeden terminál.

```bash
sudo -u server-meter /opt/server-meter/venv/bin/python -m server_meter --config /etc/server-meter/config.yaml
```

### Očekávaný výstup (úspěch)

Na stderr (systemd by to bral jako journal):

```text
INFO server_meter starting server-meter env=production driver=bme690 listen=0.0.0.0:8080 (history is RAM-only)
INFO server_meter.service measurement loop starting driver=bme690 interval=5.0s history_max=2000000 history_max_age=10000000s auto=True
INFO server_meter.bme690 BME690 detected chip_id=0x61 ...
INFO uvicorn.error Application startup complete.
INFO uvicorn.error Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

Pokud BSEC chybí, uvidíte **jednou** WARNING o chybějící knihovně a fyzické hodnoty dál běží.

Pokud senzor není na I²C:

```text
ERROR server_meter.service sensor unavailable at startup: ... (web UI will still run)
```

Web **musí** i tehdy naslouchat na 8080.

### Pokud start selže na hesle

Prázdné nebo kratší než 8 znaků:

```text
server-meter configuration error: ...
```

Tovární `CHANGE_ME` je platné. Po změně hesla: `sudo systemctl restart server-meter`.

Ukončení ručního běhu: `Ctrl+C`. Nic se na disk nezapíše.

---

## 12. Test z Raspberry Pi (localhost)

V **druhém** SSH (nechte aplikaci běžet), nebo až poběží systemd:

Health je ve výchozím YAML **veřejný** (`web.health_public: true`):

```bash
curl http://127.0.0.1:8080/api/health
```

**Očekávaný výsledek:**

```json
{"status":"healthy","service":"server-meter"}
```

Aktuální měření (Basic Auth):

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/current
```

Bez hesla:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/current
```

**Očekávaný výsledek:** `401`.

HTML UI (veřejné, login formulář; data jsou za `/api/*`):

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/
```

**Očekávaný výsledek:** `200`.

---

## 13. IP adresa a přístup z PC

```bash
hostname -I
```

Příklad výstupu:

```text
192.168.1.50
```

`192.168.1.50` je **příklad**. Použijte svou adresu.

V prohlížeči na jiném počítači ve stejné LAN:

```text
http://192.168.1.50:8080/
```

Prohlížeč otevře lokalizovaný přihlašovací formulář (uživatel `admin`, heslo z YAML). Jazyk webu je `web.locale` (`CZ` výchozí).

Pokud se stránka nenačte, zkontrolujte firewall: [SECURITY.md](SECURITY.md) a [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Firewall (UFW) — jen pokud je aktivní

```bash
sudo ufw status
```

Když je `Status: active`, neotevírejte 8080 do celého internetu. Příklad omezení na LAN (`192.168.1.0/24` je **příklad**, použijte svou síť):

```bash
sudo ufw allow from 192.168.1.0/24 to any port 8080 proto tcp comment 'server-meter lan'
sudo ufw status numbered
```

Přesný postup a pravidlo jen pro IP Nagios serveru: [SECURITY.md](SECURITY.md).

---

## 14. Systemd (trvalý běh)

Ukončete ruční proces (`Ctrl+C`), pokud ještě běží.

```bash
sudo systemctl start server-meter
systemctl status server-meter --no-pager
```

**Očekávaný výsledek:** `Active: active (running)`.

```bash
sudo systemctl enable server-meter
```

(`install.sh` už `enable` volá; zopakování nevadí.)

Logy:

```bash
journalctl -u server-meter -e --no-pager
```

Aplikace **nevytváří** soubory `*.log`. Měření nejdou do journalu po jednom vzorku.

### Volatile journald (ochrana SD karty)

**Proč:** Ubuntu může journal ukládat na microSD. Pro tento projekt je přijatelné mít logy jen v RAM.

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp /opt/server-meter/docs/journald-volatile.conf \
  /etc/systemd/journald.conf.d/server-meter-volatile.conf
sudo systemctl restart systemd-journald
```

Ověření:

```bash
grep Storage /etc/systemd/journald.conf.d/server-meter-volatile.conf
ls -d /run/log/journal
```

Očekávané: `Storage=volatile`. Po rebootu budou journal záznamy **pryč**. Kompletní vysvětlení: [SYSTEMD.md](SYSTEMD.md).

Podrobnosti služby: [SYSTEMD.md](SYSTEMD.md).

### Test po rebootu

```bash
sudo reboot
```

Po SSH:

```bash
systemctl status server-meter --no-pager
curl http://127.0.0.1:8080/api/health
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
```

**Očekávaný výsledek historie:** `"count": 0` nebo jen vzorky od tohoto bootu, `"source": "ram"`, `"persistent": false`. Grafy začínají prázdné.

---

## 15. Testy (volitelné, bez BME690)

Na vývojovém stromu (nebo v `/opt/server-meter`):

```bash
sudo -u server-meter /opt/server-meter/venv/bin/pip install -r /opt/server-meter/requirements-dev.txt
cd /opt/server-meter
sudo -u server-meter /opt/server-meter/venv/bin/python -m pytest
```

Testy používají `sensor.driver: mock` a **nevyžadují** fyzický BME690.

Mock ručně: [CONFIGURATION.md](CONFIGURATION.md) (`config/config.mock.yaml`, heslo `devpass1`, `environment: development`).

---

## 16. Nagios

Až dashboard běží, pokračujte v [NAGIOS.md](NAGIOS.md). Endpoint:

```text
GET /api/nagios/check
```

---

## Installation checklist

- [ ] Raspberry Pi vypnuto
- [ ] BME690 zapojen
- [ ] RED → PIN 1
- [ ] BLACK → PIN 6
- [ ] BLUE → PIN 3
- [ ] YELLOW → PIN 5
- [ ] Ubuntu Server aktualizován
- [ ] `uname -m` = `aarch64`
- [ ] I²C aktivní
- [ ] `/dev/i2c-*` existuje
- [ ] BME690 nalezen přes `i2cdetect -y 1`
- [ ] správná adresa 0x76/0x77 v YAML
- [ ] `/opt/server-meter/venv` nainstalován
- [ ] BSEC `libalgobsec.so` (nebo víte, že IAQ bude `null`)
- [ ] YAML nakonfigurován
- [ ] heslo není `CHANGE_ME` (≥ 8 znaků)
- [ ] `chmod` YAML 640, vlastník `root:server-meter`
- [ ] uživatel `server-meter` ve skupině `i2c`
- [ ] manuální start funguje
- [ ] `/api/health` funguje
- [ ] web dashboard funguje
- [ ] systemd `active (running)`
- [ ] služba naběhne po rebootu
- [ ] BME690 hodnoty se aktualizují
- [ ] grafy se plní
- [ ] po restartu je historie prázdná
- [ ] Nagios endpoint funguje
- [ ] Nagios Core kontrola funguje (plugin na Nagios serveru)
- [ ] disk-write audit (viz STORAGE-POLICY.md)
- [ ] journald `Storage=volatile` (volitelné, doporučené)

---

# Rychlá instalace – příkazy krok za krokem

Tato kapitola **nenahrazuje** text výše. Je pro člověka, který dokumentaci už četl.

`YOUR_PASSWORD` a `RPI_IP` doplňte.

### STEP 1 — Update OS

```bash
sudo apt update
sudo apt full-upgrade -y
sudo reboot
```

### STEP 2 — Install dependencies

```bash
sudo apt install -y python3 python3-venv python3-dev python3-pip build-essential i2c-tools git
```

### STEP 3 — Enable I²C

```bash
grep -n 'dtparam=i2c_arm=on' /boot/firmware/config.txt || echo 'dtparam=i2c_arm=on' | sudo tee -a /boot/firmware/config.txt
echo 'i2c-dev' | sudo tee /etc/modules-load.d/server-meter-i2c.conf
sudo modprobe i2c-dev
sudo reboot
```

### STEP 4 — Detect BME690

```bash
ls -l /dev/i2c*
sudo i2cdetect -y 1
```

### STEP 5 — Install server-meter

```bash
cd ~
git clone https://github.com/D0ctor1/server-meter.git
cd server-meter
sudo ./scripts/install.sh
sudo ./scripts/enable_i2c.sh
sudo usermod -aG i2c server-meter
```

### STEP 6 — Install BSEC

Součást `install.sh` (krok 6). Cíl:

```text
/opt/server-meter/lib/libalgobsec.so
```

Ručně jen když stažení z Bosch selže: [BME690-BSEC.md](BME690-BSEC.md).

### STEP 7 — Configure server-meter

```bash
sudo nano /etc/server-meter/config.yaml
```

Heslo, `sensor.i2c.address`, volitelně `sensor.bsec.library_path`.

### STEP 8 — Test manually

```bash
sudo -u server-meter /opt/server-meter/venv/bin/python -m server_meter --config /etc/server-meter/config.yaml
```

V druhém terminálu:

```bash
curl http://127.0.0.1:8080/api/health
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/current
```

`Ctrl+C` v prvním terminálu.

### STEP 9 — Start systemd

```bash
sudo systemctl start server-meter
sudo systemctl enable server-meter
systemctl status server-meter --no-pager
sudo mkdir -p /etc/systemd/journald.conf.d
sudo cp /opt/server-meter/docs/journald-volatile.conf \
  /etc/systemd/journald.conf.d/server-meter-volatile.conf
sudo systemctl restart systemd-journald
```

### STEP 10 — Test web UI

```bash
hostname -I
```

Prohlížeč: `http://RPI_IP:8080/`

### STEP 11 — Configure Nagios

Viz [NAGIOS.md](NAGIOS.md).

### STEP 12 — Verify RAM-only storage

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
sudo systemctl restart server-meter
sleep 2
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/history
```

Po restartu `count` klesne na nulu (nebo jen nové vzorky). `"persistent": false`.
