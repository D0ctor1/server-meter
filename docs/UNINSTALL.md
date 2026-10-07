# Odinstalace server-meter

Skript: `scripts/uninstall.sh`.

**Bez** `--purge`:

- zastaví a disable službu
- smaže `/etc/systemd/system/server-meter.service`
- smaže `/opt/server-meter` (kód + venv)
- **ponechá** `/etc/server-meter` (YAML s heslem)
- **ponechá** uživatele `server-meter`

**S** `--purge`:

- smaže i `/etc/server-meter`
- pokusí se smazat systémového uživatele `server-meter`

Na disku **nikdy nebyla** historie měření ke smazání.

Hardware **nesundávejte** ze zapnutého Pi. Nejdřív vypněte systém, odpojte USB-C, pak vodiče.

---

## Doporučený postup (zachovat konfiguraci)

### 1. Proveď

```bash
sudo systemctl disable --now server-meter
sudo /opt/server-meter/scripts/uninstall.sh
```

Pokud už `/opt` není k dispozici, ekvivalent skriptu:

```bash
sudo systemctl stop server-meter.service
sudo systemctl disable server-meter.service
sudo rm -f /etc/systemd/system/server-meter.service
sudo systemctl daemon-reload
sudo rm -rf /opt/server-meter
```

### 2. Ověř

```bash
systemctl status server-meter --no-pager || true
ls /opt/server-meter
ls /etc/server-meter
ss -lntp | grep 8080 || echo 'port 8080 free'
```

Služba nemá být loaded. `/etc/server-meter/config.yaml` **zůstává**.

Skript na konci vypíše, že konfigurace zůstala. Použijte `--purge` jen když ji chcete smazat.

---

## Úplné odstranění včetně hesla (`--purge`)

Toto **smaže** YAML s credentials. Zálohujte, pokud heslo ještě potřebujete.

```bash
sudo cp -a /etc/server-meter/config.yaml "$HOME/server-meter-config.yaml.bak"
chmod 600 "$HOME/server-meter-config.yaml.bak"
```

```bash
sudo /opt/server-meter/scripts/uninstall.sh --purge
```

Pokud prefix už je pryč:

```bash
sudo rm -rf /etc/server-meter
sudo deluser --system server-meter 2>/dev/null || sudo userdel server-meter 2>/dev/null || true
```

### Ověř

```bash
id server-meter || echo 'user removed'
ls /etc/server-meter || echo 'config dir removed'
```

Skript volá `deluser --system` a při neúspěchu `userdel`.

---

## Co skript nemaže

| Položka | Poznámka |
|---|---|
| I²C overlay v `/boot/firmware/config.txt` | `dtparam=i2c_arm=on` může zůstat |
| `/etc/modules-load.d/server-meter-i2c.conf` | `uninstall.sh` **nemaže** |
| `/etc/systemd/journald.conf.d/server-meter-volatile.conf` | **nemaže** |
| UFW pravidla na port 8080 | **nemaže** |
| Bosch `libalgobsec.so` mimo `/opt/server-meter` | pokud jste ho dali do `/usr/local/lib` |
| Nagios command/service na **jiném** serveru | smažte ručně tam |
| Skupina `i2c` | systémová, nechte být |

### Volitelné dočištění I²C drop-inu

Jen pokud I²C nechcete pro nic jiného:

```bash
sudo rm -f /etc/modules-load.d/server-meter-i2c.conf
```

Řádek `dtparam=i2c_arm=on` v `/boot/firmware/config.txt` smažte ručně, pokud jste ho přidali jen kvůli tomuto projektu. **Před editací config.txt Pi může vyžadovat reboot.** Neměňte GPIO zapojení za běhu.

### Volitelné journald

```bash
sudo rm -f /etc/systemd/journald.conf.d/server-meter-volatile.conf
sudo systemctl restart systemd-journald
```

Tím se journal může vrátit k ukládání na SD (podle zbytku konfigurace Ubuntu).

### Volitelný firewall

```bash
sudo ufw status numbered
```

Smažte pravidlo 8080 číslem, které ukáže `ufw status numbered` — **neuhádněte** číslo z této dokumentace.

---

## Nagios na vzdáleném serveru

Na Nagios hostiteli odstraňte `define service` / `define command` a soubor pluginu, pokud ho nepoužíváte jinde:

```bash
sudo rm -f /usr/local/nagios/libexec/check_server_meter.py
sudo rm -f /usr/local/nagios/libexec/check_server_meter.sh
sudo rm -f /usr/lib/nagios/plugins/check_server_meter.sh
sudo rm -f /usr/local/nagios/etc/objects/server-meter.cfg
```

Odstraňte i `cfg_file=…/server-meter.cfg` z `nagios.cfg`, pokud ho instalátor doplnil.

Pak `nagios -v …` a `systemctl reload` podle [NAGIOS.md](NAGIOS.md).

---

## BME690 hardware

1. `sudo poweroff` (nebo UI shutdown).
2. Odpojte USB-C.
3. Odpojte čtyři Dupont vodiče.

Opakované hot-plug na 3.3 V GPIO **nedělejte**.
