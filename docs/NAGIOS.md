# Integrace s Nagios Core 4.4.5

Nagios Core běží **typicky na jiném serveru** než Raspberry Pi. Kontroluje server-meter přes HTTP.

**Globální Python 2.7 prostředí Nagiosu se nemění.** Do Nagios hostitele se Python 3 kvůli server-meter neinstaluje. Plugin **nepotřebuje jq**.

```text
Nagios Core 4.4.5
       │
       │ execute check_server_meter.sh   (žádné argumenty)
       ▼
check_server_meter.sh
  URL + username + password + timeouty jsou VE SKRIPTU
       │
       │ curl + HTTP Basic Auth
       ▼
Raspberry Pi 5  server-meter :8080
GET /api/monitoring
```

Celá konfigurace spojení je v `check_server_meter.sh`. **Žádný** `/etc/nagios/private/server-meter.conf` ani jiný extra soubor.

Autorita stavu je server-meter (`overall` v JSON). Performance data nesou hodnoty a WARNING/CRITICAL prahy z téhož JSON.

Legacy endpoint `GET /api/nagios/check` + `scripts/check_server_meter.py` zůstává. Používá `nagios.thresholds` v YAML — ty se mohou vědomě lišit od e-mailových prahů.

server-meter **neposílá e-mail Nagiosu**. Nagios má vlastní notifikace. Stejná událost může vyvolat e-mail z obou systémů; synchronizace neexistuje. Viz [NOTIFICATIONS.md](NOTIFICATIONS.md).

Tento dokument předpokládá **Nagios Core 4.4.5**. Cesty k `nagios.cfg` se liší podle toho, jestli jste Core kompilovali ze zdroje, nebo použili balíček distro.

---

## Preferovaný plugin `check_server_meter.sh`

Na **Nagios serveru** (ne na Raspberry Pi):

```bash
sudo ./scripts/install_nagios_plugin.sh
```

Výchozí cesta: `/usr/lib/nagios/plugins/check_server_meter.sh` (upravitelná nahoře v instalátoru jako `PLUGIN_DIR`). Práva **0700**, vlastník `nagios:nagios`. Heslo je ve skriptu, proto nesmí být world-readable.

Instalátor Python, jq ani `nagios.cfg` nemění. Při opakovaném spuštění aktualizuje jen tento plugin a **ponechá** existující URL/heslo.

Upravte blok nahoře ve nainstalovaném skriptu:

```bash
SERVER_METER_URL="http://RPI_IP:8080"
SERVER_METER_USERNAME="admin"
SERVER_METER_PASSWORD="YOUR_PASSWORD"
CONNECT_TIMEOUT=5
REQUEST_TIMEOUT=10
CURL_INSECURE=false
```

HTTPS: certifikát se ověřuje. Self-signed jen když `CURL_INSECURE=true`.

Ruční test **bez argumentů**:

```bash
/usr/lib/nagios/plugins/check_server_meter.sh
echo $?
```

Očekávaný výstup:

```text
OK - server-meter reachable, temperature=24.3C humidity=45.2% IAQ=42.1 ... | temperature=24.3;45;50 humidity=45.2;80;90 ...
```

Exit: `0` OK, `1` WARNING, `2` CRITICAL, `3` UNKNOWN. Nedostupnost HTTP → 2. Neplatné JSON → 3.

Nagios potřebuje jen command bez parametrů:

```nagios
define command {
    command_name    check_server_meter
    command_line    /usr/lib/nagios/plugins/check_server_meter.sh
}

define service {
    use                 generic-service
    host_name           raspberrypi
    service_description Server Meter
    check_command       check_server_meter
}
```

Plugin jen volá HTTP. Neimportuje `server_meter`, nečte filesystem Raspberry Pi, nepoužívá Python ani jq, neukládá odpověď API na disk.

---

## Co endpoint skutečně vrací

Kód: `server_meter/api/nagios.py`, trasa v `server_meter/api/routes.py`.

| Věc | Skutečné chování |
|---|---|
| HTTP status | **vždy 200**, když proces odpoví |
| Tělo | jeden řádek začínající `OK`, `WARNING`, `CRITICAL` nebo `UNKNOWN` |
| `X-Nagios-Status` | `0` / `1` / `2` / `3` (HTTP je case-insensitive; Uvicorn na drátě pošle `x-nagios-status`) |
| `X-Nagios-State` | stejné slovo jako začátek těla (`x-nagios-state`) |
| Auth | stejné HTTP Basic Auth jako zbytek API |

