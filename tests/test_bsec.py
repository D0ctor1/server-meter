from __future__ import annotations

import pytest

from server_meter.config import BsecConfig
from server_meter.sensor.bsec import (
    BSEC_E_CONFIG_FEATUREMISMATCH,
    BSEC_MAX_PROPERTY_BLOB_SIZE,
    BSEC_OUTPUT_BREATH_VOC_EQUIVALENT,
    BSEC_OUTPUT_CO2_EQUIVALENT,
    BSEC_OUTPUT_IAQ,
    BSEC_OUTPUT_TVOC_EQUIVALENT,
    BSEC_W_SU_SAMPLERATEMISMATCH,
    BsecOutput,
    BsecProcessor,
    _parse_outputs,
    bsec_status_ok,
    bsec_subscription_attempts,
    load_bsec_config_blob,
)


def test_bsec_warnings_are_not_errors():
    assert bsec_status_ok(0)
    assert bsec_status_ok(BSEC_W_SU_SAMPLERATEMISMATCH)
    assert bsec_status_ok(10)
    assert not bsec_status_ok(-1)
    assert not bsec_status_ok(-14)
    assert not bsec_status_ok(-33)


def test_tvoc_id_matches_bsec_3_3():
    assert BSEC_OUTPUT_TVOC_EQUIVALENT == 31
    assert BSEC_OUTPUT_BREATH_VOC_EQUIVALENT == 4
    assert BSEC_E_CONFIG_FEATUREMISMATCH == -35


def test_subscription_attempts_match_bsec_3_3_iaq_example():
    lp = bsec_subscription_attempts("lp")
    tvoc_without_bvoc = [
        attempt
        for attempt in lp
        if BSEC_OUTPUT_TVOC_EQUIVALENT in attempt and BSEC_OUTPUT_BREATH_VOC_EQUIVALENT not in attempt
    ]
    assert tvoc_without_bvoc, "Bosch 3.3 IAQ LP example subscribes TVOC without breath-VOC"
    assert BSEC_OUTPUT_IAQ in tvoc_without_bvoc[0]
    assert BSEC_OUTPUT_CO2_EQUIVALENT in tvoc_without_bvoc[0]
    ulp = bsec_subscription_attempts("ulp")
    assert all(BSEC_OUTPUT_TVOC_EQUIVALENT not in attempt for attempt in ulp)


def test_subscribe_keeps_tvoc_when_bvoc_is_rejected():
    processor = BsecProcessor(BsecConfig(sample_rate="lp"))
    calls: list[list[int]] = []

    def _fake(_lib, output_ids, _rate):
        ids = list(output_ids)
        calls.append(ids)
        if BSEC_OUTPUT_BREATH_VOC_EQUIVALENT in ids:
            return BSEC_E_CONFIG_FEATUREMISMATCH
        return 0

    processor._try_subscribe = _fake  # type: ignore[method-assign]
    processor._subscribe(lib=None)  # type: ignore[arg-type]
    assert calls, "subscription must be attempted"
    assert BSEC_OUTPUT_BREATH_VOC_EQUIVALENT in calls[0]
    assert BSEC_OUTPUT_TVOC_EQUIVALENT in processor.subscribed_ids
    assert BSEC_OUTPUT_BREATH_VOC_EQUIVALENT not in processor.subscribed_ids
    assert BSEC_OUTPUT_IAQ in processor.subscribed_ids
    assert BSEC_OUTPUT_CO2_EQUIVALENT in processor.subscribed_ids
    assert "tvoc_equivalent" in processor.subscribed_output_names
    assert "breath_voc_equivalent" not in processor.subscribed_output_names


def test_apply_bsec_copies_breath_voc_without_inventing_zero():
    from server_meter.models.measurement import Measurement
    from server_meter.sensor.bme690 import _apply_bsec
    from server_meter.sensor.bsec import BsecResult

    sample = Measurement(timestamp=1.0)
    _apply_bsec(
        sample,
        BsecResult(iaq=40.0, co2_equivalent=500.0, breath_voc_equivalent=0.42, breath_voc_accuracy=1),
    )
    assert sample.breath_voc_equivalent == 0.42
    assert sample.to_api_dict()["bvoc"] == 0.42

    empty = Measurement(timestamp=1.0)
    _apply_bsec(empty, BsecResult(iaq=40.0, breath_voc_equivalent=None))
    assert empty.breath_voc_equivalent is None
    assert empty.to_api_dict()["bvoc"] is None


def test_parse_outputs_maps_breath_voc_id_4():
    outputs = (BsecOutput * 3)()
    outputs[0].sensor_id = BSEC_OUTPUT_IAQ
    outputs[0].signal = 52.5
    outputs[0].accuracy = 2
    outputs[1].sensor_id = BSEC_OUTPUT_CO2_EQUIVALENT
    outputs[1].signal = 620.0
    outputs[1].accuracy = 2
    outputs[2].sensor_id = BSEC_OUTPUT_BREATH_VOC_EQUIVALENT
    outputs[2].signal = 0.42
    outputs[2].accuracy = 1
    result = _parse_outputs(outputs, 3)
    assert result.iaq == pytest.approx(52.5)
    assert result.co2_equivalent == pytest.approx(620.0)
    assert result.breath_voc_equivalent == pytest.approx(0.42)
    assert result.breath_voc_accuracy == 1
    assert result.tvoc_equivalent is None


def test_config_blob_strips_uint32_length_prefix():
    payload = bytes((i % 256) for i in range(BSEC_MAX_PROPERTY_BLOB_SIZE))
    blob = (len(payload)).to_bytes(4, "little") + payload
    assert len(blob) == 554
    assert load_bsec_config_blob(blob) == payload


def test_config_blob_passes_through_raw_property_string():
    raw = b"\x01\x02\x03\x00\x04"
    assert load_bsec_config_blob(raw) == raw
