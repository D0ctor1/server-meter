# Aktualizace server-meter

Historii senzoru **nemigrujete**. Je jen v RAM a po restartu služby zmizí.

YAML v `/etc/server-meter/config.yaml` `install.sh` **nepřepíše**, pokud už existuje. Chybějící `web.locale` znamená české UI (`CZ`); instalátor locale do existujícího YAML nedoplňuje.

---

## 1. Záloha konfigurace

**Proč:** nová verze může přidat klíče; staré heslo a I²C adresu chcete zachovat.

```bash
sudo cp -a /etc/server-meter/config.yaml \
  /etc/server-meter/config.yaml.bak.$(date +%Y%m%d)
sudo ls -l /etc/server-meter/config.yaml*
```

Ověřte, že záloha má pořád `640 root:server-meter` (nebo ji znovu `chmod 640` / `chown root:server-meter`).

---

## 2. Zastavení služby

```bash
sudo systemctl stop server-meter
systemctl is-active server-meter
```

Očekávaný výsledek: `inactive`.

Grafy po dalším startu začnou prázdné.

---

## 3. Aktualizace zdrojového kódu

Pokud je `/opt/server-meter` git clone (po `install.sh` tam git být nemusí — skript `.git` vyřazuje):

**Varianta A — nový clone + install.sh** (stejné jako instalace):

```bash
cd ~
git clone https://github.com/D0ctor1/server-meter.git server-meter-src
cd server-meter-src
git fetch origin
git checkout <TAG_NEBO_VĚTEV>
sudo ./scripts/install.sh
```

`install.sh` synchronizuje soubory do `/opt/server-meter`, znovu sestaví venv závislosti z `requirements.txt` a **ponechá** existující `/etc/server-meter/config.yaml`.

**Varianta B — už máte pracovní strom:**

```bash
cd ~/server-meter-src
git pull
sudo ./scripts/install.sh
```

> ⚠️ **VYŽADUJE OVĚŘENÍ:** URL a výchozí větev podle vašeho forku. Tag/commit volte vědomě.

Nepoužívejte `curl … | sudo bash`.

---

## 4. Python závislosti

`install.sh` už spouští:

```bash
/opt/server-meter/venv/bin/pip install --upgrade pip
/opt/server-meter/venv/bin/pip install -r /opt/server-meter/requirements.txt
```

Ručně totéž, pokud jste kopírovali soubory bez skriptu:

```bash
sudo /opt/server-meter/venv/bin/pip install --upgrade pip
sudo /opt/server-meter/venv/bin/pip install -r /opt/server-meter/requirements.txt
```

---

## 5. Změny YAML

Porovnejte s novou šablonou:

```bash
diff -u /etc/server-meter/config.yaml /opt/server-meter/config/config.example.yaml
```

Do produkčního souboru **nekopírujte** `password: CHANGE_ME`. Přidejte jen nové klíče, které kód vyžaduje (`extra="forbid"` — neznámý klíč start **shodí**).

`persist_state` musí zůstat `false`.

Dokumentace klíčů: [CONFIGURATION.md](CONFIGURATION.md).

---

## 6. Testy

Volitelné, bez BME690:

```bash
sudo -u server-meter /opt/server-meter/venv/bin/pip install -r /opt/server-meter/requirements-dev.txt
cd /opt/server-meter
sudo -u server-meter /opt/server-meter/venv/bin/python -m pytest
```

Očekávaný konec: `passed` (projekt 1.0.0 má sadu v `tests/`).

---

## 7. Start služby

```bash
sudo systemctl daemon-reload
sudo systemctl start server-meter
systemctl status server-meter --no-pager
```

Očekávané: `Active: active (running)`.

Pokud unit v gitu přibyly direktivy, `install.sh` unit znovu nainstaluje (`install -m 0644`).

---

## 8. Kontrola API

```bash
curl -sS http://127.0.0.1:8080/api/health
curl -sS -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/current
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8080/api/current
```

Health: `{"status":"ok","service":"server-meter"}`.  
Current: HTTP 200 s `available` true/false.  
Bez hesla: `401`.

Hlavička `X-server-meter` obsahuje verzi (`1.0.0` nebo novější podle `__init__.py`).

```bash
curl -sS -D - -o /dev/null http://127.0.0.1:8080/api/health | grep X-server-meter
```

---

## 9. Kontrola senzoru

```bash
sudo i2cdetect -y 1
curl -sS -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/sensor
journalctl -u server-meter --no-pager -n 40
```

`status` by měl přejít na `ok` do několika intervalů.

---

## 10. Kontrola Nagios

Z Nagios serveru:

```bash
/usr/local/nagios/libexec/check_server_meter.py \
  --url http://RPI_IP:8080/api/nagios/check \
  --user admin \
  --password 'YOUR_PASSWORD'
echo $?
```

Po upgradu **zkopírujte i plugin**, pokud se změnil `scripts/check_server_meter.py`.

---

## BSEC při upgradu

`install.sh` ponechá existující `/opt/server-meter/lib/libalgobsec.so` (rsync ho nemaže). Chcete-li znovu stáhnout oficiální ZIP z Bosch: `SERVER_METER_BSEC_REFRESH=1 sudo ./install.sh`. Licence: [BME690-BSEC.md](BME690-BSEC.md).

---

## Rollback

```bash
sudo systemctl stop server-meter
sudo cp -a /etc/server-meter/config.yaml.bak.YYYYMMDD /etc/server-meter/config.yaml
sudo chown root:server-meter /etc/server-meter
sudo chmod 0750 /etc/server-meter
sudo chmod 640 /etc/server-meter/config.yaml
sudo chown root:server-meter /etc/server-meter/config.yaml
```

Pak nainstalujte předchozí tag stejným `install.sh` a `sudo systemctl start server-meter`.
