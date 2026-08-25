"""Tests for extended footprint generators: DFN, BGA, WLCSP, Module."""

from __future__ import annotations

from zaptrace.core.models import FootprintDef, PadShape
from zaptrace.ee.footprints import (
    footprint_bga,
    footprint_dfn,
    footprint_module,
    footprint_wlcsp,
    generate_footprint,
    generate_footprint_for_component,
    list_supported_packages,
)


class TestDfnFootprint:
    """Test DFN package generator."""

    def test_dfn8_pads_and_thermal(self) -> None:
        fp = footprint_dfn("DFN-8")
        assert fp is not None
        assert isinstance(fp, FootprintDef)
        # 8 signal pads + 1 thermal pad ("0")
        assert len(fp.pads) == 9
        pad_ids = {p.id for p in fp.pads}
        assert pad_ids == {"1", "2", "3", "4", "5", "6", "7", "8", "0"}
        assert fp.thermal_pads == ["0"]

    def test_dfn_alias_dispatch(self) -> None:
        fp = generate_footprint("dfn8")
        assert fp is not None
        assert len(fp.pads) == 9

    def test_unknown_dfn_returns_none(self) -> None:
        assert footprint_dfn("DFN-99") is None


class TestBgaFootprint:
    """Test BGA package generator."""

    def test_bga48_pad_count_and_naming(self) -> None:
        fp = footprint_bga("BGA-48")
        assert fp is not None
        # 6 rows x 8 cols = 48 pads
        assert len(fp.pads) == 48
        # JEDEC pad IDs: A1..A8, B1..B8, C1..C8, D1..D8, E1..E8, F1..F8
        pad_ids = {p.id for p in fp.pads}
        assert "A1" in pad_ids
        assert "A8" in pad_ids
        assert "F8" in pad_ids
        # Pad shapes should be circular
        assert all(p.shape == PadShape.CIRCLE for p in fp.pads)

    def test_bga_custom_grid(self) -> None:
        fp = footprint_bga(rows=4, cols=4, pitch=0.5, ball_diameter=0.3)
        assert len(fp.pads) == 16
        pad_ids = {p.id for p in fp.pads}
        assert "A1" in pad_ids
        assert "D4" in pad_ids

    def test_bga_dispatch(self) -> None:
        fp = generate_footprint("bga64")
        assert fp is not None
        assert len(fp.pads) == 64


class TestWlcspFootprint:
    """Test WLCSP package generator."""

    def test_wlcsp16_pads(self) -> None:
        fp = footprint_wlcsp("WLCSP-16")
        assert fp is not None
        # 4 rows x 4 cols = 16 pads
        assert len(fp.pads) == 16
        pad_ids = {p.id for p in fp.pads}
        assert "A1" in pad_ids
        assert "D4" in pad_ids

    def test_wlcsp_dispatch(self) -> None:
        fp = generate_footprint("wlcsp4")
        assert fp is not None
        assert len(fp.pads) == 4


class TestModuleFootprint:
    """Test SMD module castellation generator."""

    def test_module_pads(self) -> None:
        fp = footprint_module(
            width=18.0,
            height=25.5,
            pins_left=10,
            pins_right=10,
            pins_bottom=5,
            pitch=1.27,
        )
        assert isinstance(fp, FootprintDef)
        assert len(fp.pads) == 25
        pad_ids = {p.id for p in fp.pads}
        assert pad_ids == {str(i) for i in range(1, 26)}

    def test_module_for_component(self) -> None:
        fp = generate_footprint_for_component("MODULE", component_type="module")
        assert fp is not None


class TestSupportedPackagesList:
    """Test list_supported_packages includes new types."""

    def test_packages_include_new_types(self) -> None:
        pkgs = list_supported_packages()
        assert "DFN-8" in pkgs
        assert "BGA-48" in pkgs
        assert "WLCSP-16" in pkgs
        assert "MODULE" in pkgs

    def test_special_component_type_dispatches(self) -> None:
        # Header pin count variations
        h_2p = generate_footprint_for_component("2P", component_type="header")
        assert h_2p is not None
        assert len(h_2p.pads) == 2

        h_term = generate_footprint_for_component("2x4", component_type="terminal")
        assert h_term is not None
        assert len(h_term.pads) == 8

        # USB, JST, Crystal, Jumper, Testpad
        assert generate_footprint_for_component("USB", component_type="usb-a") is not None
        assert generate_footprint_for_component("USB", component_type="usb-c") is not None
        assert generate_footprint_for_component("CONN", component_type="jst") is not None
        assert generate_footprint_for_component("XTAL", component_type="crystal") is not None
        assert generate_footprint_for_component("JP", component_type="solder-jumper") is not None
        assert generate_footprint_for_component("TP", component_type="test-pad") is not None
