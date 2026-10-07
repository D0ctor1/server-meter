# BME690 and BSEC 3.x

## Hardware facts (Bosch BME690 SensorAPI v1.1.0)

| Item | Value |
| --- | --- |
| Chip ID register | `0xD0` |
| Chip ID | `0x61` (`BME69X_CHIP_ID`) |
| I²C addresses | `0x76` (`BME69X_I2C_ADDR_LOW`), `0x77` (`BME69X_I2C_ADDR_HIGH`) |
| Variant register | `0xF0` — BME690 high-gas variant is `0x02` |
| Official C API | https://github.com/boschsensortec/BME690_SensorAPI (BSD-3-Clause) |
| Datasheet | BST-BME690-DS001 (Bosch Sensortec) |

server-meter talks I²C through `smbus2` and applies the **BME690 SensorAPI
v1.1.0 floating-point compensation** (temperature, pressure, humidity, gas
resistance). This is not a BME680/BME688 workaround: coefficient layout and
formulas differ in the 2026 SensorAPI.

Physical units published by the API:

- `temperature` — °C
- `pressure` — hPa (SensorAPI uses Pa; we divide by 100)
- `humidity` — %RH
- `gas_resistance` — Ω

## Why BSEC is required for IAQ

Bosch documents IAQ, static IAQ, CO₂ equivalent, breath-VOC equivalent, gas
percentage and TVOC as **BSEC outputs**, not raw ADC channels. BME690
requires **BSEC 3.2.0.0 or newer**. BSEC 2.x (BME688-era) is the wrong
library.

BSEC is **proprietary**. Bosch publishes it only after you accept their
Software License Agreement. This repository **does not** contain:

- `libalgobsec.a` / `libalgobsec.so`
- BSEC headers
- BSEC configuration blobs
- fake download URLs

Official download page (check Bosch for the current filename):

https://www.bosch-sensortec.com/software-tools/software/bme688-and-bme690-software/

As of 2026 Bosch lists **BSEC v3.3.0.0**. Any 3.2.0.0+ build is acceptable.
Use the Raspberry Pi **aarch64** binary (`PiFour_Armv8` /
`Aarch64-linux-gnu-gcc`). Raspberry Pi 5 (Cortex-A76, ARMv8-A) uses that
64-bit library — not the Pi 3 armv6 hard-float build.

## Manual BSEC install (operator action)

1. Accept the Bosch license and download the BSEC zip for 3.2.0.0+.
2. On the Pi, extract the **aarch64** shared object. Depending on the zip
   layout the file is named `libalgobsec.so` or must be linked from
   `libalgobsec.a`:

   ```bash
   # Example only — paths inside the Bosch zip change between releases.
   sudo mkdir -p /opt/server-meter/lib
   sudo cp path/to/PiFour_Armv8/libalgobsec.so /opt/server-meter/lib/
   sudo chmod 644 /opt/server-meter/lib/libalgobsec.so
   ```

   If the zip only ships a static `.a`, link a shared library yourself:

   ```bash
   gcc -shared -o libalgobsec.so -Wl,--whole-archive libalgobsec.a -Wl,--no-whole-archive -lm -lrt -lpthread
   ```

3. Optionally copy a BSEC IAQ config blob (read-only) and set
   `sensor.bsec.config_blob_path`.
4. In `/etc/server-meter/config.yaml`:

   ```yaml
   sensor:
     driver: bme690
     interval_seconds: 5
     bsec:
       enabled: true
       library_path: /opt/server-meter/lib/libalgobsec.so
       sample_rate: lp
       persist_state: false
   ```

5. `sudo systemctl restart server-meter`

If the library is missing, the web server **still starts**. Physical BME690
values are published; IAQ / eCO2 / bVOC stay `null`. A warning is logged
once.

## BSEC sample rates

| Mode | Bosch rate | Minimum `interval_seconds` |
| --- | --- | --- |
| `lp` | `BSEC_SAMPLE_RATE_LP` = 1/3 Hz (3 s) | 3 |
| `ulp` | `BSEC_SAMPLE_RATE_ULP` = 1/300 Hz | 300 |

