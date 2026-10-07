"""Optional Bosch BSEC 3.x ctypes wrapper.

BSEC is proprietary. This project does not ship libalgobsec or Bosch config
blobs. When the operator installs BSEC 3.2.0.0+ (required for BME690), this
module loads the shared library, keeps algorithm state in RAM only, and never
calls bsec_get_state for disk persistence.

ctypes layout matches Bosch BSEC 3.x instance API used by BSEC 3.2/3.3:
bsec_get_instance_size, bsec_init, bsec_update_subscription,
bsec_sensor_control, bsec_do_steps, bsec_set_configuration, bsec_get_version.

If the library is absent, the BME690 driver continues with physical outputs
and leaves IAQ/eCO2/bVOC as null.
"""

from __future__ import annotations

import ctypes
import logging
import os
from ctypes import (
    POINTER,
    Structure,
    c_float,
    c_int64,
    c_size_t,
    c_uint8,
    c_uint16,
    c_uint32,
    c_void_p,
)
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from server_meter.config import BsecConfig
from server_meter.sensor.exceptions import BsecUnavailableError

if TYPE_CHECKING:
    from server_meter.sensor.bme690 import RawBme690Sample

logger = logging.getLogger("server_meter.bsec")

BSEC_MAX_PHYSICAL_SENSOR = 8
BSEC_MAX_WORKBUFFER_SIZE = 4096
BSEC_MAX_PROPERTY_BLOB_SIZE = 550
BSEC_NUMBER_OUTPUTS = 15
BSEC_SAMPLE_RATE_LP = 0.33333
BSEC_SAMPLE_RATE_ULP = 0.0033333
BSEC_OK = 0
# Bosch bsec_library_return_t: 0 success, >0 warning/info, <0 error.
BSEC_W_SU_SAMPLERATEMISMATCH = 14

BSEC_INPUT_PRESSURE = 1
BSEC_INPUT_HUMIDITY = 2
BSEC_INPUT_TEMPERATURE = 3
BSEC_INPUT_GASRESISTOR = 4
BSEC_INPUT_HEATSOURCE = 14
BSEC_INPUT_DISABLE_BASELINE_TRACKER = 23
BSEC_INPUT_PROFILE_PART = 24

BSEC_OUTPUT_IAQ = 1
BSEC_OUTPUT_STATIC_IAQ = 2
BSEC_OUTPUT_CO2_EQUIVALENT = 3
BSEC_OUTPUT_BREATH_VOC_EQUIVALENT = 4
BSEC_OUTPUT_RAW_TEMPERATURE = 6
BSEC_OUTPUT_RAW_PRESSURE = 7
BSEC_OUTPUT_RAW_HUMIDITY = 8
BSEC_OUTPUT_RAW_GAS = 9
BSEC_OUTPUT_STABILIZATION_STATUS = 12
BSEC_OUTPUT_RUN_IN_STATUS = 13
BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE = 14
BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY = 15
BSEC_OUTPUT_GAS_PERCENTAGE = 21
BSEC_OUTPUT_TVOC_EQUIVALENT = 31  # BSEC 3.3 bsec_virtual_sensor_t (not 32)

def bsec_status_ok(status: int) -> bool:
    """Bosch: 0 = success, positive = warning/info, negative = error."""
    return int(status) >= 0


def load_bsec_config_blob(data: bytes) -> bytes:
    """Bosch .config files are a uint32 LE length prefix plus the property blob."""
    if len(data) >= 4:
        declared = int.from_bytes(data[:4], "little")
        if 0 < declared <= BSEC_MAX_PROPERTY_BLOB_SIZE and declared + 4 <= len(data):
            return data[4 : 4 + declared]
    if len(data) > BSEC_MAX_PROPERTY_BLOB_SIZE:
        return data[:BSEC_MAX_PROPERTY_BLOB_SIZE]
    return data


BSEC_PROCESS_PRESSURE = 1 << (BSEC_INPUT_PRESSURE - 1)
BSEC_PROCESS_TEMPERATURE = 1 << (BSEC_INPUT_TEMPERATURE - 1)
BSEC_PROCESS_HUMIDITY = 1 << (BSEC_INPUT_HUMIDITY - 1)
BSEC_PROCESS_GAS = 1 << (BSEC_INPUT_GASRESISTOR - 1)
BSEC_PROCESS_PROFILE_PART = 1 << (BSEC_INPUT_PROFILE_PART - 1)


class BsecVersion(Structure):
    _fields_ = [
        ("major", c_uint8),
        ("minor", c_uint8),
        ("major_bugfix", c_uint8),
        ("minor_bugfix", c_uint8),
    ]


