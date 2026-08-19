"""Tests for analog & sensor front-end calculators."""

from __future__ import annotations

import pytest

from zaptrace.synthesis.analog import (
    adc_code_for_voltage,
    adc_lsb_voltage,
    adc_source_impedance_check,
    anti_alias_filter,
    inverting_feedback_for_gain,
    inverting_gain,
    noninverting_feedback_for_gain,
    noninverting_gain,
    opamp_closed_loop_bandwidth,
    opamp_min_gbw,
)


def test_noninverting_gain() -> None:
    assert noninverting_gain(9000.0, 1000.0) == pytest.approx(10.0)
    assert noninverting_gain(0.0, 1000.0) == pytest.approx(1.0)  # buffer


def test_inverting_gain() -> None:
    assert inverting_gain(10000.0, 1000.0) == pytest.approx(-10.0)


def test_noninverting_feedback_for_gain() -> None:
    assert noninverting_feedback_for_gain(10.0, 1000.0) == 9100.0  # (10-1)*1000=9000 -> E24 9.1k
    assert noninverting_feedback_for_gain(1.0, 1000.0) == 0.0  # unity buffer


def test_inverting_feedback_for_gain() -> None:
    assert inverting_feedback_for_gain(10.0, 1000.0) == 10000.0  # 10*1000 -> 10k


def test_adc_lsb_voltage() -> None:
    assert adc_lsb_voltage(3.3, 12) == pytest.approx(3.3 / 4096)


def test_adc_code_for_voltage_clamps() -> None:
    assert adc_code_for_voltage(0.0, 3.3, 12) == 0
    assert adc_code_for_voltage(1.65, 3.3, 12) == 2048
    assert adc_code_for_voltage(10.0, 3.3, 12) == 4095  # over-range clamps to max


def test_adc_code_for_voltage_clamps_negative_input_to_zero() -> None:
    assert adc_code_for_voltage(-0.1, 3.3, 12) == 0


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        noninverting_gain(9000.0, 0.0)
    with pytest.raises(ValueError):
        noninverting_feedback_for_gain(0.5, 1000.0)  # gain < 1
    with pytest.raises(ValueError):
        adc_lsb_voltage(3.3, 0)


class TestOpAmpBandwidth:
    def test_closed_loop_bandwidth(self) -> None:
        # 10 MHz GBW at gain 10 -> 1 MHz closed-loop BW
        bw = opamp_closed_loop_bandwidth(10e6, 10.0)
        assert bw == pytest.approx(1e6, rel=1e-4)

    def test_unity_gain_bandwidth_equals_gbw(self) -> None:
        assert opamp_closed_loop_bandwidth(10e6, 1.0) == pytest.approx(10e6)

    def test_min_gbw(self) -> None:
        # Need 1 MHz at gain 10, margin 3x -> 30 MHz GBW
        gbw = opamp_min_gbw(1e6, 10.0, margin=3.0)
        assert gbw == pytest.approx(30e6, rel=1e-4)

    def test_invalid_gbw(self) -> None:
        with pytest.raises(ValueError):
            opamp_closed_loop_bandwidth(0.0, 10.0)


class TestAntiAliasFilter:
    def test_nyquist_half_sample_rate(self) -> None:
        result = anti_alias_filter(44100.0)
        # fc should be around sample_rate/4 = 11025 Hz
        assert result.cutoff_hz == pytest.approx(11025, rel=0.2)
        assert result.filter_order >= 1

    def test_attenuation_increases_with_lower_cutoff(self) -> None:
        # Lower cutoff -> more attenuation at Nyquist
        tight = anti_alias_filter(10000.0, signal_bandwidth_hz=1000.0)
        loose = anti_alias_filter(10000.0, signal_bandwidth_hz=4000.0)
        assert tight.attenuation_db_at_nyquist > loose.attenuation_db_at_nyquist

    def test_invalid_bandwidth(self) -> None:
        with pytest.raises(ValueError):
            anti_alias_filter(10000.0, signal_bandwidth_hz=6000.0)  # > Nyquist

    def test_returns_dataclass(self) -> None:
        result = anti_alias_filter(100e3)
        assert result.r_ohms > 0
        assert result.c_farads == pytest.approx(100e-9)


class TestAdcSourceImpedance:
    def test_low_impedance_passes(self) -> None:
        # 100 Ω source, 10 pF input cap, 1 MSPS 12-bit ADC
        result = adc_source_impedance_check(100.0, 10.0, 1e6, 12)
        assert result.ok

    def test_high_impedance_fails(self) -> None:
        # 100 kΩ source, 20 pF input cap, 1 MSPS 12-bit ADC -> too slow to settle
        result = adc_source_impedance_check(100_000.0, 20.0, 1e6, 12)
        assert not result.ok

    def test_max_source_ohms_is_positive(self) -> None:
        result = adc_source_impedance_check(1000.0, 10.0, 1e6, 12)
        assert result.max_source_ohms > 0

    def test_invalid_capacitance(self) -> None:
        with pytest.raises(ValueError):
            adc_source_impedance_check(1000.0, 0.0, 1e6, 12)
