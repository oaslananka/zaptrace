"""Tests for RF / wireless design calculators."""

from __future__ import annotations

import pytest

from zaptrace.synthesis.rf import (
    antenna_keepout,
    free_space_path_loss_db,
    get_rf_module,
    l_network_matching,
    link_margin_db,
    list_rf_modules,
    microstrip_50ohm_width_mm,
    quarter_wave_mm,
    wavelength_mm,
)


def test_wavelength_free_space() -> None:
    assert wavelength_mm(2.4e9) == pytest.approx(124.91, abs=0.1)  # 2.4 GHz ~ 12.5 cm
    assert wavelength_mm(915e6) == pytest.approx(327.6, abs=0.5)


def test_wavelength_in_dielectric_is_shorter() -> None:
    assert wavelength_mm(2.4e9, eff_dielectric=4.0) == pytest.approx(124.91 / 2, abs=0.1)


def test_quarter_wave() -> None:
    assert quarter_wave_mm(2.4e9) == pytest.approx(124.91 / 4, abs=0.05)


def test_free_space_path_loss() -> None:
    fspl_1m = free_space_path_loss_db(2.4e9, 1.0)
    assert fspl_1m == pytest.approx(40.05, abs=0.1)  # ~40 dB at 1 m, 2.4 GHz
    # +20 dB per decade of distance
    assert free_space_path_loss_db(2.4e9, 10.0) == pytest.approx(fspl_1m + 20.0, abs=0.01)


def test_link_margin() -> None:
    margin = link_margin_db(
        tx_power_dbm=10.0, tx_gain_dbi=2.0, rx_gain_dbi=2.0, path_loss_db=40.05, rx_sensitivity_dbm=-90.0
    )
    assert margin == pytest.approx(63.95, abs=0.05)


def test_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        wavelength_mm(0.0)
    with pytest.raises(ValueError):
        wavelength_mm(2.4e9, eff_dielectric=0.5)
    with pytest.raises(ValueError):
        free_space_path_loss_db(2.4e9, 0.0)


class TestAntennaKeepout:
    def test_2_4ghz_keepout(self) -> None:
        ko = antenna_keepout(2.4e9)
        assert ko.wavelength_mm == pytest.approx(124.91, abs=0.5)
        assert ko.min_keepout_mm == pytest.approx(12.5, abs=0.5)
        assert ko.recommended_keepout_mm == pytest.approx(31.2, abs=0.5)

    def test_higher_freq_smaller_keepout(self) -> None:
        ko_24 = antenna_keepout(2.4e9)
        ko_5 = antenna_keepout(5.0e9)
        assert ko_5.recommended_keepout_mm < ko_24.recommended_keepout_mm

    def test_serializable(self) -> None:
        ko = antenna_keepout(2.4e9)
        d = ko.to_dict()
        assert "min_keepout_mm" in d


class TestLNetworkMatching:
    def test_50_to_25_low_pass(self) -> None:
        result = l_network_matching(50.0, 25.0, 2.4e9)
        assert result.topology == "low-pass"
        assert result.q_factor == pytest.approx(1.0, rel=0.01)

    def test_high_pass_topology(self) -> None:
        result = l_network_matching(50.0, 25.0, 2.4e9, topology="high-pass")
        assert result.topology == "high-pass"

    def test_swapped_source_load(self) -> None:
        r1 = l_network_matching(50.0, 25.0, 2.4e9)
        r2 = l_network_matching(25.0, 50.0, 2.4e9)
        assert r1.q_factor == pytest.approx(r2.q_factor, rel=1e-3)

    def test_invalid_topology(self) -> None:
        with pytest.raises(ValueError):
            l_network_matching(50.0, 25.0, 2.4e9, topology="bandpass")

    def test_serializable(self) -> None:
        d = l_network_matching(50.0, 25.0, 2.4e9).to_dict()
        assert "q_factor" in d


class TestMicrostrip50Ohm:
    def test_fr4_0_2mm_substrate(self) -> None:
        w = microstrip_50ohm_width_mm(0.2, er=4.3)
        assert 0.3 < w < 0.7  # typical range for 0.2mm FR-4

    def test_thicker_substrate_gives_wider_trace(self) -> None:
        w_thin = microstrip_50ohm_width_mm(0.1, er=4.3)
        w_thick = microstrip_50ohm_width_mm(0.2, er=4.3)
        assert w_thick > w_thin

    def test_higher_er_gives_narrower_trace(self) -> None:
        w_fr4 = microstrip_50ohm_width_mm(0.2, er=4.3)
        w_rogers = microstrip_50ohm_width_mm(0.2, er=10.0)
        assert w_rogers < w_fr4


class TestRfModuleRef:
    def test_list_modules_non_empty(self) -> None:
        modules = list_rf_modules()
        assert len(modules) >= 4

    def test_get_module_by_id(self) -> None:
        m = get_rf_module("ESP32-WROOM-32")
        assert "FCC" in m.certifications
        assert "2.4 GHz" in m.freq_bands

    def test_get_unknown_module_raises(self) -> None:
        with pytest.raises(ValueError):
            get_rf_module("UNKNOWN-MODULE-XYZ")

    def test_module_serializable(self) -> None:
        d = get_rf_module("nRF52840-DK").to_dict()
        assert "certifications" in d
        assert "protocols" in d
