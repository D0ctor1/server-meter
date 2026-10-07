# E-mailové notifikace

server-meter umí poslat WARNING / CRITICAL / RECOVERY e-mail, když naměřená hodnota zůstane mimo nastavený práh. Stav alarmu je **jen v RAM**. Historie měření se na SD kartu nikdy nezapisuje. SMTP nastavení smí být v YAML, protože jde o administrativní konfiguraci.

```text
BME690 / systém
        │
        ▼
   Measurement (RAM)
        │
        ▼
 NotificationEngine (RAM state)
        │
        ├── min duration
        ├── hysteresis
        └── cooldown
        │
        ▼
   SMTP queue (RAM, max 10)
        │
        ▼
     administrátor
```

Chybějící blok `notifications:` je platný. E-mail zůstane **vypnutý**, existující instalace nic neposílají.

---

## Co prahy znamenají

Výchozí hodnoty jsou **default anomaly thresholds**. Nejsou:

- zdravotním limitem,
- hygienickou normou,
- certifikovaným měřením toxických plynů.

BME690 / BSEC dodává indikátory kvality vzduchu (IAQ, eCO₂, bVOC, odpor plynu). Text alarmu proto používá formulace jako *Air quality anomaly* / *Unusually high air-quality indicator*, nikoli *Toxic gas detected*.

---

## YAML model

```yaml
notifications:
  enabled: false
  max_queue_size: 10
  email:
    enabled: false
    cooldown_seconds: 3600
    notify_recovery: true
    from: "server-meter@example.com"
    to:
      - "admin@example.com"
    web_url: "http://192.168.1.50:8080"
    smtp:
      host: "smtp.example.com"
      port: 587
      security: "starttls"   # none | starttls | tls
      username: "server-meter@example.com"
      password: "CHANGE_ME"
      timeout_seconds: 15
  thresholds:
    temperature:
      enabled: true
      warning_high: 45
      critical_high: 50
      hysteresis: 2
      min_duration_seconds: 30
```

`web.locale` určuje jazyk e-mailu (CZ/EN) stejně jako dashboard. Technické tokeny `WARNING` / `CRITICAL` / `RECOVERY` / `NORMAL` a subject prefix `[server-meter][…]` zůstávají.

---

## Podporované metriky a výchozí prahy

| Metrika | Zapnuto | WARNING | CRITICAL | Hystereze | min. trvání |
|---|---|---:|---:|---:|---:|
| `temperature` | ano | ≥ 45 °C | ≥ 50 °C | 2 | 30 s |
| `humidity` | ano | ≥ 80 % | ≥ 90 % | 2 | 30 s |
| `pressure` | ne | ≤ 980 / ≥ 1040 hPa | ≤ 960 / ≥ 1060 hPa | 5 | 30 s |
| `gas_resistance` | ne | ≤ 20 kΩ | ≤ 8 kΩ | 2000 Ω | 30 s |
| `iaq` | ano | ≥ 150 | ≥ 250 | 10 | 60 s |
| `iaq_accuracy` | ne | ≤ 1 | ≤ 0 | 0 | 300 s |
| `static_iaq` | ne | ≥ 150 | ≥ 250 | 10 | 60 s |
| `eco2` | ano | ≥ 1500 ppm | ≥ 2500 ppm | 100 | 60 s |
| `bvoc` | ano | ≥ 1.0 ppm | ≥ 2.0 ppm | 0.1 | 60 s |
| `cpu_temperature` | ano | ≥ 70 °C | ≥ 80 °C | 2 | 30 s |
| `cpu_usage` | ne | ≥ 85 % | ≥ 95 % | 5 | 60 s |
| `ram_usage` | ano | ≥ 70 % | ≥ 85 % | 5 | 60 s |
| `sensor_unavailable` | ano | stáří ≥ 15 s | stáří ≥ 30 s | 5 | 0 s |

Dolní i horní mez lze nastavit u každé metriky (`warning_low` / `critical_low` / `warning_high` / `critical_high`). Explicitní clear meze: `warning_clear_high`, `critical_clear_high`, `warning_clear_low`, `critical_clear_low`.

---

## Hystereze

Bez hystereze by hodnota kolem prahu střídala WARNING/NORMAL a spamovala e-maily.

Příklad teplota (hysteresis 2):

```text
WARNING:           >= 45 °C
WARNING clear:     < 43 °C
CRITICAL:          >= 50 °C
CRITICAL clear:    < 48 °C
```

---

## Minimální doba

`min_duration_seconds` — stav musí trvat alespoň tak dlouho, než se alarm vyhlásí. Jeden chybný vzorek nestačí.

---

## Cooldown

`email.cooldown_seconds` (výchozí 3600). Dokud alarm trvá, další e-mail stejné metriky se pošle nejdřív po cooldownu. Eskalace WARNING → CRITICAL cooldown obchází.

---

## Recovery

`email.notify_recovery: true` pošle jeden e-mail při návratu do NORMAL, a jen pokud se předtím opravdu odeslal WARNING/CRITICAL. Subject:

```text
[server-meter][RECOVERY] BME690 temperature
```

---

## SMTP a bezpečnost

Nastavení je ve webovém **Nastavení** (ikona ⚙). Uložení přepíše v YAML jen klíč `notifications` (atomic write: temp + fsync + rename, `fcntl` lock).

Heslo SMTP:

- je v `/etc/server-meter/config.yaml` (mode **660** `root:server-meter`, aby služba mohla uložit Settings),
- **není** v API, HTML, JS, Nagios výstupu ani v journald,
- GET `/api/settings` vrací jen `password_set: true/false`.

Testovací e-mail: tlačítko **Odeslat testovací email** / **Send test email**. Subject `[server-meter][TEST]`. Neexistuje tlačítko „vygeneruj falešný CRITICAL“.

Odesílání běží v background workeru (`asyncio.Queue`, max 10, drop oldest). Timeout SMTP je povinný. Chyba SMTP:

- nespadí měření, web ani FastAPI,
- zaloguje se bez hesla,
- nastaví `delivery_ok=false`.

Žádné nekonečné retry. Fronta není na disku.

Audit: `Notification configuration changed` do journald. Nikdy `password changed from X to Y`.

Po uložení Settings se konfigurace **reloaduje v procesu** (bez rebootu Pi, bez `systemctl restart`, pokud zápis YAML projde).

---

## Nagios vs e-mail

Jsou to **dvě nezávislé** vrstvy. server-meter neposílá e-mail Nagiosu.

```text
senzor → server-meter SMTP → admin
senzor → /api/monitoring → Nagios plugin → Nagios notifikace
```

Stejná událost může vyvolat oba e-maily. Doporučení: server-meter e-mail pro sensor-specific odchylky, Nagios pro dostupnost služby. Žádná automatická synchronizace.

Prahy a doporučený stav pro shell plugin `check_server_meter.sh` čte z `/api/monitoring` (autorita je server-meter). URL a heslo jsou ve skriptu pluginu, ne v extra Nagios conf souboru. Legacy `/api/nagios/check` dál používá `nagios.thresholds` — ty se mohou lišit, pokud je vědomě nastavíte jinak.

Podrobnosti: [NAGIOS.md](NAGIOS.md).