The default `interval_seconds: 5` is valid for LP and avoids aggressive
polling. `interval_seconds: 1` with BSEC LP enabled is rejected at startup.

## Outputs we expose (only when BSEC provides them)

Mapped from `bsec_virtual_sensor_t` (BSEC 3.x):

| Field | BSEC id | Unit |
| --- | --- | --- |
| `iaq` / `iaq_accuracy` | `BSEC_OUTPUT_IAQ` (1) | 0–500 / 0–3 |
| `static_iaq` / `static_iaq_accuracy` | `BSEC_OUTPUT_STATIC_IAQ` (2) | index / 0–3 |
| `co2_equivalent` (`eco2`) | `BSEC_OUTPUT_CO2_EQUIVALENT` (3) | ppm |
| `breath_voc_equivalent` (`bvoc`) | `BSEC_OUTPUT_BREATH_VOC_EQUIVALENT` (4) | ppm |
| `raw_temperature` | `BSEC_OUTPUT_RAW_TEMPERATURE` (6) | °C |
| `raw_pressure` | `BSEC_OUTPUT_RAW_PRESSURE` (7) | hPa |
| `raw_humidity` | `BSEC_OUTPUT_RAW_HUMIDITY` (8) | % |
| `gas_resistance` | `BSEC_OUTPUT_RAW_GAS` (9) | Ω |
| `stabilization_status` | `BSEC_OUTPUT_STABILIZATION_STATUS` (12) | 0/1 |
| `run_in_status` | `BSEC_OUTPUT_RUN_IN_STATUS` (13) | 0/1 |
| `temperature` | `BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE` (14) | °C |
| `humidity` | `BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY` (15) | % |
| `gas_percentage` | `BSEC_OUTPUT_GAS_PERCENTAGE` (21) | % |
| `tvoc_equivalent` | `BSEC_OUTPUT_TVOC_EQUIVALENT` (32) | BSEC 3.2+ LP only |

IAQ accuracy: 0 stabilizing, 1 low, 2 medium, 3 high. After reboot accuracy
starts at 0 because state is not restored from the SD card.

TVOC and breath-VOC subscriptions are optional. Some IAQ-only BSEC blobs
reject them (`BSEC_E_CONFIG_FEATUREMISMATCH`). The driver retries without
those outputs rather than inventing values.

Gas-scan estimate channels (`BSEC_OUTPUT_GAS_ESTIMATE_*`) need a BME
AI-Studio selectivity model. They are not subscribed in the default IAQ
configuration.

## Alternative: community Python wrapper

https://github.com/mcalisterkm/bme69x-python-library-bsec3.2.1.0

That wrapper also requires you to download the Bosch zip yourself and compile
on the Pi. If the `bme69x` module is installed:

```yaml
sensor:
  driver: bme69x_python
```

Do not use its save-state examples.

## I²C bring-up

```bash
sudo apt install -y i2c-tools
sudo /opt/server-meter/scripts/enable_i2c.sh
sudo i2cdetect -y 1
```

A BME690 appears as `76` or `77`. Set `sensor.i2c.address` accordingly.
Pimoroni modules are often 0x76 unless a cutoff trace selects 0x77.

Wiring (3.3 V logic, typical breakout):

| BME690 | Raspberry Pi 5 |
| --- | --- |
| VIN / VDD | 3.3 V |
| GND | GND |
| SDA | GPIO2 (pin 3) |
| SCL | GPIO3 (pin 5) |

Do not use 5 V on VIN unless the module has an on-board regulator.

## Known limits

- Without Bosch BSEC, IAQ/eCO2/bVOC are `null` by design.
- BSEC LP is ~3 s; faster polling is rejected.
- IAQ needs days of background calibration for accuracy 3.
- BSEC state is RAM-only, so every reboot restarts calibration.
- ctypes struct layouts match published BSEC 3.x headers. A future Bosch
  ABI change may require a server-meter update.
- Ubuntu Server 26.04 on Pi 5 must have `i2c-dev` and `/dev/i2c-1`.
