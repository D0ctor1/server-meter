# Hardware a zapojení BME690

Tento dokument popisuje **fyzické** zapojení. Software (I²C, aplikace) je v [INSTALLATION.md](INSTALLATION.md).

> **VYPNI RASPBERRY PI A ODPOJ NAPÁJENÍ** před každou změnou vodičů na GPIO.

## Použitý hardware

| Položka | Specifikace |
|---|---|
| Deska | Raspberry Pi 5 |
| RAM | 4 GB |
| Úložiště | Kingston Industrial 16 GB microSD |
| Senzor | Bosch Sensortec BME690 |
| Rozhraní | I²C (I2C1 / SDA1 SCL1) |
| Kabel | STEMMA QT / Qwiic JST-SH 4-pin → Dupont female |

## Barvy STEMMA QT / Qwiic kabelu

Pro kabel použitý v tomto projektu:

```text
RED    = VCC
BLACK  = GND
BLUE   = SDA
YELLOW = SCL
```

Pokud máte jiný kabel, **neřiďte se barvou naslepo** — ověřte dokumentaci výrobce kabelu. Barvy výše platí pro běžný Adafruit STEMMA QT 4-pin.

## Přesný pinout Raspberry Pi 5

| Kabel | Signál | Raspberry Pi 5 | Physical PIN |
|---|---|---|---|
| RED | 3.3 V | 3V3 | PIN 1 |
| BLACK | GND | Ground | PIN 6 |
| BLUE | SDA | GPIO2 / SDA1 | PIN 3 |
| YELLOW | SCL | GPIO3 / SCL1 | PIN 5 |

### Physical PIN versus GPIO číslo

Na 40pinové hlavici se **fyzické číslo pinu** (1–40, počítáno od USB-C/ETH strany) **nerovná** BCM GPIO číslu.

```text
Physical PIN 1 = 3.3 V          (není GPIO)
Physical PIN 3 = GPIO2 / SDA1
Physical PIN 5 = GPIO3 / SCL1
Physical PIN 6 = GND            (není GPIO)
```

Špatně: „připoj SDA na GPIO 3“.  
Správně: „připoj SDA na **physical PIN 3**, což je **GPIO2**.“

## ASCII schéma

```text
BME690 / STEMMA QT
        │
        │
        ├── RED    VCC ───────────── PIN 1  (3.3V)
        │
        ├── BLACK  GND ───────────── PIN 6  (GND)
        │
        ├── BLUE   SDA ───────────── PIN 3  (GPIO2 / SDA1)
        │
        └── YELLOW SCL ───────────── PIN 5  (GPIO3 / SCL1)
```

### Orientace 40pinové hlavice (Raspberry Pi 5)

Deska USB-C / Ethernet nahoře, GPIO vlevo. PIN 1 je čtvercový plošný spoj, obvykle u rohu s SD kartou / napájením (strana s 3.3 V). Piny jsou ve dvou sloupcích:

```text
        3.3V  (1)  (2)  5V          ← NEPŘIPOJUJTE BME690 NA PIN 2
        GPIO2 (3)  (4)  5V          ← SDA  (BLUE)
        GPIO3 (5)  (6)  GND         ← SCL  (YELLOW)   GND (BLACK)
              (7)  (8)  ...
```

PIN 1 (3.3 V) je **lichý sloupec, první pin**. PIN 2 vedle něj je **5 V — ten nepoužívejte**.

## Napájení 3.3 V — důležité

```text
BME690 připojuj na 3.3 V (PIN 1).

NEPŘIPOJUJ VCC SENZORU NA 5 V (PIN 2 ani PIN 4),
pokud konkrétní breakout výrobce výslovně nepotvrzuje podporu 5V napájení.
```

Pro tento projekt používejte **výhradně 3.3 V**. 5 V na logice I²C může senzor zničit.

## I²C adresa

Oficiální BME690 SensorAPI (`BME69X_I2C_ADDR_LOW` / `HIGH`) povoluje:

- `0x76`
- `0x77`

Výchozí hodnota v `config/config.example.yaml` je **`0x77`**. Mnoho breakoutů (včetně některých Pimoroni) je z výroby na **`0x76`**. Adresu zjistíte až po zapnutí I²C příkazem `sudo i2cdetect -y 1` — viz [INSTALLATION.md](INSTALLATION.md).

Chip ID BME690 je `0x61` (registr `0xD0`). To kontroluje driver `server_meter/sensor/bme690.py`.

## Bezpečný postup zapojení

### 1. Proveď — vypnutí

1. Raspberry Pi **vypni** (`sudo poweroff` pokud běží).
2. Počkej, až zhasne zelená LED aktivity.
3. **Odpoj napájecí USB-C kabel.**
4. Odpoj i další USB napájení, pokud ho používáte.

### 2. Proveď — zapojení

1. Připoj STEMMA QT / Qwiic konektor k BME690 (západka / polarita — nejde zasunout obráceně u JST-SH).
2. Dupont konce:
   - RED → physical **PIN 1** (3.3 V)
   - BLACK → physical **PIN 6** (GND)
   - BLUE → physical **PIN 3** (SDA / GPIO2)
   - YELLOW → physical **PIN 5** (SCL / GPIO3)
3. Zkontrolujte, že žádný Dupont nesedí o pin vedle (zejména ne na 5 V).
4. Zkontrolujte zejména **VCC a GND**.
5. Teprve potom zapojte USB-C napájení a zapněte Pi.

Nikdy nepřepojujte GPIO za běhu Raspberry Pi.

### 3. Ověř po zapnutí (až poběží Ubuntu)

```bash
ls -l /dev/i2c*
sudo i2cdetect -y 1
```

Očekávaný výsledek po aktivaci I²C: v tabulce `76` nebo `77`. Pokud ne, viz [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Co tento dokument neřeší

- Aktivace I²C v Ubuntu — [INSTALLATION.md](INSTALLATION.md)
- Bosch BSEC knihovna — [BME690-BSEC.md](BME690-BSEC.md)
