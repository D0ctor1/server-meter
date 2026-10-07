from __future__ import annotations

from server_meter.sensor.bsec import (
    BSEC_MAX_PROPERTY_BLOB_SIZE,
    BSEC_OUTPUT_TVOC_EQUIVALENT,
    BSEC_W_SU_SAMPLERATEMISMATCH,
    bsec_status_ok,
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


def test_config_blob_strips_uint32_length_prefix():
    payload = bytes((i % 256) for i in range(BSEC_MAX_PROPERTY_BLOB_SIZE))
    blob = (len(payload)).to_bytes(4, "little") + payload
    assert len(blob) == 554
    assert load_bsec_config_blob(blob) == payload


def test_config_blob_passes_through_raw_property_string():
    raw = b"\x01\x02\x03\x00\x04"
    assert load_bsec_config_blob(raw) == raw