### Proč HTTP 200 není Nagios exit code

Vzdálený HTTP server **nemůže** nastavit unix exit code procesu na Nagios serveru.

| Vrstva | Co nese |
|---|---|
| HTTP status | dostupnost FastAPI (200 = odpověď doručena) |
| Tělo + hlavičky | stav kontroly (OK/WARNING/CRITICAL/UNKNOWN) |
| Exit code pluginu | `0`/`1`/`2`/`3` procesu, který Nagios spustí **u sebe** |

Legacy plugin `scripts/check_server_meter.py` čte hlavičku `X-Nagios-State` (případně první slovo těla) a **sám** vrátí odpovídající exit code. Preferujte `check_server_meter.sh` + `/api/monitoring`, pokud na Nagios hostiteli nechcete Python 3.

`check_http` standardně mapuje HTTP 200 → OK. WARNING i CRITICAL endpointu zůstanou HTTP 200, takže **`check_http` bez další logiky nerozliší** WARNING od OK.

---

## Mapování stavů (implementace)

`NagiosState` (`IntEnum`):

| Exit / hlavička | Slovo | Kdy (zjednodušeně) |
|---|---|---|
| 0 | OK | senzor dostupný, data čerstvá, prahy v pořádku |
| 1 | WARNING | CPU teplota / RAM / load1 / IAQ nad warning, nebo firmware throttle |
| 2 | CRITICAL | výpadek BME690, stará data, nebo kryty prahy |
| 3 | UNKNOWN | start bez vzorku, nebo `nagios.enabled: false` |

Kontroly v `evaluate_nagios()` (v tomto pořadí, bere se **nejhorší** numerická hodnota):

1. `nagios.enabled: false` → okamžitě `UNKNOWN - Nagios checks disabled`
2. Stav senzoru `unknown`/`initializing` a žádný vzorek → UNKNOWN (`sensor state unknown`)
3. Stav `unavailable` nebo žádný vzorek → CRITICAL (`BME690 communication failure`)
4. Stáří vzorku `>` `nagios.sensor_max_age_seconds` (výchozí 30 s) → CRITICAL
5. Jinak zpráva `BME690 reachable`
6. CPU teplota Pi (`cpu_temperature_warning` / `_critical`)
7. RAM % (`ram_usage_warning` / `_critical`)
8. Load 1 min (`cpu_load_warning` / `_critical`)
9. Throttle bity `throttled` / `under_voltage` / `soft_temp_limit` → WARNING
10. IAQ, **jen pokud BSEC vrátil číslo** (`iaq_warning` / `_critical`)

Výchozí prahy jsou v `config/config.example.yaml` a v [CONFIGURATION.md](CONFIGURATION.md).

> **Známé omezení kódu:** `UNKNOWN = 3` je numericky větší než `CRITICAL = 2`. Když se současně vyhodnotí UNKNOWN (inicializace) i třeba vysoká teplota CPU, zůstane UNKNOWN. Při běžném provozu po první úspěšné konverzi to nevadí.

---

## Krok 1 — Ruční test z Nagios serveru

**Proč:** nejdřív ověříte síť, firewall a heslo, až potom konfiguraci Nagios.

Na **Nagios serveru**:

```bash
curl -u admin:YOUR_PASSWORD \
  -D - \
  http://RPI_IP:8080/api/nagios/check
```

Dosadíte:

- `YOUR_PASSWORD` — `web.auth.password`
- `RPI_IP` — adresa Pi z `hostname -I` (příklad `192.168.1.50`)

### Očekávané tělo (příklady)

Úspěch:

```text
OK - BME690 reachable; temperature=24.1C, humidity=45.2%, pressure=1008.2hPa, gas=123.4kOhm, iaq=42.1, sensor_age=2s, cpu_temp=48.2C, ram=31%
```

`iaq=…` je v těle jen když BSEC hodnotu dodal.

Senzor odpojený:

```text
CRITICAL - BME690 communication failure; sensor_age=n/a, cpu_temp=48.2C, ram=31%
```

Ještě žádný vzorek po startu:

```text
UNKNOWN - sensor state unknown; sensor_age=n/a, cpu_temp=48.2C, ram=31%
```

Nagios vypnutý v YAML:

```text
UNKNOWN - Nagios checks disabled
```

HTTP kód musí být **200**. Hlavičky:

```text
x-nagios-status: 0
x-nagios-state: OK
```

