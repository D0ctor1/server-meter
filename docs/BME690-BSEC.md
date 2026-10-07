# BME690 a BSEC 3.x

## Co aplikace skutečně dělá

Tři oddělené vrstvy:

1. **I²C** — `smbus2` v `server_meter/sensor/i2c_bus.py`
2. **BME690 SensorAPI v1.1.0** — Python port kompenzace v `server_meter/sensor/bme690.py` (BSD-3-Clause Bosch, [BME690_SensorAPI](https://github.com/boschsensortec/BME690_SensorAPI))
3. **BSEC 3.x** — volitelný ctypes wrapper `server_meter/sensor/bsec.py`

Není to BME688 knihovna. Chip ID musí být `0x61`.

Fyzické výstupy bez BSEC:

| Pole | Jednotka |
|---|---|
| `temperature` | °C |
| `pressure` | hPa (API Pa / 100) |
| `humidity` | % RH |
| `gas_resistance` | Ω |

IAQ, static IAQ, eCO2 (`co2_equivalent`), bVOC (`breath_voc_equivalent`), gas %, TVOC dává **jen BSEC**. Bez knihovny jsou v JSON `null`. To je záměr, ne chyba výpočtu.

---

## Proprietární licence Bosch BSEC

BSEC **není** v git repozitáři a **není** open-source.

`sudo ./install.sh` stáhne oficiální ZIP z Bosch Sensortec software-downloads (jen `bosch-sensortec.com`, verze **3.2.0.0+**). Spuštěním instalátoru potvrzujete Software License Agreement Bosch Sensortec:

https://www.bosch-sensortec.com/media/boschsensortec/downloads/software/bme688_development_software/2024_12/20241219_clickthrough_license_terms_bsec_bme680_bme688_bme690.pdf

Stránka se seznamem souborů:

https://www.bosch-sensortec.com/en/software-tools/software-downloads.html

Marketingová stránka BME688/BME690 (formulář click-through; stejné ZIP jsou i jako přímé `/media/...` odkazy výše):

https://www.bosch-sensortec.com/software-tools/software/bme688-and-bme690-software/

Ověřeno na **BSEC v3.3.0.1** (srpen 2026): v ZIPu je `release_bin/IAQ/bin/RaspberryPi/PiFour_Armv8/libalgobsec.a` (ne `.so`). Instalátor z něj na Pi 5 udělá shared object a zkopíruje read-only blob `bme690_iaq_33v_3s_28d/bsec_iaq.config` (3,3 V, LP 3 s).

Přeskočit stažení: `SERVER_METER_SKIP_BSEC=1 sudo ./install.sh`.  
Vynutit znovu: `SERVER_METER_BSEC_REFRESH=1 sudo ./install.sh`.  
Vlastní ZIP: `SERVER_METER_BSEC_ZIP=/cesta/bsec_v3-3-0-1.zip sudo ./install.sh`.

---

## Jakou binárku vzít (Raspberry Pi 5 / Ubuntu ARM64)

| Požadavek | Hodnota |
|---|---|
| CPU | Raspberry Pi 5, Cortex-A76, ARMv8-A |
| OS | Ubuntu Server 26.04.1 **64-bit** |
| `uname -m` | `aarch64` |
| Bosch složka | typicky **PiFour_Armv8** / překladač `aarch64-linux-gnu-gcc` |

**Nepoužívejte** 32bit `armhf` / Pi 3 armv6 knihovnu.

BSEC 3.3.0.1 dodává **jen** `libalgobsec.a` (ELF AArch64 relocatable). `install.sh` z něj sestaví shared object:

```bash
gcc -shared -o /opt/server-meter/lib/libalgobsec.so \
  -Wl,--whole-archive libalgobsec.a -Wl,--no-whole-archive \
  -lm -lrt -lpthread
```

Při chybě linkeru zkusí ještě `-Wl,-z,notext`. Nepoužívejte 32bit `PiThree_ArmV6` ani `Sel_IAQ`.

---

## Kam soubor umístit

Aplikace hledá (v tomto pořadí) v `server_meter/sensor/bsec.py`:

```text
sensor.bsec.library_path          # z YAML
$SERVER_METER_BSEC_LIB            # env
/opt/server-meter/lib/libalgobsec.so
/usr/local/lib/libalgobsec.so
/usr/lib/libalgobsec.so
/opt/bosch/bsec/libalgobsec.so
libalgobsec.so                    # dynamický linker
```

`install.sh` umisťuje knihovnu sám. Ruční kopie jen když stažení z Bosch selže:

```bash
sudo mkdir -p /opt/server-meter/lib
sudo cp CESTA_Z_BOSCH_ZIP/libalgobsec.so /opt/server-meter/lib/libalgobsec.so
sudo chmod 644 /opt/server-meter/lib/libalgobsec.so
sudo chown root:root /opt/server-meter/lib/libalgobsec.so
```

V `/etc/server-meter/config.yaml`:

```yaml
sensor:
  bsec:
    enabled: true
    library_path: "/opt/server-meter/lib/libalgobsec.so"
    config_blob_path: ""
    sample_rate: "lp"
    persist_state: false
```

Volitelný read-only config blob (`bsec_set_configuration`) se čte z `config_blob_path`, pokud soubor existuje.

```bash
sudo systemctl restart server-meter
journalctl -u server-meter --no-pager -n 50 | grep -i bsec
```

**Očekávaný úspěch:** `BSEC x.y.z.w initialized (state is RAM-only, not written to disk)`

**Očekávaný stav bez knihovny:** jedno WARNING, služba běží, IAQ je `null`.

Ověření z API:

```bash
curl -u admin:YOUR_PASSWORD http://127.0.0.1:8080/api/sensor
```

Pole `driver.bsec_loaded` je `true`/`false`. `bsec_version` je řetězec nebo `null`.

Driver odmítne BSEC starší než 3.2.

---

## BSEC a SD karta

Aplikace **nevolá** `bsec_get_state(` pro zápis na disk. `persist_state: true` konfigurace **odmítne**.

Po rebootu:

- algoritmus začíná znovu,
- `iaq_accuracy` bývá 0 (stabilizing), pak 1–3,
- UI to ukazuje jako „stabilizing / low / medium / high“.

To je záměr kvůli ochraně SD karty.

---

## Sample rate

| YAML `sample_rate` | Bosch | Minimální `interval_seconds` |
|---|---|---|
| `lp` | 1/3 Hz (3 s) | 3 |
| `ulp` | 1/300 Hz | 300 |

Výchozí `interval_seconds: 5` je s LP v pořádku. `interval_seconds: 1` + `bsec.enabled: true` + `lp` **selže při startu**.

---

## Mapování výstupů BSEC 3.x

| JSON pole | BSEC id (v kódu) | Jednotka |
|---|---|---|
| `iaq` / `iaq_accuracy` | 1 | 0–500 / 0–3 |
| `static_iaq` | 2 | index |
| `co2_equivalent` (`eco2`) | 3 | ppm |
| `breath_voc_equivalent` (`bvoc`) | 4 | ppm |
| raw T/p/RH/gas | 6–9 | °C / hPa / % / Ω |
| compensated T/RH | 14, 15 | °C / % |
| `gas_percentage` | 21 | % |
| `tvoc_equivalent` | 31 | jen LP, volitelné (BSEC 3.3) |

`bsec_update_subscription` kód **14** je varování `BSEC_W_SU_SAMPLERATEMISMATCH` (ne fatální chyba). Wrapper kladné kódy bere jako úspěch.

Pokud knihovna TVOC nebo bVOC odmítne, wrapper zopakuje subscribe bez nich. Hodnoty zůstanou `null`.

---

## Známé omezení implementace BSEC

`BsecProcessor.process()` volá **`bsec_do_steps`**. **Nevolá** `bsec_sensor_control`. Heater a oversampling nastavuje `Bme690Driver` forced módem (YAML `heater_temperature_c` / `heater_duration_ms`).

Důsledek: chování se může lišit od oficiálního `bsec_iot_example`. Fyzické hodnoty T/p/RH/gas resistance jsou i tak z oficiální SensorAPI kompenzace.

Komunitní Python modul `bme69x` (driver `bme69x_python`) vyžaduje, abyste ho **sami** zkompilovali proti Bosch ZIP. Tento projekt ho neshípuje. Ani u něj se nesmí používat save-state příklady.

---

## I²C bez BSEC

To stačí na teplotu, vlhkost, tlak a odpor plynu. Dashboard karty IAQ/eCO2/bVOC ukážou „—“.
