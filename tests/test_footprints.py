"""Tests for the parametric footprint and symbol library."""

from __future__ import annotations

import math
from unittest.mock import patch

from zaptrace.core.models import (
    DrawCommand,
    FootprintDef,
    LayerSet,
    Pad,
    PadShape,
    SymbolDef,
)
from zaptrace.ee.footprints import (
    _CHIP_DIMENSIONS,
    _named_package_footprint,
    footprint_chip,
    footprint_crystal_smd,
    footprint_dip,
    footprint_header,
    footprint_jst_ph,
    footprint_qfn,
    footprint_qfp,
    footprint_soic,
    footprint_solder_jumper,
    footprint_sot,
    footprint_test_pad,
    footprint_usb_a,
    footprint_usb_c,
    generate_footprint,
    generate_footprint_for_component,
    list_supported_packages,
    symbol_from_pins,
)


class TestChipFootprints:
    def test_0402(self) -> None:
        fp = footprint_chip("0402")
        assert fp is not None
        assert len(fp.pads) == 2
        assert all(p.shape == PadShape.RECT for p in fp.pads)
        assert "0402" in fp.description

    def test_0603(self) -> None:
        fp = footprint_chip("0603")
        assert fp is not None
        assert len(fp.pads) == 2

    def test_1206(self) -> None:
        fp = footprint_chip("1206")
        assert fp is not None
        assert len(fp.pads) == 2
        # 1206 should have wider pads than 0402
        assert fp.pads[0].size[0] > 1.0

    def test_unknown_chip(self) -> None:
        fp = footprint_chip("9999")
        assert fp is None

    def test_chip_pad_gap_matches_declared_copper_edge_spacing(self) -> None:
        for package, (_length, _width, _height, pad_width, _pad_height, pad_gap) in _CHIP_DIMENSIONS.items():
            fp = footprint_chip(package)
            assert fp is not None
            assert len(fp.pads) == 2
            center_spacing = abs(fp.pads[1].position[0] - fp.pads[0].position[0])
            copper_gap = center_spacing - pad_width
            assert math.isclose(copper_gap, pad_gap, rel_tol=0.0, abs_tol=1e-12), package

    def test_0402_pads_do_not_overlap(self) -> None:
        fp = footprint_chip("0402")
        assert fp is not None
        center_spacing = abs(fp.pads[1].position[0] - fp.pads[0].position[0])
        assert center_spacing >= fp.pads[0].size[0]

    def test_returns_footprintdef(self) -> None:
        fp = footprint_chip("0805")
        assert isinstance(fp, FootprintDef)


class TestSOTFootprints:
    def test_sot23(self) -> None:
        fp = footprint_sot("SOT-23")
        assert fp is not None
        assert len(fp.pads) == 3

    def test_sot23_5(self) -> None:
        fp = footprint_sot("SOT-23-5")
        assert fp is not None
        assert len(fp.pads) == 5

    def test_sot89(self) -> None:
        fp = footprint_sot("SOT-89")
        assert fp is not None
        assert len(fp.pads) == 4

    def test_unknown_sot(self) -> None:
        fp = footprint_sot("SOT-999")
        assert fp is None


class TestSOICFootprints:
    def test_soic8(self) -> None:
        fp = footprint_soic("SOIC-8")
        assert fp is not None
        assert len(fp.pads) == 8

    def test_soic14(self) -> None:
        fp = footprint_soic("SOIC-14")
        assert fp is not None
        assert len(fp.pads) == 14

    def test_tssop16(self) -> None:
        fp = footprint_soic("TSSOP-16")
        assert fp is not None
        assert len(fp.pads) == 16

    def test_unknown_soic(self) -> None:
        fp = footprint_soic("SOIC-999")
        assert fp is None


class TestQFNFootprints:
    def test_qfn16(self) -> None:
        fp = footprint_qfn("QFN-16")
        assert fp is not None
        # 16 pins + 1 thermal pad
        assert len(fp.pads) == 17

    def test_qfn32(self) -> None:
        fp = footprint_qfn("QFN-32")
        assert fp is not None
        assert len(fp.pads) == 33

    def test_qfn_thermal_pad(self) -> None:
        fp = footprint_qfn("QFN-32")
        assert fp is not None
        assert fp.thermal_pads is not None
        assert "0" in fp.thermal_pads

    def test_unknown_qfn(self) -> None:
        fp = footprint_qfn("QFN-999")
        assert fp is None


