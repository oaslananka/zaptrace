"""Tests for DSN export format."""

from zaptrace.core.models import (
    BoardDefinition,
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    LayerSet,
    LayerSpec,
    Net,
    NetConstraints,
    NetNode,
    Pad,
    PadShape,
)
from zaptrace.export.dsn import export_dsn


def test_export_dsn_structure():
    design = Design(meta=DesignMeta(name="test_board"))
    design.board_def = BoardDefinition(
        outline=[(0, 0), (10, 0), (10, 10), (0, 10)],
        layer_stack=[LayerSpec(name="F.Cu", type="signal"), LayerSpec(name="B.Cu", type="signal")],
    )

    comp = Component(id="C1", ref="C1", type="cap", position=(5, 5))
    comp.footprint_def = FootprintDef(
        pads=[
            Pad(id="1", shape=PadShape.RECT, position=(-1, 0), size=(1, 1), layer=LayerSet.TOP),
            Pad(id="2", shape=PadShape.RECT, position=(1, 0), size=(1, 1), layer=LayerSet.TOP),
        ]
    )
    design.components["C1"] = comp
    design.placement = {"C1": (5, 5)}

    net1 = Net(id="N1", name="RF_P", nodes=[NetNode(component_ref="C1", pin_name="1")])
    net1.constraints = NetConstraints(impedance_target=90.0)
    design.nets["N1"] = net1

    dsn_output = export_dsn(design)

    # General structure
    assert "(pcb test_board" in dsn_output
    assert "(parser" in dsn_output
    assert "(resolution mm 10000)" in dsn_output

    # Structure/layer
    assert "(structure" in dsn_output
    assert "(layer F.Cu (type signal))" in dsn_output
    assert "(layer B.Cu (type signal))" in dsn_output
    assert "(boundary" in dsn_output

    # Placement
    assert "(placement" in dsn_output
    assert "(component C1" in dsn_output
    assert "(place C1 5.0000 5.0000 front 0.0)" in dsn_output

    # Library
    assert "(library" in dsn_output
    assert "(image C1" in dsn_output
    assert "(pin Pad_rect_1_00x1_00_F_Cu 1 -1.0000 0.0000)" in dsn_output

    # Network
    assert "(network" in dsn_output
    assert "(net RF_P" in dsn_output
    assert "C1-1" in dsn_output

    # Wiring/Classes
    assert "(wiring" in dsn_output
    assert "(class RF_P_Class RF_P" in dsn_output
    assert "(width " in dsn_output  # we assert width exists, the exact value may depend on the engine
    assert "(clearance 0.1500)" in dsn_output
