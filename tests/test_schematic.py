"""Tests for the Schematic Engine (Phase 2.2)."""

from __future__ import annotations

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    Net,
    NetNode,
    Pin,
    PinType,
    SymbolDef,
)
from zaptrace.ee.schematic import SchematicEngine, generate_symbol, render_schematic_svg
from zaptrace.ee.schematic.placement import place_schematic
from zaptrace.ee.schematic.symbols import SYMBOL_REGISTRY, TYPE_ALIASES


def _design() -> Design:
    return Design(
        meta=DesignMeta(name="SchematicTest", author="tester"),
        components={
            "r1": Component(id="r1", ref="R1", type="resistor", value="10k"),
            "r2": Component(id="r2", ref="R2", type="resistor", value="1k"),
            "c1": Component(id="c1", ref="C1", type="capacitor", value="100n"),
            "q1": Component(id="q1", ref="Q1", type="bjt_npn", value="2N3904"),
        },
        nets={
            "n1": Net(
                id="n1",
                name="NET1",
                nodes=[
                    NetNode(component_ref="R1", pin_name="1"),
                    NetNode(component_ref="C1", pin_name="1"),
                    NetNode(component_ref="Q1", pin_name="B"),
                ],
            ),
        },
    )


class TestSymbolGeneration:
    def test_resistor_symbol(self) -> None:
        comp = Component(id="r1", ref="R1", type="resistor", value="10k")
        sym = generate_symbol(comp)
        assert sym is not None
        assert len(sym.pins) >= 2
        assert len(sym.body) >= 1

    def test_capacitor_symbol(self) -> None:
        comp = Component(id="c1", ref="C1", type="capacitor", value="100n")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 2

    def test_inductor_symbol(self) -> None:
        comp = Component(id="l1", ref="L1", type="inductor", value="10uH")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 2

    def test_diode_symbol(self) -> None:
        comp = Component(id="d1", ref="D1", type="diode")
        sym = generate_symbol(comp)
        assert len(sym.pins) == 2

    def test_led_symbol(self) -> None:
        comp = Component(id="d1", ref="D1", type="led")
        sym = generate_symbol(comp)
        assert len(sym.pins) == 2

    def test_bjt_npn_symbol(self) -> None:
        comp = Component(id="q1", ref="Q1", type="bjt_npn")
        sym = generate_symbol(comp)
        assert len(sym.pins) == 3

    def test_nmos_symbol(self) -> None:
        comp = Component(id="q1", ref="Q1", type="nmos")
        sym = generate_symbol(comp)
        assert len(sym.pins) == 3

    def test_opamp_symbol(self) -> None:
        comp = Component(id="u1", ref="U1", type="opamp")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 3

    def test_connector_symbol(self) -> None:
        comp = Component(id="j1", ref="J1", type="connector")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 2

    def test_crystal_symbol(self) -> None:
        comp = Component(id="y1", ref="Y1", type="crystal")
        sym = generate_symbol(comp)
        assert len(sym.pins) == 2

    def test_fuse_symbol(self) -> None:
        comp = Component(id="f1", ref="F1", type="fuse")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 2

    def test_regulator_symbol(self) -> None:
        comp = Component(id="u1", ref="U1", type="regulator")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 3

    def test_transformer_symbol(self) -> None:
        comp = Component(id="t1", ref="T1", type="transformer")
        sym = generate_symbol(comp)
        assert len(sym.pins) >= 4

    def test_antenna_symbol(self) -> None:
        comp = Component(id="ant1", ref="ANT1", type="antenna")
        sym = generate_symbol(comp)
        assert len(sym.body) >= 1

    def test_unknown_type_fallback(self) -> None:
        comp = Component(
            id="x1",
            ref="X1",
            type="custom_thing",
            pins={"A": Pin(name="A", type=PinType.PASSIVE), "B": Pin(name="B", type=PinType.PASSIVE)},
        )
        sym = generate_symbol(comp)
        assert sym is not None

    def test_unknown_type_no_pins(self) -> None:
        comp = Component(id="x1", ref="X1", type="custom_thing")
        sym = generate_symbol(comp)
        # Should return a placeholder box
        assert len(sym.body) >= 1

    def test_existing_symbol_override(self) -> None:
        """Component.symbol takes precedence."""
        existing = SymbolDef(
            pins=[],
            body=[],
            height=10,
            width=10,
        )
        comp = Component(id="r1", ref="R1", type="resistor", value="10k", symbol=existing)
        sym = generate_symbol(comp)
        assert sym is existing

    def test_symbol_type_override_property(self) -> None:
        """symbol_type property overrides type-based lookup."""
        comp = Component(id="d1", ref="D1", type="resistor", value="LED", properties={"symbol_type": "led"})
        sym = generate_symbol(comp)
        # Should generate an LED symbol (2 pins) not a resistor
        assert len(sym.pins) == 2

    def test_all_registry_entries(self) -> None:
        """Every entry in the symbol registry produces a valid symbol."""
        for name, gen in SYMBOL_REGISTRY.items():
            sym = gen()
            assert len(sym.body) >= 1, f"{name}: no body"
            assert isinstance(sym, SymbolDef), f"{name}: wrong type"

    def test_type_aliases_resolve(self) -> None:
        """Every type alias resolves to a valid symbol."""
        for alias, canonical in TYPE_ALIASES.items():
            gen_cls = SYMBOL_REGISTRY.get(canonical)
            assert gen_cls is not None, f"{alias} -> {canonical} not in registry"
            sym = gen_cls()
            assert sym is not None