class TestQFPFootprints:
    def test_qfp32(self) -> None:
        fp = footprint_qfp("QFP-32")
        assert fp is not None
        assert len(fp.pads) == 32

    def test_qfp64(self) -> None:
        fp = footprint_qfp("QFP-64")
        assert fp is not None
        assert len(fp.pads) == 64


class TestDIPFootprints:
    def test_dip8(self) -> None:
        fp = footprint_dip("DIP-8")
        assert fp is not None
        assert len(fp.pads) == 8
        # THT should have drills
        assert fp.pads[0].drill is not None

    def test_dip14(self) -> None:
        fp = footprint_dip("DIP-14")
        assert fp is not None
        assert len(fp.pads) == 14

    def test_unknown_dip(self) -> None:
        fp = footprint_dip("DIP-999")
        assert fp is None


class TestConnectorFootprints:
    def test_header_1x4(self) -> None:
        fp = footprint_header(rows=1, cols=4)
        assert len(fp.pads) == 4
        assert fp.pads[0].drill is not None

    def test_header_2x8(self) -> None:
        fp = footprint_header(rows=2, cols=8)
        assert len(fp.pads) == 16

    def test_usb_a(self) -> None:
        fp = footprint_usb_a()
        assert fp is not None
        assert "USB" in fp.description

    def test_usb_c(self) -> None:
        fp = footprint_usb_c()
        assert fp is not None
        assert len(fp.pads) == 18  # 16 signal + 2 shield

    def test_jst_ph_2pin(self) -> None:
        fp = footprint_jst_ph(pins=2)
        assert fp is not None
        assert len(fp.pads) == 2

    def test_jst_ph_4pin(self) -> None:
        fp = footprint_jst_ph(pins=4)
        assert len(fp.pads) == 4


class TestSpecialFootprints:
    def test_crystal_smd(self) -> None:
        fp = footprint_crystal_smd()
        assert fp is not None
        assert len(fp.pads) == 4

    def test_solder_jumper(self) -> None:
        fp = footprint_solder_jumper()
        assert fp is not None
        assert len(fp.pads) == 2

    def test_test_pad(self) -> None:
        fp = footprint_test_pad()
        assert fp is not None
        assert len(fp.pads) == 1
        assert fp.pads[0].shape == PadShape.CIRCLE


class TestGenerateFootprint:
    def test_chip_via_package_name(self) -> None:
        fp = generate_footprint("0603")
        assert fp is not None
        assert len(fp.pads) == 2

    def test_soic_via_generate(self) -> None:
        fp = generate_footprint("SOIC-8")
        assert fp is not None
        assert len(fp.pads) == 8

    def test_qfn_via_generate(self) -> None:
        fp = generate_footprint("QFN-32")
        assert fp is not None
        assert len(fp.pads) == 33

    def test_dip_via_generate(self) -> None:
        fp = generate_footprint("DIP-8")
        assert fp is not None
        assert len(fp.pads) == 8

    def test_sot_via_generate(self) -> None:
        fp = generate_footprint("SOT-23")
        assert fp is not None
        assert len(fp.pads) == 3

    def test_unknown_returns_none(self) -> None:
        fp = generate_footprint("BGA-256")
        assert fp is None

    def test_alias_resolution(self) -> None:
        fp = generate_footprint("soic8")
        assert fp is not None
        assert len(fp.pads) == 8

    def test_layer_override(self) -> None:
        fp = generate_footprint("0603", layer=LayerSet.BOTTOM)
        assert fp is not None
        assert fp.pads[0].layer == LayerSet.BOTTOM


class TestGenerateForComponent:
    def test_header_type(self) -> None:
        fp = generate_footprint_for_component("1x4", component_type="header")
        assert fp is not None
        assert len(fp.pads) == 4

    def test_usb_c_type(self) -> None:
        fp = generate_footprint_for_component("", component_type="usb-c")
        assert fp is not None
        assert "USB" in fp.description

    def test_jst_type(self) -> None:
        fp = generate_footprint_for_component("", component_type="jst")
        assert fp is not None
        assert "JST" in fp.description

    def test_crystal_type(self) -> None:
        fp = generate_footprint_for_component("", component_type="crystal")
        assert fp is not None
        assert len(fp.pads) == 4

    def test_fallback_to_package(self) -> None:
        fp = generate_footprint_for_component("0603", component_type="resistor")
        assert fp is not None
        assert len(fp.pads) == 2

    def test_empty_returns_none(self) -> None:
        fp = generate_footprint_for_component("", "")
        assert fp is None


