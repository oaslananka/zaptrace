"""Tests for the behavioral DC bias resolver."""

from __future__ import annotations

import pytest

from zaptrace.analysis.dc_bias import _rail_volts, behavioral_source_cards, resolve_dc_bias
from zaptrace.export.spice import export_spice_netlist
from zaptrace.synthesis.repair import synthesize_and_repair


def _design(intent: str):
    return synthesize_and_repair(intent)["design"]


class TestRailParsing:
    @pytest.mark.parametrize(
        ("net", "volts"),
        [("VDD_3V3", 3.3), ("VDD_5", 5.0), ("VDD_1V8", 1.8), ("SDA", None), ("VBUS", None)],
    )
    def test_rail_volts(self, net: str, volts: float | None) -> None:
        assert _rail_volts(net) == volts


class TestBiasResolution:
    def test_well_formed_board_passes(self) -> None:
        bias = resolve_dc_bias(_design("ESP32-C3 USB-C 3.3V board, I2C temperature sensor"))
        assert bias.passed
        assert bias.net_voltages["VDD_3V3"] == 3.3
        assert bias.net_voltages["VBUS"] == 5.0
        assert bias.net_voltages["GND"] == 0.0
        assert bias.undriven_rails == []

    def test_undriven_rail_is_flagged(self) -> None:
        # A 5V rail on a battery board needs a boost stage that has no block yet,
        # so VDD_5 is referenced by loads but driven by nothing.
        bias = resolve_dc_bias(_design("ESP32-C3 battery board, single Li-ion cell, 5V rail"))
        assert not bias.passed
        assert "VDD_5" in bias.undriven_rails

    def test_to_dict_shape(self) -> None:
        data = resolve_dc_bias(_design("ESP32-C3 USB-C 3.3V board, I2C sensor")).to_dict()
        assert set(data) == {"passed", "net_voltages", "rails_checked", "undriven_rails"}


class TestBehavioralSources:
    def test_sources_emitted_for_driven_rails_and_inputs(self) -> None:
        design = _design("ESP32-C3 USB-C 3.3V board, I2C sensor")
        cards = behavioral_source_cards(design)
        assert any(c.startswith("VVDD_3V3 VDD_3V3 0 3.3") for c in cards)
        assert any(c.startswith("VVBUS VBUS 0 5") for c in cards)

    def test_no_source_for_an_undriven_rail(self) -> None:
        design = _design("ESP32-C3 battery board, single Li-ion cell, 5V rail")
        cards = behavioral_source_cards(design)
        assert not any("VDD_5" in c for c in cards)  # not papered over with a source

    def test_export_injects_extra_cards(self) -> None:
        design = _design("ESP32-C3 USB-C 3.3V board, I2C sensor")
        netlist = export_spice_netlist(design, extra_cards=behavioral_source_cards(design))
        assert "Behavioral DC bias models" in netlist
        assert "VVDD_3V3 VDD_3V3 0 3.3" in netlist
        assert netlist.rstrip().endswith(".end")


class TestScorecardIntegration:
    def test_undriven_rail_fails_electrical_dimension(self) -> None:
        from zaptrace.synthesis.scorecard import score_board

        out = synthesize_and_repair("ESP32-C3 battery board, single Li-ion cell, 5V rail")
        bias = resolve_dc_bias(out["design"])
        card = score_board(out["design"], out["plan"], out["repair"], out["footprints"], bias)
        electrical = next(d for d in card.dimensions if d.name == "electrical")
        assert electrical.status == "fail"
        assert "undriven" in electrical.detail
