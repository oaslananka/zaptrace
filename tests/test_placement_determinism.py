from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.ee.schematic.placement import place_schematic


def test_schematic_placement_is_deterministic() -> None:
    design = Design(name="test_design", meta=DesignMeta(name="test_design"))
    design.components["R1"] = Component(id="R1", value="10k", ref="R1", footprint="R0805", type="resistor")
    design.components["C1"] = Component(id="C1", value="100nF", ref="C1", footprint="C0805", type="capacitor")
    design.components["U1"] = Component(id="U1", value="MCU", ref="U1", footprint="QFN32", type="ic")
    design.nets["N1"] = Net(
        id="N1",
        name="VDD",
        nodes=[
            NetNode(component_ref="R1", pin_number="1", pin_name="VCC"),
            NetNode(component_ref="U1", pin_number="1", pin_name="VDD"),
        ],
    )

    pos1 = place_schematic(design)
    pos2 = place_schematic(design)

    assert pos1 == pos2, "Schematic placement must be 100% deterministic across calls"