class TestListSupported:
    def test_returns_list(self) -> None:
        pkgs = list_supported_packages()
        assert isinstance(pkgs, list)

    def test_contains_common(self) -> None:
        pkgs = list_supported_packages()
        assert "0603" in pkgs
        assert "SOIC-8" in pkgs
        assert "QFN-32" in pkgs
        assert len(pkgs) >= 40

    def test_sorted(self) -> None:
        pkgs = list_supported_packages()
        assert pkgs == sorted(pkgs)


class TestSymbolFromPins:
    def test_basic_pins(self) -> None:
        pins = {
            "1": {"type": "input"},
            "2": {"type": "output"},
            "3": {"type": "power"},
            "4": {"type": "power"},
        }
        sym = symbol_from_pins(pins)
        assert isinstance(sym, SymbolDef)
        assert len(sym.pins) == 4

    def test_power_pins_on_top(self) -> None:
        pins = {
            "1": {"type": "input"},
            "VCC": {"type": "power"},
            "GND": {"type": "power"},
            "2": {"type": "output"},
        }
        sym = symbol_from_pins(pins)
        # Power pins should be positioned at top
        top_pins = [p for p in sym.pins if p.orientation == "top"]
        assert len(top_pins) == 2
        assert {p.name for p in top_pins} == {"VCC", "GND"}

    def test_body_has_rect(self) -> None:
        pins = {"1": {"type": "passive"}, "2": {"type": "passive"}}
        sym = symbol_from_pins(pins)
        assert len(sym.body) >= 1
        assert sym.body[0].type == "rect"

    def test_custom_dimensions(self) -> None:
        pins = {"1": {"type": "passive"}}
        sym = symbol_from_pins(pins, width=80.0, height=120.0)
        assert sym.width == 80.0
        assert sym.height == 120.0

    def test_empty_pins(self) -> None:
        sym = symbol_from_pins({})
        assert isinstance(sym, SymbolDef)
        assert len(sym.pins) == 0


MOCK_FP_DEF = FootprintDef(
    pads=[Pad(id="1", position=(-1.0, 0.0), size=(1.0, 1.0)), Pad(id="2", position=(1.0, 0.0), size=(1.0, 1.0))],
    outline=[DrawCommand(type="circle", params={"r": 1})],
    courtyard=(4.0, 3.0),
    description="Mock SOIC-8 LCSC:C12345",
)

MOCK_SYM_DEF = SymbolDef()


class TestLCSCIntegration:
    @patch("zaptrace.ee.imports.import_lcsc_component")
    def test_generate_with_lcsc_id(self, mock_import) -> None:
        mock_import.return_value = (MOCK_FP_DEF, MOCK_SYM_DEF)

        fp = generate_footprint_for_component("SOIC-8", lcsc_id="C12345")

        assert fp is not None
        assert len(fp.pads) == 2
        assert "LCSC:C12345" in fp.description
        mock_import.assert_called_once_with("C12345")

    @patch("zaptrace.ee.imports.import_lcsc_component")
    def test_generate_with_lcsc_id_fallback(self, mock_import) -> None:
        # If LCSC importer returns None, fallback to default package
        mock_import.return_value = (None, None)

        fp = generate_footprint_for_component("SOIC-8", lcsc_id="C99999")

        assert fp is not None
        assert len(fp.pads) == 8  # The default SOIC-8 has 8 pads
        mock_import.assert_called_once_with("C99999")


def test_named_package_dispatch_preserves_family_generators() -> None:
    expected_pads = {"SOT-23": 3, "SOIC-8": 8, "QFN-32": 33, "LQFP-48": 48, "DIP-8": 8}
    for package, pad_count in expected_pads.items():
        footprint = _named_package_footprint(package, LayerSet.TOP)
        assert footprint is not None
        assert len(footprint.pads) == pad_count
    assert _named_package_footprint("BGA-256", LayerSet.TOP) is None