(nebo 1/2/3 podle stavu). Uvicorn/ASGI posílá názvy hlaviček malými písmeny. `curl`, `http.client` i Nagios plugin je najdou i jako `X-Nagios-Status` — HTTP je case-insensitive. Porovnání v `bash` (`[[ … == *X-Nagios-Status:* ]]`) case-sensitive **není** a instalátor proto používá `grep -i`.

### Pokud curl selže

| Symptom | Co zkontrolovat |
|---|---|
| `Connection refused` | `systemctl status server-meter`, `ss -lntp \| grep 8080` na Pi |
| timeout | firewall, špatná IP, Pi v jiné VLAN |
| HTTP 401 | username/password, mezery v YAML |
| HTTP 404 | překlep v URL — musí být `/api/nagios/check` |

---

## Krok 2 — Plugin `check_server_meter.py`

Soubor v projektu: `scripts/check_server_meter.py`.

Používá jen standardní knihovnu Pythonu (`urllib`). Na Nagios serveru stačí `python3`.

### Instalace pluginu na Nagios server

Cesta `$USER1$` je v Nagios `resource.cfg`. U instalace ze zdroje bývá:

```text
$USER1$=/usr/local/nagios/libexec
```

> ⚠️ **VYŽADUJE OVĚŘENÍ:** Na vašem Nagios hostiteli otevřete `resource.cfg` a ověřte `$USER1$`. U balíčku `nagios4` na Debian/Ubuntu to často bývá `/usr/lib/nagios/plugins`.

```bash
sudo install -m 0755 check_server_meter.py /usr/local/nagios/libexec/check_server_meter.py
```

Skript zkopírujte z Pi nebo z git klonu (stejná verze jako server-meter).

Plugin musí být spustitelný uživatelem, pod kterým běží Nagios (často `nagios`):

```bash
sudo chown nagios:nagios /usr/local/nagios/libexec/check_server_meter.py
ls -l /usr/local/nagios/libexec/check_server_meter.py
```

### Ověření z příkazové řádky (ještě mimo Nagios)

```bash
/usr/local/nagios/libexec/check_server_meter.py \
  --url http://RPI_IP:8080/api/nagios/check \
  --user admin \
  --password 'YOUR_PASSWORD'
echo $?
```

**Očekávaný výsledek:** stejný text jako curl; `echo $?` je `0`, `1`, `2` nebo `3`.

Argumenty skriptu (skutečné, z `argparse`):

| Argument | Výchozí | Význam |
|---|---|---|
| `--url` | `http://127.0.0.1:8080/api/nagios/check` | plná URL |
| `--user` | prázdné | Basic Auth uživatel |
| `--password` | prázdné | Basic Auth heslo |
| `--timeout` | `8.0` | timeout v sekundách |
| `--no-auth` | vypnuto | neposílat Authorization |

HTTP chyba / nedostupnost / timeout → plugin tiskne `CRITICAL - …` a končí **2**.

Neočekávané tělo → `UNKNOWN - unexpected plugin output: …` a končí **3**.

Heslo **nedávejte** do query stringu URL.

---

## Krok 3 — Definice command a service

Příklad pro Nagios Core. Upravte `host_name` podle vašeho `define host`.

```nagios
define command {
    command_name    check_server_meter
    command_line    $USER1$/check_server_meter.py --url http://$HOSTADDRESS$:8080/api/nagios/check --user $ARG1$ --password $ARG2$
}

define service {
    use                 generic-service
    host_name           server-meter
    service_description BME690 server-meter
    check_command       check_server_meter!admin!YOUR_PASSWORD
    check_interval      1
    retry_interval      1
    max_check_attempts  3
}
```

`YOUR_PASSWORD` nahraďte skutečným heslem, nebo (lépe) použijte makra v `resource.cfg` (`$USER3$` atd.), aby heslo nebylo v `*.cfg` čitelné všemi.

Host (pokud ještě nemáte):

```nagios
define host {
    use                     generic-host
    host_name               server-meter
    alias                   Raspberry Pi 5 server-meter
    address                 RPI_IP
    max_check_attempts      5
    check_period            24x7
    notification_interval   30
    notification_period     24x7
}
```

`RPI_IP` je adresa Pi, **ne** smyšlená.

Kam soubor uložit, závisí na instalaci. Často:

```text
/usr/local/nagios/etc/objects/server-meter.cfg
```

nebo u `nagios4`:

```text
/etc/nagios4/conf.d/server-meter.cfg
```