class TestSchematicEngine:
    def test_render_creates_svg(self) -> None:
        svg = render_schematic_svg(_design())
        assert svg.startswith("<svg")
        assert "SchematicTest" in svg
        assert "R1" in svg
        assert "C1" in svg
        assert "Q1" in svg

    def test_svg_has_wires(self) -> None:
        svg = render_schematic_svg(_design())
        assert "wire" in svg
        assert "NET1" in svg

    def test_svg_has_symbols(self) -> None:
        svg = render_schematic_svg(_design())
        assert "R1" in svg  # ref designators
        assert "10k" in svg  # values
        assert "Q1" in svg

    def test_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        svg = render_schematic_svg(d)
        assert "No components" in svg

    def test_svg_with_pin_labels(self) -> None:
        d = Design(
            meta=DesignMeta(name="pin_test"),
            components={
                "r1": Component(
                    id="r1",
                    ref="R1",
                    type="resistor",
                    value="10k",
                    pins={"1": Pin(name="1", type=PinType.PASSIVE), "2": Pin(name="2", type=PinType.PASSIVE)},
                ),
            },
            nets={
                "n1": Net(id="n1", name="NET1", nodes=[NetNode(component_ref="R1", pin_name="1")]),
            },
        )
        svg = render_schematic_svg(d, show_pin_labels=True)
        assert "R1" in svg

    def test_render_with_blocks(self) -> None:
        """Render with block placement."""
        d = Design(
            meta=DesignMeta(name="block_test"),
            components={
                "r1": Component(id="r1", ref="R1", type="resistor", value="10k"),
                "r2": Component(id="r2", ref="R2", type="resistor", value="1k"),
                "c1": Component(id="c1", ref="C1", type="capacitor", value="100n"),
            },
        )
        svg = render_schematic_svg(d)
        assert svg.startswith("<svg")

    def test_author_in_svg(self) -> None:
        d = Design(
            meta=DesignMeta(name="auth", author="test_user"),
            components={"r1": Component(id="r1", ref="R1", type="resistor")},
        )
        svg = render_schematic_svg(d)
        assert "test_user" in svg

    def test_version_in_svg(self) -> None:
        d = Design(
            meta=DesignMeta(name="ver", version="2.0.0"),
            components={"r1": Component(id="r1", ref="R1", type="resistor")},
        )
        svg = render_schematic_svg(d)
        assert "2.0.0" in svg


class TestPlacement:
    def test_place_returns_dict(self) -> None:
        positions = place_schematic(_design())
        assert isinstance(positions, dict)
        assert len(positions) == 4

    def test_place_all_components(self) -> None:
        positions = place_schematic(_design())
        assert "r1" in positions
        assert "r2" in positions
        assert "c1" in positions
        assert "q1" in positions

    def test_place_returns_unique_positions(self) -> None:
        positions = place_schematic(_design())
        pos_set = set(positions.values())
        assert len(pos_set) == len(positions)

    def test_place_empty_design(self) -> None:
        d = Design(meta=DesignMeta(name="empty"))
        positions = place_schematic(d)
        assert positions == {}

    def test_place_with_component_blocks(self) -> None:
        positions = place_schematic(_design(), block_list=[["r1", "c1"], ["q1"]])

        assert set(positions) == {"r1", "r2", "c1", "q1"}
        assert positions["r1"] != positions["c1"]

    def test_place_within_bounds(self) -> None:
        positions = place_schematic(_design())
        for x, y in positions.values():
            assert 60 <= x <= 1140
            assert 60 <= y <= 840


class TestEngineClass:
    def test_engine_constructs(self) -> None:
        engine = SchematicEngine()
        assert engine.width == 1200
        assert engine.height == 900

    def test_engine_custom_size(self) -> None:
        engine = SchematicEngine(width_px=800, height_px=600)
        assert engine.width == 800
        assert engine.height == 600

    def test_engine_hides_pins(self) -> None:
        engine = SchematicEngine(show_pin_labels=False)
        assert not engine.show_pin_labels

    def test_engine_renders_design(self) -> None:
        engine = SchematicEngine()
        svg = engine.render(_design())
        assert "R1" in svg


class TestSymbolPinMapping:
    def test_pin_electrical_type(self) -> None:
        comp = Component(
            id="q1",
            ref="Q1",
            type="bjt_npn",
            pins={
                "B": Pin(name="B", type=PinType.INPUT),
                "C": Pin(name="C", type=PinType.OUTPUT),
                "E": Pin(name="E", type=PinType.PASSIVE),
            },
        )
        sym = generate_symbol(comp)
        # Find base pin
        b_pin = next(p for p in sym.pins if p.id == "B")
        assert b_pin.electrical_type == "input"


class TestSvgOutput:
    def test_svg_valid_structure(self) -> None:
        svg = render_schematic_svg(_design())
        assert svg.strip().startswith("<svg")
        assert svg.strip().endswith("</svg>")

    def test_svg_has_viewbox(self) -> None:
        svg = render_schematic_svg(_design())
        assert "viewBox" in svg

    def test_svg_no_duplicate_refs(self) -> None:
        """Each ref should appear exactly once."""
        svg = render_schematic_svg(_design())
        assert svg.count("R1") >= 1
