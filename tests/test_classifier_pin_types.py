"""Characterization tests for pin-type net classification."""

from __future__ import annotations

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetClass, NetNode, Pin, PinType
from zaptrace.ee.classifier import (
    _classify_component_types,
    _classify_power_pin_types,
    _collect_connected_types,
)


def test_collect_connected_types_ignores_missing_components_and_pins() -> None:
    component = Component(
        id="u1",
        ref="U1",
        type="USB-C",
        pins={
            "vbus": Pin(name="VBUS", type=PinType.POWER),
            "tx": Pin(name="TX", type=PinType.OUTPUT),
        },
    )
    net = Net(
        id="n1",
        name="MYSTERY",
        nodes=[
            NetNode(component_ref="U1", pin_name="vbus"),
            NetNode(component_ref="U1", pin_name="tx"),
            NetNode(component_ref="U1", pin_name="missing"),
            NetNode(component_ref="MISSING", pin_name="x"),
        ],
    )
    design = Design(meta=DesignMeta(name="classifier"), components={"u1": component}, nets={"n1": net})

    assert _collect_connected_types(design, net) == ({"power", "output"}, {"usb-c"})


def test_component_type_classification_preserves_priority() -> None:
    assert _classify_component_types({"antenna"}) == NetClass.RF
    assert _classify_component_types({"usb-c"}) == NetClass.DIFFERENTIAL
    assert _classify_component_types({"analog-front-end"}) == NetClass.SIGNAL_ANALOG
    assert _classify_component_types({"resistor"}) is None


def test_power_pin_classification_preserves_output_boost() -> None:
    assert _classify_power_pin_types({"power", "output"}) == NetClass.POWER_MED
    assert _classify_power_pin_types({"power"}) == NetClass.POWER_LOW
    assert _classify_power_pin_types({"input"}) == NetClass.SIGNAL_LOW
