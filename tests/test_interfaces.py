"""Tests for high-speed interface SI profiles."""

from __future__ import annotations

import pytest

from zaptrace.synthesis.interfaces import (
    _max_interface_data_rate,
    _via_stub_note,
    _via_stub_risk,
    bga_breakout_rules,
    get_interface_profile,
    list_interfaces,
    via_stub_resonance,
)


def test_known_differential_impedances() -> None:
    assert get_interface_profile("usb2").differential_impedance_ohms == 90.0
    assert get_interface_profile("ethernet-100").differential_impedance_ohms == 100.0
    assert get_interface_profile("hdmi").differential_impedance_ohms == 100.0
    assert get_interface_profile("pcie").differential_impedance_ohms == 85.0


def test_can_has_termination() -> None:
    can = get_interface_profile("can")
    assert can.bus_termination_ohms == 120.0
    assert can.differential_impedance_ohms == 120.0


def test_ddr3_is_single_ended() -> None:
    ddr = get_interface_profile("ddr3")
    assert ddr.single_ended_impedance_ohms == 40.0
    assert ddr.differential_impedance_ohms is None


def test_lookup_is_case_insensitive() -> None:
    assert get_interface_profile("USB2").name == "usb2"


def test_unknown_interface_raises() -> None:
    with pytest.raises(ValueError, match="Unknown interface"):
        get_interface_profile("rs232")


def test_list_interfaces() -> None:
    names = list_interfaces()
    assert "usb2" in names
    assert "pcie" in names
    assert names == sorted(names)


def test_profile_serializable() -> None:
    data = get_interface_profile("usb3").to_dict()
    assert data["differential_impedance_ohms"] == 90.0
    assert "notes" in data


class TestViaStubResonance:
    def test_no_backdrill_thicker_board_gives_lower_freq(self) -> None:
        w_thick = via_stub_resonance(3.2, 0.0, "pcie")
        w_thin = via_stub_resonance(1.6, 0.0, "pcie")
        assert w_thick.resonant_freq_ghz < w_thin.resonant_freq_ghz

    def test_backdrilling_increases_resonant_freq(self) -> None:
        no_bd = via_stub_resonance(1.6, 0.0, "usb3")
        with_bd = via_stub_resonance(1.6, 1.0, "usb3")
        assert with_bd.resonant_freq_ghz > no_bd.resonant_freq_ghz

    def test_stub_length_is_via_minus_backdrill(self) -> None:
        w = via_stub_resonance(1.6, 0.6, "usb2")
        assert w.stub_length_mm == pytest.approx(1.0, rel=1e-3)

    def test_invalid_backdrill_raises(self) -> None:
        with pytest.raises(ValueError):
            via_stub_resonance(1.6, 1.6, "pcie")  # backdrill >= via length

    def test_unknown_interface_raises(self) -> None:
        with pytest.raises(ValueError):
            via_stub_resonance(1.6, 0.0, "rs232")

    def test_serializable(self) -> None:
        w = via_stub_resonance(1.6, 0.0, "usb3")
        d = w.to_dict()
        assert "resonant_freq_ghz" in d
        assert "risk" in d


class TestBgaBreakoutRules:
    def test_1mm_pitch(self) -> None:
        r = bga_breakout_rules(1.0)
        assert r.pitch_mm == 1.0
        assert r.max_trace_width_mm <= 0.15

    def test_0_8mm_pitch(self) -> None:
        r = bga_breakout_rules(0.8)
        assert r.pitch_mm == 0.8

    def test_larger_than_known_snaps_to_1mm(self) -> None:
        r = bga_breakout_rules(1.27)
        assert r.pitch_mm == 1.0

    def test_smaller_than_0_5mm_raises(self) -> None:
        with pytest.raises(ValueError):
            bga_breakout_rules(0.3)

    def test_serializable(self) -> None:
        d = bga_breakout_rules(1.0).to_dict()
        assert "max_trace_width_mm" in d
        assert "note" in d


def test_via_stub_helpers_preserve_rate_risk_and_note_semantics() -> None:
    assert _max_interface_data_rate("pcie", get_interface_profile("pcie")) == 8.0
    assert _max_interface_data_rate("usb3", get_interface_profile("usb3")) == 10.0
    assert _max_interface_data_rate("usb2", get_interface_profile("usb2")) == 0.48
    assert _max_interface_data_rate("can", get_interface_profile("can")) is None
    assert _via_stub_risk(1.0, 8.0) == "high"
    assert _via_stub_risk(5.0, 8.0) == "medium"
    assert _via_stub_risk(9.0, 8.0) == "low"
    assert _via_stub_risk(9.0, None) == "unknown"
    assert "No backdrilling applied." in _via_stub_note("usb3", 1.6, 22.0, "low", 0.0)
    assert "Backdrilled 1.00 mm." in _via_stub_note("usb3", 0.6, 58.0, "low", 1.0)
