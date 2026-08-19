from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType
from zaptrace.erc.graph import ElectricalGraph
from zaptrace.erc.rules import rule_ERC005


def _i2c_design(*, resistor_to_power: bool) -> Design:
    design = Design(meta=DesignMeta(name="erc-graph"))
    design.components["u1"] = Component(
        id="u1",
        ref="U1",
        type="mcu",
        pins={"SDA": Pin(name="SDA", type=PinType.BIDIRECTIONAL, net="sda")},
    )
    design.components["r1"] = Component(
        id="r1",
        ref="R1",
        type="RES",
        value="4.7k",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE, net="sda"),
            "2": Pin(name="2", type=PinType.PASSIVE, net="vcc" if resistor_to_power else "float"),
        },
    )
    design.nets["sda"] = Net(
        id="sda",
        name="I2C_SDA",
        nodes=[NetNode(component_ref="U1", pin_name="SDA"), NetNode(component_ref="R1", pin_name="1")],
    )
    design.nets["vcc"] = Net(
        id="vcc",
        name="VCC_3V3",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="R1", pin_name="2")] if resistor_to_power else [],
    )
    if not resistor_to_power:
        design.nets["float"] = Net(
            id="float",
            name="FLOAT",
            nodes=[NetNode(component_ref="R1", pin_name="2")],
        )
    return design


def test_electrical_graph_indexes_endpoints_and_component_nets() -> None:
    graph = ElectricalGraph.from_design(_i2c_design(resistor_to_power=True))
    assert {endpoint.component_ref for endpoint in graph.endpoints("sda")} == {"U1", "R1"}
    assert graph.nets_for_component("R1") == {"sda", "vcc"}
    assert graph.is_power_net("vcc")


def test_i2c_pullup_requires_resistor_to_power_rail() -> None:
    assert rule_ERC005(_i2c_design(resistor_to_power=True)) == []
    violations = rule_ERC005(_i2c_design(resistor_to_power=False))
    assert len(violations) == 1
    assert "power rail" in violations[0].message