class BsecInput(Structure):
    _fields_ = [
        ("time_stamp", c_int64),
        ("signal", c_float),
        ("signal_dimensions", c_uint8),
        ("sensor_id", c_uint8),
    ]


class BsecOutput(Structure):
    _fields_ = [
        ("time_stamp", c_int64),
        ("signal", c_float),
        ("signal_dimensions", c_uint8),
        ("sensor_id", c_uint8),
        ("accuracy", c_uint8),
    ]


class BsecSensorConfiguration(Structure):
    _fields_ = [
        ("sample_rate", c_float),
        ("sensor_id", c_uint8),
    ]


class BsecBmeSettings(Structure):
    _fields_ = [
        ("next_call", c_int64),
        ("process_data", c_uint32),
        ("heater_temperature", c_uint16),
        ("heater_duration", c_uint16),
        ("heater_temperature_profile", c_uint16 * 10),
        ("heater_duration_profile", c_uint16 * 10),
        ("heater_profile_len", c_uint8),
        ("run_gas", c_uint8),
        ("pressure_oversampling", c_uint8),
        ("temperature_oversampling", c_uint8),
        ("humidity_oversampling", c_uint8),
        ("trigger_measurement", c_uint8),
        ("op_mode", c_uint8),
    ]


@dataclass(slots=True)
class BsecResult:
    iaq: float | None = None
    iaq_accuracy: int | None = None
    static_iaq: float | None = None
    static_iaq_accuracy: int | None = None
    co2_equivalent: float | None = None
    co2_accuracy: int | None = None
    breath_voc_equivalent: float | None = None
    breath_voc_accuracy: int | None = None
    gas_percentage: float | None = None
    gas_percentage_accuracy: int | None = None
    tvoc_equivalent: float | None = None
    tvoc_accuracy: int | None = None
    temperature: float | None = None
    humidity: float | None = None
    pressure_hpa: float | None = None
    gas_resistance: float | None = None
    raw_temperature: float | None = None
    raw_humidity: float | None = None
    raw_pressure: float | None = None
    stabilization_status: int | None = None
    run_in_status: int | None = None


