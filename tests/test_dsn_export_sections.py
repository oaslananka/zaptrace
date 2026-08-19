"""Focused regression tests for Specctra DSN section renderers."""

from __future__ import annotations

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    LayerSpec,
    Net,
    NetNode,
    Pad,
    PadShape,
)
from zaptrace.export.dsn import (
    _library_lines,
    _network_lines,
    _parser_lines,
    _placement_lines,
    _structure_lines,
    _wiring_lines,
)


class _GeometryKnowledgeBase:
    def resolve_net_geometry(self, net: Net) -> dict[str, float]:
        del net
        return {"trace_width": 0.42}


def _design() -> Design:
    design = Design(
        meta=DesignMeta(name="section_board"),
        board_def=BoardDefinition(
            outline=[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)],
            layer_stack=[
                LayerSpec(name="F.Cu", type="signal"),
                LayerSpec(name="In1.Cu", type="power"),
                LayerSpec(name="B.Cu", type="signal"),
            ],
        ),
    )
    design.components = {
        "U1": Component(
            id="U1",
            ref="U1",
            type="ic",
            position=(1.0, 2.0),
            footprint_def=FootprintDef(
                pads=[
                    Pad(
                        id="1",
                        layer=LayerSet.TOP,
                        shape=PadShape.CIRCLE,
                        position=(-1.0, 0.0),
                        size=(1.2, 1.2),
                    ),
                    Pad(
                        id="2",
                        layer=LayerSet.BOTTOM,
                        shape=PadShape.RECT,
                        position=(1.0, 0.0),
                        size=(1.0, 2.0),
                    ),
                ]
            ),
        ),
        "SKIP": Component(id="SKIP", ref="SKIP", type="virtual"),
    }
    design.placement = {"U1": (3.0, 4.0, 90.0)}  # type: ignore[dict-item]
    design.nets = {"N1": Net(id="N1", name="SIGNAL", nodes=[NetNode(component_ref="U1", pin_name="1")])}
    return design


def test_parser_and_structure_sections_preserve_dsn_records() -> None:
    design = _design()

    assert _parser_lines() == [
        "  (parser",
        '    (string_quote ")',
        "    (space_in_quoted_tokens on)",
        '    (host_cad "ZapTrace")',
        '    (host_version "1.0")',
        "  )",
        "  (resolution mm 10000)",
        "  (unit mm)",
    ]
    structure, layers = _structure_lines(design)
    assert layers == ["F.Cu", "In1.Cu", "B.Cu"]
    assert structure == [
        "  (structure",
        "    (layer F.Cu (type signal))",
        "    (layer In1.Cu (type power))",
        "    (layer B.Cu (type signal))",
        "    (boundary",
        "      (path pcb 0 0.0000 0.0000 10.0000 0.0000 10.0000 5.0000 0.0000 0.0000)",
        "    )",
        "  )",
    ]


def test_placement_library_network_and_wiring_sections_are_stable() -> None:
    design = _design()

    assert _placement_lines(design) == [
        "  (placement",
        "    (component U1",
        "      (place U1 3.0000 4.0000 front 90.0)",
        "    )",
        "  )",
    ]
    assert _library_lines(design, ["F.Cu", "In1.Cu", "B.Cu"]) == [
        "  (library",
        "    (image U1",
        "      (pin Pad_circle_1_20x1_20_F_Cu 1 -1.0000 0.0000)",
        "      (pin Pad_rect_1_00x2_00_B_Cu 2 1.0000 0.0000)",
        "    )",
        "    (padstack Pad_circle_1_20x1_20_F_Cu",
        "      (shape (circle F.Cu 0.6000))",
        "    )",
        "    (padstack Pad_rect_1_00x2_00_B_Cu",
        "      (shape (rect B.Cu -0.5000 -1.0000 0.5000 1.0000))",
        "    )",
        "  )",
    ]
    assert _network_lines(design) == [
        "  (network",
        "    (net SIGNAL",
        "      (pins",
        "        U1-1",
        "      )",
        "    )",
        "  )",
    ]
    assert _wiring_lines(design, _GeometryKnowledgeBase()) == [
        "  (wiring",
        "    (class SIGNAL_Class SIGNAL",
        "      (rule",
        "        (width 0.4200)",
        "        (clearance 0.1500)",
        "      )",
        "    )",
        "  )",
    ]
