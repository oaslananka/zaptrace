"""Focused regression tests for ERC power-source discovery."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode, NetType, Pin, PinType
from zaptrace.erc.rules import (
    _inductor_connects_to_regulator,
    _net_has_direct_power_source,
    _power_net_has_source,
)


def _design(*, components: list[Component], nets: list[Net]) -> Design:
    return Design(
        meta=DesignMeta(name="power-source-fixture"),
        components={component.id: component for component in components},
        nets={net.id: net for net in nets},
    )


def _component(component_id: str, component_type: str, **pins: PinType) -> Component:
    return Component(
        id=component_id,
        ref=component_id.upper(),
        type=component_type,
        pins={name: Pin(name=name, type=pin_type) for name, pin_type in pins.items()},
    )


def test_direct_power_source_detection_preserves_output_regulator_and_connector_rules() -> None:
    output = _component("driver", "logic", OUT=PinType.OUTPUT)
    regulator = _component("reg", "buck regulator", SW=PinType.POWER)
    connector = _component("jack", "USB-C-16P", VBUS=PinType.POWER)
    sink = _component("load", "mcu", VCC=PinType.POWER)
    net = Net(
        id="rail",
        name="RAIL",
        type=NetType.POWER,
        nodes=[
            NetNode(component_ref="DRIVER", pin_name="OUT"),
            NetNode(component_ref="REG", pin_name="SW"),
            NetNode(component_ref="JACK", pin_name="VBUS"),
            NetNode(component_ref="LOAD", pin_name="VCC"),
        ],
    )
    design = _design(components=[output, regulator, connector, sink], nets=[net])

    assert _net_has_direct_power_source(design, net) is True
    assert _power_net_has_source(design, net.id) is True


def test_direct_power_source_detection_rejects_missing_components_and_sink_only_net() -> None:
    sink = _component("load", "mcu", VCC=PinType.POWER)
    net = Net(
        id="rail",
        name="RAIL",
        type=NetType.POWER,
        nodes=[
            NetNode(component_ref="MISSING", pin_name="OUT"),
            NetNode(component_ref="LOAD", pin_name="VCC"),
        ],
    )
    design = _design(components=[sink], nets=[net])

    assert _net_has_direct_power_source(design, net) is False
    assert _power_net_has_source(design, net.id) is False
    assert _power_net_has_source(design, "missing-net") is False


def test_inductor_neighbor_detection_follows_other_net_to_regulator() -> None:
    inductor = _component("l1", "inductor", A=PinType.PASSIVE, B=PinType.PASSIVE)
    regulator = _component("u1", "buck regulator", SW=PinType.POWER)
    load = _component("load", "mcu", VCC=PinType.POWER)
    output = Net(
        id="output",
        name="3V3",
        type=NetType.POWER,
        nodes=[
            NetNode(component_ref="L1", pin_name="A"),
            NetNode(component_ref="LOAD", pin_name="VCC"),
        ],
    )
    switch = Net(
        id="switch",
        name="SW",
        nodes=[
            NetNode(component_ref="L1", pin_name="B"),
            NetNode(component_ref="U1", pin_name="SW"),
        ],
    )
    design = _design(components=[inductor, regulator, load], nets=[output, switch])

    assert _inductor_connects_to_regulator(design, output.id, "L1") is True
    assert _power_net_has_source(design, output.id) is True


def test_inductor_neighbor_detection_requires_other_net_and_regulator_component() -> None:
    inductor = _component("l1", "ferrite bead", A=PinType.PASSIVE, B=PinType.PASSIVE)
    load = _component("load", "mcu", VCC=PinType.POWER)
    output = Net(
        id="output",
        name="3V3",
        type=NetType.POWER,
        nodes=[
            NetNode(component_ref="L1", pin_name="A"),
            NetNode(component_ref="LOAD", pin_name="VCC"),
        ],
    )
    isolated = Net(
        id="isolated",
        name="ISOLATED",
        nodes=[NetNode(component_ref="L1", pin_name="B")],
    )
    design = _design(components=[inductor, load], nets=[output, isolated])

    assert _inductor_connects_to_regulator(design, output.id, "L1") is False
    assert _inductor_connects_to_regulator(design, output.id, "MISSING") is False
    assert _power_net_has_source(design, output.id) is False