V hlavním `nagios.cfg` musí být `cfg_file=` nebo `cfg_dir=` na tento soubor.

---

## Krok 4 — Validace konfigurace Nagios

**Ze zdroje (běžné):**

```bash
sudo /usr/local/nagios/bin/nagios -v /usr/local/nagios/etc/nagios.cfg
```

**Balíček nagios4 na Debian/Ubuntu (pokud tak máte nainstalováno):**

```bash
sudo /usr/sbin/nagios4 -v /etc/nagios4/nagios.cfg
```

> ⚠️ **VYŽADUJE OVĚŘENÍ:** Spusťte `command -v nagios; command -v nagios4; ls /usr/local/nagios/bin/nagios /usr/sbin/nagios4 2>/dev/null` a použijte **existující** binárku a **existující** `nagios.cfg`.

### Očekávaný výsledek

Na konci výstupu:

```text
Total Warnings: 0
Total Errors: 0
```

Pak reload (ne restart, pokud chcete zachovat stav):

```bash
sudo systemctl reload nagios
```

nebo u nagios4:

```bash
sudo systemctl reload nagios4
```

Název jednotky ověřte:

```bash
systemctl list-units --type=service | grep -i nagios
```

---

## check_http (pouze dostupnost HTTP)

Plugin z monitoring-plugins / nagios-plugins. Na Ubuntu Nagios serveru často:

```text
/usr/lib/nagios/plugins/check_http
```

### Ruční ověření syntaxe na **vašem** Nagios serveru

```bash
/usr/lib/nagios/plugins/check_http -h
```

Ověřte, že existují `-H`, `-p`, `-u`, `-a`, `-e`, `-t`. Tento projekt `check_http` neupravuje.

### Příkaz, který jen dokáže HTTP 200

```bash
/usr/lib/nagios/plugins/check_http \
  -H RPI_IP \
  -p 8080 \
  -u /api/nagios/check \
  -a admin:YOUR_PASSWORD \
  -e 200 \
  -t 10
```

Význam (monitoring-plugins `check_http`):

| Přepínač | Účel |
|---|---|
| `-H` | Host v HTTP hlavičce / DNS |
| `-p` | TCP port |
| `-u` | cesta URL |
| `-a` | Basic Auth `user:password` |
| `-e 200` | očekávaný HTTP kód |
| `-t 10` | timeout |

Volitelně `-I RPI_IP`, pokud `-H` má být jméno.

Příklad Nagios command **jen pro „proces žije“**:

```nagios
define command {
    command_name    check_server_meter_http
    command_line    $USER1$/check_http -H $HOSTADDRESS$ -p 8080 -u /api/nagios/check -a $ARG1$:$ARG2$ -e 200 -t 10
}
```

Tato kontrola bude **OK**, i když tělo začíná `CRITICAL`. Pro skutečný stav BME690 použijte `check_server_meter.py`.

Přidání `-s "OK"` **není** vhodné: WARNING/CRITICAL pak `check_http` typicky označí jako CRITICAL kvůli chybějícímu řetězci, ne kvůli mapování 0/1/2/3.

---

## Lokální kontrola na Raspberry Pi

Pokud Nagios NRPE běží na Pi (není součástí tohoto projektu):

```bash
/opt/server-meter/venv/bin/python /opt/server-meter/scripts/check_server_meter.py \
  --url http://127.0.0.1:8080/api/nagios/check \
  --user admin \
  --password 'YOUR_PASSWORD'
echo $?
```

---

## Firewall

Na Pi otevřete **8080 jen** z Nagios serveru nebo LAN, ne z celého internetu. Postup: [SECURITY.md](SECURITY.md).

---

## TLS

Plugin volá HTTP. Na nedůvěryhodné síti dejte před server-meter reverse proxy s HTTPS a v `--url` použijte `https://…`. Samotný server-meter TLS **neimplementuje**.

---

## Checklist Nagios

- [ ] `curl` z Nagios serveru vrací HTTP 200 a slovo OK/WARNING/CRITICAL/UNKNOWN
- [ ] `X-Nagios-Status` souhlasí s tělem
- [ ] plugin nainstalován, `echo $?` dává 0–3
- [ ] `define command` + `define service` validní (`nagios -v`)
- [ ] heslo není v URL
- [ ] firewall pouští jen Nagios IP
- [ ] po odpojení senzoru (test) přejde služba do CRITICAL
- [ ] po `systemctl restart server-meter` může krátce být UNKNOWN, pak OK
