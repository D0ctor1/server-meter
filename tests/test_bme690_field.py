from __future__ import annotations

from server_meter.sensor.bme690 import BME69X_NEW_DATA_MSK, Bme69xCalib, decode_field


def test_decode_field_requires_new_data_bit():
    calib = Bme69xCalib(par_t1=1, par_t2=1, par_p1=1, par_p5=1)
    buff = bytes(17)
    assert decode_field(buff, calib) is None
    data = bytearray(17)
    data[0] = BME69X_NEW_DATA_MSK
    sample = decode_field(bytes(data), calib)
    assert sample is not None
    assert isinstance(sample.temperature_c, float)
    assert isinstance(sample.pressure_pa, float)
