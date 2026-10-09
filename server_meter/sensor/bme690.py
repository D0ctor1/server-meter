"""BME690 I²C driver.

Compensation formulas are a Python port of Bosch Sensortec BME690 SensorAPI
v1.1.0 (BSD-3-Clause), not the older BME680/BME688 integer formulas.

Copyright (c) 2025 Bosch Sensortec GmbH — original C implementation.
https://github.com/boschsensortec/BME690_SensorAPI

Physical outputs: temperature °C, pressure Pa (converted to hPa by the
normalizer), humidity %RH, gas resistance Ohm.

IAQ / eCO2 / bVOC are produced only when BSEC 3.x is loaded. This module
never persists samples or BSEC state to disk.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from server_meter.config import SensorConfig
from server_meter.models.measurement import Measurement, SensorStatus
from server_meter.sensor.base import SensorDriver
from server_meter.sensor.bsec import BsecProcessor, BsecResult
from server_meter.sensor.exceptions import SensorProtocolError, SensorUnavailableError
from server_meter.sensor.i2c_bus import I2CBus

logger = logging.getLogger("server_meter.bme690")

BME69X_CHIP_ID = 0x61
BME69X_REG_FIELD0 = 0x1D
BME69X_REG_IDAC_HEAT0 = 0x50
BME69X_REG_RES_HEAT0 = 0x5A
BME69X_REG_GAS_WAIT0 = 0x64
BME69X_REG_CTRL_GAS_0 = 0x70
BME69X_REG_CTRL_GAS_1 = 0x71
BME69X_REG_CTRL_HUM = 0x72
BME69X_REG_CTRL_MEAS = 0x74
BME69X_REG_CONFIG = 0x75
BME69X_REG_UNIQUE_ID = 0x83
BME69X_REG_COEFF1 = 0x8A
BME69X_REG_CHIP_ID = 0xD0
BME69X_REG_SOFT_RESET = 0xE0
BME69X_REG_COEFF2 = 0xE1
BME69X_REG_VARIANT_ID = 0xF0
BME69X_REG_COEFF3 = 0x00
BME69X_SOFT_RESET_CMD = 0xB6
BME69X_LEN_COEFF1 = 23
BME69X_LEN_COEFF2 = 14
BME69X_LEN_COEFF3 = 5
BME69X_LEN_FIELD = 17
BME69X_NEW_DATA_MSK = 0x80
BME69X_GAS_INDEX_MSK = 0x0F
BME69X_GAS_RANGE_MSK = 0x0F
BME69X_GASM_VALID_MSK = 0x20
BME69X_HEAT_STAB_MSK = 0x10
BME69X_RHRANGE_MSK = 0x30
BME69X_RSERROR_MSK = 0xF0
BME69X_FORCED_MODE = 0x01
BME69X_SLEEP_MODE = 0x00
BME690_VARIANT_GAS_HIGH = 0x02

# Oversampling register encodings from SensorAPI
_OS_MAP = {0: 0, 1: 1, 2: 2, 4: 3, 8: 4, 16: 5}


@dataclass(slots=True)
class Bme69xCalib:
    par_h1: int = 0
    par_h2: int = 0
    par_h3: int = 0
    par_h4: int = 0
    par_h5: int = 0
    par_h6: int = 0
    par_g1: int = 0
    par_g2: int = 0
    par_g3: int = 0
    par_t1: int = 0
    par_t2: int = 0
    par_t3: int = 0
    par_p1: int = 0
    par_p2: int = 0
    par_p3: int = 0
    par_p4: int = 0
    par_p5: int = 0
    par_p6: int = 0
    par_p7: int = 0
    par_p8: int = 0
    par_p9: int = 0
    par_p10: int = 0
    par_p11: int = 0
    res_heat_range: int = 0
    res_heat_val: int = 0
    range_sw_err: int = 0


@dataclass(slots=True)
class RawBme690Sample:
    temperature_c: float
    pressure_pa: float
    humidity_rh: float
    gas_resistance_ohm: float
    status: int
    gas_index: int
    heat_stable: bool
    gas_valid: bool


def _concat_u16(msb: int, lsb: int) -> int:
    return ((msb & 0xFF) << 8) | (lsb & 0xFF)


def _to_int8(value: int) -> int:
    value &= 0xFF
    return value - 256 if value > 127 else value


def _to_int16(value: int) -> int:
    value &= 0xFFFF
    return value - 65536 if value > 32767 else value


def parse_calib(coeff: bytes) -> Bme69xCalib:
    """Parse the 42-byte coefficient block (SensorAPI get_calib_data)."""
    if len(coeff) < 42:
        raise SensorProtocolError("incomplete BME690 calibration block")
    calib = Bme69xCalib()
    calib.par_t1 = _concat_u16(coeff[32], coeff[31])
    calib.par_t2 = _concat_u16(coeff[1], coeff[0])
    calib.par_t3 = _to_int8(coeff[2])
    calib.par_p5 = _to_int16(_concat_u16(coeff[5], coeff[4]))
    calib.par_p6 = _to_int16(_concat_u16(coeff[7], coeff[6]))
    calib.par_p7 = _to_int8(coeff[8])
    calib.par_p8 = _to_int8(coeff[9])
    calib.par_p1 = _to_int16(_concat_u16(coeff[11], coeff[10]))
    calib.par_p2 = _concat_u16(coeff[13], coeff[12])
    calib.par_p3 = _to_int8(coeff[14])
    calib.par_p4 = _to_int8(coeff[15])
    calib.par_p9 = _to_int16(_concat_u16(coeff[19], coeff[18]))
    calib.par_p10 = _to_int8(coeff[20])
    calib.par_p11 = _to_int8(coeff[21])
    par_h5 = (coeff[23] << 4) | (coeff[24] >> 4)
    if par_h5 > 2047:
        par_h5 -= 4096
    calib.par_h5 = par_h5
    par_h1 = (coeff[25] << 4) | (coeff[24] & 0x0F)
    if par_h1 > 2047:
        par_h1 -= 4096
    calib.par_h1 = par_h1
    calib.par_h2 = _to_int8(coeff[26])
    calib.par_h4 = _to_int8(coeff[27])
    calib.par_h3 = coeff[28]
    calib.par_h6 = coeff[29]
    calib.par_g1 = _to_int8(coeff[35])
    calib.par_g2 = _to_int16(_concat_u16(coeff[34], coeff[33]))
    calib.par_g3 = _to_int8(coeff[36])
    calib.res_heat_range = (coeff[39] & BME69X_RHRANGE_MSK) >> 4
    calib.res_heat_val = _to_int8(coeff[37])
    calib.range_sw_err = _to_int8(coeff[41] & BME69X_RSERROR_MSK) // 16
    return calib


def calc_temperature(temp_adc: int, calib: Bme69xCalib) -> float:
    do1 = calib.par_t1 << 8
    dtk1 = calib.par_t2 / float(1 << 30)
    dtk2 = calib.par_t3 / float(1 << 48)
    cf = float(temp_adc) - float(do1)
    return float(cf * dtk1 + cf * cf * dtk2)


def calc_pressure(pres_adc: int, temperature_c: float, calib: Bme69xCalib) -> float:
    o = calib.par_p1 * (1 << 3)
    tk10 = calib.par_p2 / float(1 << 6)
    tk20 = calib.par_p3 / float(1 << 8)
    tk30 = calib.par_p4 / float(1 << 15)
    s = (calib.par_p5 - float(1 << 14)) / float(1 << 20)
    tk1s = (calib.par_p6 - float(1 << 14)) / float(1 << 29)
    tk2s = calib.par_p7 / float(1 << 32)
    tk3s = calib.par_p8 / float(1 << 37)
    nls = calib.par_p9 / float(1 << 48)
    tknls = calib.par_p10 / float(1 << 48)
    nls3 = calib.par_p11 / (float(1 << 35) * float(1 << 30))
    t = temperature_c
    tmp1 = o + (tk10 * t) + (tk20 * t * t) + (tk30 * t * t * t)
    tmp2 = pres_adc * (s + (tk1s * t) + (tk2s * t * t) + (tk3s * t * t * t))
    tmp3 = pres_adc * pres_adc * (nls + (tknls * t))
    tmp4 = pres_adc * pres_adc * pres_adc * nls3
    return float(tmp1 + tmp2 + tmp3 + tmp4)


def calc_humidity(hum_adc: int, temperature_c: float, calib: Bme69xCalib) -> float:
    temp_comp = (temperature_c * 5120.0) - 76800.0
    oh = calib.par_h1 * float(1 << 6)
    sh = calib.par_h5 / float(1 << 16)
    tk10h = calib.par_h2 / float(1 << 14)
    tk1sh = calib.par_h4 / float(1 << 26)
    tk2sh = calib.par_h3 / float(1 << 26)
    hlin2 = calib.par_h6 / float(1 << 19)
    hoff = hum_adc - (oh + tk10h * temp_comp)
    hsens = hoff * sh * (1.0 + (tk1sh * temp_comp) + (tk1sh * tk2sh * temp_comp * temp_comp))
    hum = hsens * (1.0 - hlin2 * hsens)
    return float(min(100.0, max(0.0, hum)))


def calc_gas_resistance(gas_res_adc: int, gas_range: int) -> float:
    var1 = 262144 >> gas_range
    var2 = (int(gas_res_adc) - 512) * 3
    var2 = 4096 + var2
    if var2 == 0:
        return 0.0
    return 1_000_000.0 * float(var1) / float(var2)


def calc_res_heat(temp_c: int, calib: Bme69xCalib, amb_temp_c: float = 25.0) -> int:
    temp = min(int(temp_c), 400)
    var1 = (calib.par_g1 / 16.0) + 49.0
    var2 = ((calib.par_g2 / 32768.0) * 0.0005) + 0.00235
    var3 = calib.par_g3 / 1024.0
    var4 = var1 * (1.0 + (var2 * temp))
    var5 = var4 + (var3 * amb_temp_c)
    res_heat = 3.4 * (
        (var5 * (4.0 / (4.0 + calib.res_heat_range)) * (1.0 / (1.0 + (calib.res_heat_val * 0.002)))) - 25.0
    )
    return int(res_heat) & 0xFF


def calc_gas_wait(duration_ms: int) -> int:
    dur = int(duration_ms)
    if dur >= 0xFC0:
        return 0xFF
    factor = 0
    while dur > 0x3F:
        dur //= 4
        factor += 1
    return (dur + (factor * 64)) & 0xFF


def decode_field(buff: bytes, calib: Bme69xCalib) -> RawBme690Sample | None:
    if len(buff) < BME69X_LEN_FIELD:
        return None
    status = buff[0] & BME69X_NEW_DATA_MSK
    if not status:
        return None
    adc_pres = (buff[2] << 16) | (buff[3] << 8) | buff[4]
    adc_temp = (buff[5] << 16) | (buff[6] << 8) | buff[7]
    adc_hum = (buff[8] << 8) | buff[9]
    adc_gas_res = (buff[15] << 2) | (buff[16] >> 6)
    gas_range = buff[16] & BME69X_GAS_RANGE_MSK
    gas_valid = bool(buff[16] & BME69X_GASM_VALID_MSK)
    heat_stable = bool(buff[16] & BME69X_HEAT_STAB_MSK)
    temperature = calc_temperature(adc_temp, calib)
    pressure = calc_pressure(adc_pres, temperature, calib)
    humidity = calc_humidity(adc_hum, temperature, calib)
    gas = calc_gas_resistance(adc_gas_res, gas_range)
    return RawBme690Sample(
        temperature_c=temperature,
        pressure_pa=pressure,
        humidity_rh=humidity,
        gas_resistance_ohm=gas,
        status=status | (buff[16] & (BME69X_GASM_VALID_MSK | BME69X_HEAT_STAB_MSK)),
        gas_index=buff[0] & BME69X_GAS_INDEX_MSK,
        heat_stable=heat_stable,
        gas_valid=gas_valid,
    )


def _os_bits(oversample: int) -> int:
    return _OS_MAP.get(int(oversample), 3)


class Bme690Driver(SensorDriver):
    name = "bme690"

    def __init__(self, config: SensorConfig) -> None:
        self._config = config
        self._bus = I2CBus(config.i2c.bus, config.i2c.address, config.i2c_timeout_seconds)
        self._calib: Bme69xCalib | None = None
        self._amb_temp = 25.0
        self._variant_id = 0
        self._bsec: BsecProcessor | None = None
        self._opened = False
        self._bsec_logged_missing = False

    def open(self) -> None:
        self._bus.open()
        try:
            self._soft_reset()
            chip_id = self._bus.read_u8(BME69X_REG_CHIP_ID)
            if chip_id != BME69X_CHIP_ID:
                raise SensorProtocolError(
                    f"Unexpected chip ID 0x{chip_id:02x} at 0x{self._config.i2c.address:02x} "
                    f"(BME690 is 0x{BME69X_CHIP_ID:02x})"
                )
            self._variant_id = self._bus.read_u8(BME69X_REG_VARIANT_ID)
            self._calib = self._read_calib()
            self._configure_forced_defaults()
            self._opened = True
            logger.info(
                "BME690 detected chip_id=0x%02x variant=0x%02x i2c=0x%02x bus=%d",
                chip_id,
                self._variant_id,
                self._config.i2c.address,
                self._config.i2c.bus,
            )
            self._init_bsec()
        except Exception:
            self._bus.close()
            self._opened = False
            raise

    def close(self) -> None:
        if self._bsec is not None:
            self._bsec.close()
            self._bsec = None
        try:
            if self._opened:
                self._bus.write_u8(BME69X_REG_CTRL_MEAS, BME69X_SLEEP_MODE)
        except SensorUnavailableError:
            pass
        self._bus.close()
        self._opened = False

    def describe(self) -> dict[str, object]:
        return {
            "driver": self.name,
            "chip": "BME690",
            "chip_id": hex(BME69X_CHIP_ID),
            "variant_id": hex(self._variant_id),
            "i2c_bus": self._config.i2c.bus,
            "i2c_address": hex(self._config.i2c.address),
            "bsec_loaded": bool(self._bsec and self._bsec.available),
            "bsec_version": self._bsec.version if self._bsec else None,
            "bsec_subscribed_outputs": (
                self._bsec.subscribed_output_names if self._bsec and self._bsec.available else []
            ),
            "opened": self._opened,
        }

    def read(self) -> Measurement:
        if not self._opened or self._calib is None:
            raise SensorUnavailableError("BME690 is not initialized")
        raw = self._forced_measurement()
        self._amb_temp = raw.temperature_c
        ts = time.time()
        measurement = Measurement(
            timestamp=ts,
            temperature=raw.temperature_c,
            pressure=raw.pressure_pa / 100.0,
            humidity=raw.humidity_rh,
            gas_resistance=raw.gas_resistance_ohm,
            raw_temperature=raw.temperature_c,
            raw_humidity=raw.humidity_rh,
            raw_pressure=raw.pressure_pa / 100.0,
            sensor_status=SensorStatus.OK,
        )
        if self._bsec is not None and self._bsec.available:
            processed = self._bsec.process(raw, ts)
            if processed is not None:
                _apply_bsec(measurement, processed)
        return measurement

    def _init_bsec(self) -> None:
        if not self._config.bsec.enabled:
            logger.info("BSEC disabled in configuration; exposing physical BME690 outputs only")
            return
        processor = BsecProcessor(self._config.bsec)
        try:
            processor.open()
        except Exception as exc:
            if not self._bsec_logged_missing:
                logger.warning(
                    "BSEC 3.x not available (%s). Physical BME690 values will still be published; "
                    "IAQ/eCO2/bVOC remain null until Bosch BSEC is installed. See docs/bme690-bsec.md",
                    exc,
                )
                self._bsec_logged_missing = True
            processor.close()
            self._bsec = None
            return
        self._bsec = processor

    def _soft_reset(self) -> None:
        self._bus.write_u8(BME69X_REG_SOFT_RESET, BME69X_SOFT_RESET_CMD)
        time.sleep(0.01)

    def _read_calib(self) -> Bme69xCalib:
        coeff = bytearray(42)
        coeff[0:BME69X_LEN_COEFF1] = self._bus.read_bytes(BME69X_REG_COEFF1, BME69X_LEN_COEFF1)
        coeff[BME69X_LEN_COEFF1 : BME69X_LEN_COEFF1 + BME69X_LEN_COEFF2] = self._bus.read_bytes(
            BME69X_REG_COEFF2, BME69X_LEN_COEFF2
        )
        coeff[BME69X_LEN_COEFF1 + BME69X_LEN_COEFF2 :] = self._bus.read_bytes(BME69X_REG_COEFF3, BME69X_LEN_COEFF3)
        return parse_calib(bytes(coeff))

    def _configure_forced_defaults(self) -> None:
        os_hum = _os_bits(1)
        os_temp = _os_bits(2)
        os_pres = _os_bits(16)
        filt = 1
        ctrl_hum = os_hum & 0x07
        self._bus.write_u8(BME69X_REG_CTRL_HUM, ctrl_hum)
        config = (filt << 2) & 0x1C
        self._bus.write_u8(BME69X_REG_CONFIG, config)
        if self._calib is None:
            return
        self._bus.write_u8(
            BME69X_REG_RES_HEAT0,
            calc_res_heat(self._config.heater_temperature_c, self._calib, self._amb_temp),
        )
        self._bus.write_u8(BME69X_REG_GAS_WAIT0, calc_gas_wait(self._config.heater_duration_ms))
        # run_gas enable, nb_conv = 0 (profile 0)
        self._bus.write_u8(BME69X_REG_CTRL_GAS_1, 0x20)
        ctrl_meas = ((os_temp & 0x07) << 5) | ((os_pres & 0x07) << 2) | BME69X_SLEEP_MODE
        self._bus.write_u8(BME69X_REG_CTRL_MEAS, ctrl_meas)

    def _forced_measurement(self) -> RawBme690Sample:
        os_temp = _os_bits(2)
        os_pres = _os_bits(16)
        ctrl_meas = ((os_temp & 0x07) << 5) | ((os_pres & 0x07) << 2) | BME69X_FORCED_MODE
        self._bus.write_u8(BME69X_REG_CTRL_MEAS, ctrl_meas)
        wait_s = 0.05 + (self._config.heater_duration_ms / 1000.0) + 0.12
        deadline = time.monotonic() + min(max(wait_s, 0.15), 2.5)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            time.sleep(0.02)
            try:
                field = self._bus.read_bytes(BME69X_REG_FIELD0, BME69X_LEN_FIELD)
                sample = decode_field(field, self._calib)  # type: ignore[arg-type]
            except SensorUnavailableError as exc:
                last_error = exc
                continue
            if sample is not None:
                return sample
        if last_error is not None:
            raise last_error
        raise SensorUnavailableError("BME690 measurement timed out (no new data)")


def _apply_bsec(measurement: Measurement, bsec: BsecResult) -> None:
    if bsec.temperature is not None:
        measurement.temperature = bsec.temperature
    if bsec.humidity is not None:
        measurement.humidity = bsec.humidity
    if bsec.pressure_hpa is not None:
        measurement.pressure = bsec.pressure_hpa
    if bsec.gas_resistance is not None:
        measurement.gas_resistance = bsec.gas_resistance
    measurement.iaq = bsec.iaq
    measurement.iaq_accuracy = bsec.iaq_accuracy
    measurement.static_iaq = bsec.static_iaq
    measurement.static_iaq_accuracy = bsec.static_iaq_accuracy
    measurement.co2_equivalent = bsec.co2_equivalent
    measurement.co2_accuracy = bsec.co2_accuracy
    measurement.breath_voc_equivalent = bsec.breath_voc_equivalent
    measurement.breath_voc_accuracy = bsec.breath_voc_accuracy
    measurement.gas_percentage = bsec.gas_percentage
    measurement.gas_percentage_accuracy = bsec.gas_percentage_accuracy
    measurement.tvoc_equivalent = bsec.tvoc_equivalent
    measurement.tvoc_accuracy = bsec.tvoc_accuracy
    measurement.raw_temperature = bsec.raw_temperature if bsec.raw_temperature is not None else measurement.raw_temperature
    measurement.raw_humidity = bsec.raw_humidity if bsec.raw_humidity is not None else measurement.raw_humidity
    measurement.raw_pressure = bsec.raw_pressure if bsec.raw_pressure is not None else measurement.raw_pressure
    measurement.stabilization_status = bsec.stabilization_status
    measurement.run_in_status = bsec.run_in_status
