"""Characterization tests for schematic wire routing helpers."""

from __future__ import annotations

from zaptrace.core.models import Design, DesignMeta, Net, NetNode, SymbolDef, SymbolPin
from zaptrace.ee.schematic.engine import WIRE_WIDTH, SchematicEngine


def test_collect_net_pin_positions_skips_unresolvable_nodes() -> None:
    engine = SchematicEngine()
    net = Net(
        id="n1",
        name="BUS",
        nodes=[
            NetNode(component_ref="U1", pin_name="A"),
            NetNode(component_ref="U2", pin_name="missing"),
            NetNode(component_ref="NO_POSITION", pin_name="A"),
            NetNode(component_ref="NO_SYMBOL", pin_name="A"),
            NetNode(component_ref="UNKNOWN", pin_name="A"),
        ],
    )
    symbols = {
        "u1": SymbolDef(pins=[SymbolPin(id="A", name="A", position=(1, 2), length=5, orientation="right")]),
        "u2": SymbolDef(pins=[SymbolPin(id="B", name="B", position=(0, 0))]),
        "no_position": SymbolDef(pins=[SymbolPin(id="A", name="A", position=(0, 0))]),
    }
    positions = {"u1": (10.0, 20.0), "u2": (30.0, 40.0), "no_symbol": (50.0, 60.0)}
    ref_to_id = {"U1": "u1", "U2": "u2", "NO_POSITION": "no_position", "NO_SYMBOL": "no_symbol"}

    assert engine._collect_net_pin_positions(net, ref_to_id, symbols, positions) == [(16.0, 22.0, "u1")]


def test_orthogonal_wire_segments_preserve_both_existing_branches() -> None:
    engine = SchematicEngine()
    assert engine._orthogonal_wire_segments((0, 0, "a"), (10, 2, "b"), "H") == [
        (0, 0, 5.0, 0, "H", WIRE_WIDTH),
        (5.0, 0, 5.0, 2, "H", WIRE_WIDTH),
        (5.0, 2, 10, 2, "H", WIRE_WIDTH),
    ]
    assert engine._orthogonal_wire_segments((1, 2, "a"), (3, 12, "b"), "V") == [
        (1, 2, 1, 2.0, "V", WIRE_WIDTH),
        (1, 2.0, 3, 2.0, "V", WIRE_WIDTH),
        (3, 2.0, 3, 12, "V", WIRE_WIDTH),
    ]


def test_route_wires_preserves_sorted_adjacent_connection_order() -> None:
    engine = SchematicEngine()
    design = Design(
        meta=DesignMeta(name="wires"),
        nets={
            "n1": Net(
                id="n1",
                name="BUS",
                nodes=[
                    NetNode(component_ref="U3", pin_name="P"),
                    NetNode(component_ref="U1", pin_name="P"),
                    NetNode(component_ref="U2", pin_name="P"),
                ],
            )
        },
    )
    design.components = {}
    # The helper only needs ref/id mapping from components; use model construction through assignment.
    from zaptrace.core.models import Component

    design.components = {
        "u1": Component(id="u1", ref="U1", type="test"),
        "u2": Component(id="u2", ref="U2", type="test"),
        "u3": Component(id="u3", ref="U3", type="test"),
    }
    symbol = SymbolDef(pins=[SymbolPin(id="P", name="P", position=(0, 0), length=0, orientation="right")])
    symbols = {"u1": symbol, "u2": symbol, "u3": symbol}
    positions = {"u1": (0.0, 0.0), "u2": (10.0, 0.0), "u3": (20.0, 0.0)}

    wires = engine._route_wires(design, symbols, positions)
    assert len(wires) == 6
    assert wires[:3] == engine._orthogonal_wire_segments((0, 0, "u1"), (10, 0, "u2"), "BUS")
    assert wires[3:] == engine._orthogonal_wire_segments((10, 0, "u2"), (20, 0, "u3"), "BUS")
