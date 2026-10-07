# Integrace s Nagios Core 4.4.5

Nagios Core běží **typicky na jiném serveru** než Raspberry Pi. Kontroluje server-meter přes HTTP.

**Samotný Nagios Core grafy nevytváří.** Služba nese stav, aktuální hodnotu a performance data. Historii a grafy kreslí backend (PNP4Nagios, Nagiosgraph, …).

**Globální prostředí Nagiosu se nemění.** Do Nagios hostitele se kvůli server-meter neinstaluje další interpret. Plugin používá `curl`, `sed`, `awk`, `grep`, `cut`, `printf`.

```text
Nagios Core 4.4.5
       │
       │  check_server_meter.sh $ARG1$
       ▼
check_server_meter.sh     (jeden soubor, všechny služby)
  URL + username + password + prahy jsou VE SKRIPTU
       │
       │  GET /api/monitoring   (celý JSON v RAM, vybere se metrika)
       ▼
Raspberry Pi  server-meter :8080
```

Jeden plugin, mnoho Nagios services. **Žádný** extra `/etc/nagios/private/server-meter.conf`. Nagios object configuration (`define host` / `command` / `service`) je oddělená věc — tu Nagios potřebuje, aby věděl, co zobrazovat.

`Server Meter Health` (prázdné `$ARG1$` nebo `health`) používá `overall` z notifikačního enginu (hysteresis/doba). Jednotlivé metriky porovnávají **aktuální vzorek** s prahy ve skriptu, aby každá služba měla vlastní stav a vlastní časovou řadu.

IAQ prahy jsou BSEC index anomálie, **ne** zdravotní / toxikologická hranice.

Legacy endpoint `GET /api/nagios/check` + `scripts/check_server_meter.py` zůstává.

server-meter **neposílá e-mail Nagiosu**. Nagios má vlastní notifikace. Viz [NOTIFICATIONS.md](NOTIFICATIONS.md).

---

## Preferovaný plugin `check_server_meter.sh`

Na **Nagios serveru** (ne na Raspberry Pi):

```bash
sudo ./scripts/install_nagios_plugin.sh
```

Detekce cesty: `/usr/local/nagios/libexec` (Core ze zdroje), jinak `/usr/lib/nagios/plugins`. Přepis: `PLUGIN_DIR`, `NAGIOS_BIN`, `NAGIOS_CFG`, `NAGIOS_OBJECTS_DIR`.

Práva **0700**, vlastník `nagios:nagios`. Heslo je ve skriptu.

Instalátor:

1. zazálohuje existující plugin / `server-meter.cfg` / `nagios.cfg` (`*.bak.<timestamp>`), starší zálohy nemaže,
2. aktualizuje `check_server_meter.sh` a **ponechá** existující konfigurační blok,
3. nainstaluje chybějící objekty do `server-meter.cfg` (command `$ARG1$`, host, služby) — vždy tentýž soubor, žádné `_2` / `_new`; existující objekty jinde nepřepisuje (`WARNING: existing Nagios object detected`),
4. pokud už existuje `host_name` stejného jména, `define host` nepřidá (`INCLUDE_HOST=auto`),
5. detekuje PNP4Nagios / Nagiosgraph / `process_performance_data` a **neinstaluje** druhý grafovací stack,
6. do `nagios.cfg` přidá `cfg_file=` jen když tam ještě není,
7. spustí `/usr/local/nagios/bin/nagios -v /usr/local/nagios/etc/nagios.cfg` (nebo detekovanou binárku),
8. při chybě konfigurace **neprovádí** reload,
9. při úspěchu reloaduje Nagios (`NAGIOS_RELOAD=0` reload přeskočí).

Upravte blok nahoře ve nainstalovaném skriptu:

```bash
SERVER_METER_URL="http://RPI_IP:8080"
SERVER_METER_USERNAME="admin"
SERVER_METER_PASSWORD="YOUR_PASSWORD"
CONNECT_TIMEOUT=5
REQUEST_TIMEOUT=10
CURL_INSECURE=false

TEMP_WARNING=45
TEMP_CRITICAL=50
CPU_TEMP_WARNING=70
CPU_TEMP_CRITICAL=80
RAM_WARNING=85
RAM_CRITICAL=95
SENSOR_AGE_WARNING=15
SENSOR_AGE_CRITICAL=30
```

HTTPS: certifikát se ověřuje. Self-signed jen když `CURL_INSECURE=true`.

### Proč `$ARG1$`

```nagios
define command {
    command_name    check_server_meter
    command_line    /usr/local/nagios/libexec/check_server_meter.sh $ARG1$
}

define service {
    use                     generic-service
    host_name               server-meter
    service_description     BME690 Temperature
    check_command           check_server_meter!temperature
}
```

`check_server_meter!temperature` předá pluginu argument `temperature`. Nová metrika = větev v `case` ve skriptu + jeden `define service`. Šablona: `scripts/nagios/server-meter.cfg`.