def _candidate_library_paths(explicit: str) -> list[Path]:
    paths: list[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    env = os.environ.get("SERVER_METER_BSEC_LIB")
    if env:
        paths.append(Path(env).expanduser())
    paths.extend(
        [
            Path("/opt/server-meter/lib/libalgobsec.so"),
            Path("/usr/local/lib/libalgobsec.so"),
            Path("/usr/lib/libalgobsec.so"),
            Path("/opt/bosch/bsec/libalgobsec.so"),
        ]
    )
    return paths


class BsecProcessor:
    """Hold BSEC instance memory in RAM. Never serialize state to the SD card."""

    def __init__(self, config: BsecConfig) -> None:
        self._config = config
        self._lib = None
        self._instance = None
        self._available = False
        self._version: str | None = None
        self._temperature_offset = float(config.temperature_offset)

    @property
    def available(self) -> bool:
        return self._available

    @property
    def version(self) -> str | None:
        return self._version

    def open(self) -> None:
        lib = self._load_library()
        self._bind(lib)
        size = int(lib.bsec_get_instance_size())
        if size <= 0 or size > 2_000_000:
            raise BsecUnavailableError(f"unexpected BSEC instance size {size}")
        self._instance = (c_uint8 * size)()
        status = lib.bsec_init(self._instance)
        if not bsec_status_ok(status):
            raise BsecUnavailableError(f"bsec_init failed: {status}")
        version = BsecVersion()
        lib.bsec_get_version(self._instance, ctypes.byref(version))
        self._version = f"{version.major}.{version.minor}.{version.major_bugfix}.{version.minor_bugfix}"
        if version.major < 3 or (version.major == 3 and version.minor < 2):
            raise BsecUnavailableError(
                f"BME690 requires BSEC 3.2.0.0 or newer; found {self._version}"
            )
        self._maybe_set_configuration(lib)
        self._subscribe(lib)
        self._lib = lib
        self._available = True
        logger.info("BSEC %s initialized (state is RAM-only, not written to disk)", self._version)

    def close(self) -> None:
        # Dropping the instance buffer forgets calibration. Intentionally no disk save.
        self._available = False
        self._instance = None
        self._lib = None

    def process(self, sample: RawBme690Sample, unix_ts: float) -> BsecResult | None:
        if not self._available or self._lib is None or self._instance is None:
            return None
        time_ns = int(unix_ts * 1_000_000_000)
        inputs = (BsecInput * 8)()
        n = 0
        for sensor_id, value in (
            (BSEC_INPUT_TEMPERATURE, sample.temperature_c),
            (BSEC_INPUT_HUMIDITY, sample.humidity_rh),
            (BSEC_INPUT_PRESSURE, sample.pressure_pa),
            (BSEC_INPUT_GASRESISTOR, sample.gas_resistance_ohm),
            (BSEC_INPUT_HEATSOURCE, self._temperature_offset),
            (BSEC_INPUT_PROFILE_PART, float(sample.gas_index)),
        ):
            if sensor_id == BSEC_INPUT_GASRESISTOR and not sample.gas_valid:
                continue
            inputs[n].time_stamp = time_ns
            inputs[n].signal = float(value)
            inputs[n].signal_dimensions = 1
            inputs[n].sensor_id = sensor_id
            n += 1
        n_outputs = c_uint8(BSEC_NUMBER_OUTPUTS)
        outputs = (BsecOutput * BSEC_NUMBER_OUTPUTS)()
        status = self._lib.bsec_do_steps(
            self._instance, inputs, c_uint8(n), outputs, ctypes.byref(n_outputs)
        )
        if not bsec_status_ok(status):
            logger.warning("bsec_do_steps status=%s", status)
            return None
        return _parse_outputs(outputs, int(n_outputs.value))

    def _load_library(self) -> ctypes.CDLL:
        errors: list[str] = []
        for path in _candidate_library_paths(self._config.library_path):
            if not path.is_file():
                continue
            try:
                return ctypes.CDLL(str(path), mode=os.RTLD_NOW if hasattr(os, "RTLD_NOW") else 0)
            except OSError as exc:
                errors.append(f"{path}: {exc}")
        try:
            return ctypes.CDLL("libalgobsec.so")
        except OSError as exc:
            errors.append(str(exc))
        raise BsecUnavailableError(
            "Bosch BSEC shared library not found. Download BSEC 3.2.0.0+ from Bosch Sensortec, "
            "build/copy libalgobsec.so for Raspberry Pi 5 aarch64 (PiFour_Armv8), and set "
            "sensor.bsec.library_path. Details: " + "; ".join(errors[-3:])
        )

    def _bind(self, lib: ctypes.CDLL) -> None:
        lib.bsec_get_instance_size.restype = c_size_t
        lib.bsec_init.argtypes = [c_void_p]
        lib.bsec_init.restype = ctypes.c_int
        lib.bsec_get_version.argtypes = [c_void_p, POINTER(BsecVersion)]
        lib.bsec_get_version.restype = ctypes.c_int
        lib.bsec_update_subscription.argtypes = [
            c_void_p,
            POINTER(BsecSensorConfiguration),
            c_uint8,
            POINTER(BsecSensorConfiguration),
            POINTER(c_uint8),
        ]
        lib.bsec_update_subscription.restype = ctypes.c_int
        lib.bsec_do_steps.argtypes = [
            c_void_p,
            POINTER(BsecInput),
            c_uint8,
            POINTER(BsecOutput),
            POINTER(c_uint8),
        ]
        lib.bsec_do_steps.restype = ctypes.c_int
        lib.bsec_set_configuration.argtypes = [
            c_void_p,
            POINTER(c_uint8),
            c_uint32,
            POINTER(c_uint8),
            c_uint32,
        ]
        lib.bsec_set_configuration.restype = ctypes.c_int

    def _maybe_set_configuration(self, lib: ctypes.CDLL) -> None:
        blob_path = self._config.config_blob_path.strip()
        if not blob_path:
            return
        path = Path(blob_path).expanduser()
        if not path.is_file():
            logger.warning("BSEC config blob not found: %s (continuing with library defaults)", path)
            return
        data = load_bsec_config_blob(path.read_bytes())
        blob = (c_uint8 * len(data)).from_buffer_copy(data)
        work = (c_uint8 * BSEC_MAX_WORKBUFFER_SIZE)()
        status = lib.bsec_set_configuration(
            self._instance,
            blob,
            c_uint32(len(data)),
            work,
            c_uint32(BSEC_MAX_WORKBUFFER_SIZE),
        )
        if not bsec_status_ok(status):
            logger.warning("bsec_set_configuration failed: %s", status)
        else:
            if status > 0:
                logger.info("BSEC configuration blob applied from %s (%d bytes, warning %s)", path, len(data), status)
            else:
                logger.info("BSEC configuration blob applied from %s (%d bytes, read-only)", path, len(data))

    def _subscribe(self, lib: ctypes.CDLL) -> None:
        rate = BSEC_SAMPLE_RATE_ULP if self._config.sample_rate == "ulp" else BSEC_SAMPLE_RATE_LP
        output_ids = [
            BSEC_OUTPUT_IAQ,
            BSEC_OUTPUT_STATIC_IAQ,
            BSEC_OUTPUT_CO2_EQUIVALENT,
            BSEC_OUTPUT_RAW_TEMPERATURE,
            BSEC_OUTPUT_RAW_PRESSURE,
            BSEC_OUTPUT_RAW_HUMIDITY,
            BSEC_OUTPUT_RAW_GAS,
            BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE,
            BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY,
            BSEC_OUTPUT_STABILIZATION_STATUS,
            BSEC_OUTPUT_RUN_IN_STATUS,
            BSEC_OUTPUT_GAS_PERCENTAGE,
        ]
        # Breath-VOC is derived internally in some BSEC 3.x IAQ configs; subscribe last
        # and drop it if the library rejects the set.
        optional = [BSEC_OUTPUT_BREATH_VOC_EQUIVALENT]
        if self._config.sample_rate == "lp":
            optional.append(BSEC_OUTPUT_TVOC_EQUIVALENT)

        requested_ids = list(output_ids)
        status = self._try_subscribe(lib, requested_ids + optional, rate)
        if not bsec_status_ok(status):
            status = self._try_subscribe(lib, requested_ids, rate)
        if not bsec_status_ok(status):
            core = [
                BSEC_OUTPUT_IAQ,
                BSEC_OUTPUT_STATIC_IAQ,
                BSEC_OUTPUT_CO2_EQUIVALENT,
                BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE,
                BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY,
                BSEC_OUTPUT_STABILIZATION_STATUS,
                BSEC_OUTPUT_RUN_IN_STATUS,
            ]
            status = self._try_subscribe(lib, core, rate)
        if not bsec_status_ok(status):
            raise BsecUnavailableError(f"bsec_update_subscription failed: {status}")
        if status > 0:
            logger.info("bsec_update_subscription warning %s (outputs still subscribed)", status)

    def _try_subscribe(self, lib: ctypes.CDLL, output_ids: list[int], rate: float) -> int:
        n = len(output_ids)
        requested = (BsecSensorConfiguration * n)()
        for i, sensor_id in enumerate(output_ids):
            requested[i].sample_rate = rate
            requested[i].sensor_id = sensor_id
        required = (BsecSensorConfiguration * BSEC_MAX_PHYSICAL_SENSOR)()
        n_required = c_uint8(BSEC_MAX_PHYSICAL_SENSOR)
        return int(
            lib.bsec_update_subscription(
                self._instance, requested, c_uint8(n), required, ctypes.byref(n_required)
            )
        )


def _parse_outputs(outputs: ctypes.Array[BsecOutput], count: int) -> BsecResult:
    result = BsecResult()
    for i in range(count):
        item = outputs[i]
        sid = int(item.sensor_id)
        value = float(item.signal)
        acc = int(item.accuracy)
        if sid == BSEC_OUTPUT_IAQ:
            result.iaq = value
            result.iaq_accuracy = acc
        elif sid == BSEC_OUTPUT_STATIC_IAQ:
            result.static_iaq = value
            result.static_iaq_accuracy = acc
        elif sid == BSEC_OUTPUT_CO2_EQUIVALENT:
            result.co2_equivalent = value
            result.co2_accuracy = acc
        elif sid == BSEC_OUTPUT_BREATH_VOC_EQUIVALENT:
            result.breath_voc_equivalent = value
            result.breath_voc_accuracy = acc
        elif sid == BSEC_OUTPUT_RAW_TEMPERATURE:
            result.raw_temperature = value
        elif sid == BSEC_OUTPUT_RAW_PRESSURE:
            result.raw_pressure = value / 100.0
        elif sid == BSEC_OUTPUT_RAW_HUMIDITY:
            result.raw_humidity = value
        elif sid == BSEC_OUTPUT_RAW_GAS:
            result.gas_resistance = value
        elif sid == BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_TEMPERATURE:
            result.temperature = value
        elif sid == BSEC_OUTPUT_SENSOR_HEAT_COMPENSATED_HUMIDITY:
            result.humidity = value
        elif sid == BSEC_OUTPUT_GAS_PERCENTAGE:
            result.gas_percentage = value
            result.gas_percentage_accuracy = acc
        elif sid == BSEC_OUTPUT_TVOC_EQUIVALENT:
            result.tvoc_equivalent = value
            result.tvoc_accuracy = acc
        elif sid == BSEC_OUTPUT_STABILIZATION_STATUS:
            result.stabilization_status = int(round(value))
        elif sid == BSEC_OUTPUT_RUN_IN_STATUS:
            result.run_in_status = int(round(value))
    return result