Pokud už máte hosta pod jiným `host_name`, nastavte `NAGIOS_HOST_NAME` a služby se přizpůsobí. Starou jednu službu `Server Meter` nahrazuje `Server Meter Health` plus per-metric služby.

Plugin jen volá HTTP. Neukládá JSON, cache ani historii na disk.

### Ruční test každé metriky

```bash
/usr/local/nagios/libexec/check_server_meter.sh --help
/usr/local/nagios/libexec/check_server_meter.sh
/usr/local/nagios/libexec/check_server_meter.sh temperature
/usr/local/nagios/libexec/check_server_meter.sh humidity
/usr/local/nagios/libexec/check_server_meter.sh pressure
/usr/local/nagios/libexec/check_server_meter.sh gas_resistance
/usr/local/nagios/libexec/check_server_meter.sh iaq
/usr/local/nagios/libexec/check_server_meter.sh iaq_accuracy
/usr/local/nagios/libexec/check_server_meter.sh static_iaq
/usr/local/nagios/libexec/check_server_meter.sh static_iaq_accuracy
/usr/local/nagios/libexec/check_server_meter.sh eco2
/usr/local/nagios/libexec/check_server_meter.sh bvoc
/usr/local/nagios/libexec/check_server_meter.sh cpu_temperature
/usr/local/nagios/libexec/check_server_meter.sh cpu_load
/usr/local/nagios/libexec/check_server_meter.sh ram
/usr/local/nagios/libexec/check_server_meter.sh sensor
echo $?
```

Příklady:

```text
OK - BME690 temperature=24.3 C | temperature=24.3;45;50
OK - BME690 IAQ=52.6 | iaq=52.6;150;250
OK - CPU temperature=48.1 C | cpu_temperature=48.1;70;80
WARNING - BME690 temperature=46.2 C (warning >= 45 C) | temperature=46.2;45;50
CRITICAL - BME690 temperature=51.4 C (critical >= 50 C) | temperature=51.4;45;50
CRITICAL - BME690 sensor unavailable
CRITICAL - BME690 data too old: 37 seconds | sensor_age=37;15;30
UNKNOWN - invalid response from server-meter
```

Exit: `0` OK, `1` WARNING, `2` CRITICAL (včetně nedostupného HTTP), `3` UNKNOWN (neplatné JSON, chybějící metrika, heslo `CHANGE_ME`).

### Performance data a grafy

| Vrstva | Co poskytuje |
|---|---|
| Nagios service | stav, aktuální hodnotu, řádek performance data za `\|` |
| PNP4Nagios / Nagiosgraph | historii, RRD, graf |

Ověření, že Nagios perfdata přijímá:

1. Výstup pluginu obsahuje `| label=value;warn;crit`.
2. V `nagios.cfg` je `process_performance_data=1`.
3. Je nastavený `service_perfdata_command` / `host_perfdata_command`, nebo `*_perfdata_file` + NPCD (PNP4Nagios), nebo ekvivalent Nagiosgraph.
4. Po několika kontrolách existuje RRD/graf pro `server-meter` / `BME690 Temperature` atd.

Pokud už PNP4Nagios nebo Nagiosgraph běží, **neinstalujte druhý** grafovací systém — stačí, že každá služba posílá vlastní perfdata.

#### PNP4Nagios (když ještě není)

Na Nagios hostiteli (ověřte balíčky vaší distro; cesty u Core ze zdroje):

```text
process_performance_data=1
service_perfdata_file=/usr/local/pnp4nagios/var/service-perfdata
service_perfdata_file_template=DATATYPE::SERVICEPERFDATA\tTIMET::$TIMET$\tHOSTNAME::$HOSTNAME$\tSERVICEDESC::$SERVICEDESC$\tSERVICEPERFDATA::$SERVICEPERFDATA$\tSERVICECHECKCOMMAND::$SERVICECHECKCOMMAND$\tHOSTSTATE::$HOSTSTATE$\tHOSTSTATETYPE::$HOSTSTATETYPE$\tSERVICESTATE::$SERVICESTATE$\tSERVICESTATETYPE::$SERVICESTATETYPE$
service_perfdata_file_mode=a
service_perfdata_file_processing_interval=15
service_perfdata_file_processing_command=process-service-perfdata-file
```

Command `process-service-perfdata-file` volá `process_perfdata.pl` z PNP4Nagios. Host perfdata analogicky. Po `nagios -v` a reloadu se v PNP objeví samostatný graf na službu.

#### Nagiosgraph (alternativa, ne souběžně s PNP)

Mapování `$HOSTNAME$/$SERVICEDESC$` na RRD podle `map` souborů Nagiosgraph. Stejný princip: jedna service = jedna řada.

Plugin **nevytváří** grafy uvnitř server-meter.

---

## Legacy endpoint `GET /api/nagios/check`

Preferovaný plugin používá `GET /api/monitoring`. Následující platí jen pro starý textový endpoint.

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
