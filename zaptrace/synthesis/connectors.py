"""Connector synthesis: give the board the physical input it needs.

Power-input synthesis emits the USB-C CC termination resistors but no actual
receptacle — so the synthesized board had nothing to plug into and its CC nets
dangled at a single resistor. This places the real USB-C connector from the
library and wires VBUS / GND / CC1 / CC2 / shield, turning the CC nets into real
two-terminal connections and giving the board a power source.

D+/D- and the sideband pins are left unconnected: a power-only USB-C input does
not use them, and inventing a connection would be wrong.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from zaptrace.core.models import Component, Net, NetNode, Pin, PinType
from zaptrace.library.loader import LibraryLoader

if TYPE_CHECKING:
    from zaptrace.core.models import Design

_USB_C_PART = "usb-c-16p"


def _next_ref(design: Design, prefix: str) -> str:
    idx = 1
    while f"{prefix}{idx}" in design.components:
        idx += 1
    return f"{prefix}{idx}"


def _connect(design: Design, net_name: str, ref: str, pin: str) -> None:
    if net_name not in design.nets:
        design.nets[net_name] = Net(id=net_name, name=net_name)
    design.nets[net_name].nodes.append(NetNode(component_ref=ref, pin_name=pin))


def _pin_type(raw: dict[str, str]) -> PinType:
    try:
        return PinType(raw.get("type", "passive"))
    except ValueError:
        return PinType.PASSIVE


def instantiate_usb_c_connector(
    design: Design,
    *,
    vbus_net: str = "VBUS",
    gnd_net: str = "GND",
    cc1_net: str = "CC1",
    cc2_net: str = "CC2",
    ref: str | None = None,
) -> str:
    """Place the USB-C receptacle and wire power, ground, shield, and the CC pins.

    Returns the connector's reference designator. CC1/CC2 join the nets the CC
    termination resistors already sit on, so those nets become real connections.
    """
    spec = LibraryLoader().get(_USB_C_PART)
    if ref is None:
        ref = _next_ref(design, "J")
    design.components[ref] = Component(
        id=ref,
        ref=ref,
        type="connector",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )
    wiring = {"VBUS": vbus_net, "GND": gnd_net, "SHIELD": gnd_net, "CC1": cc1_net, "CC2": cc2_net}
    for pin, net in wiring.items():
        if pin in spec.pins:
            _connect(design, net, ref, pin)
    return ref


def instantiate_dc_input(design: Design, *, vin_net: str, gnd_net: str = "GND", ref: str | None = None) -> str:
    """Place a 2-terminal DC power input and wire it to a rail and ground.

    Used when an intent states a rail but no on-board input source: the board is
    powered externally at that rail's voltage through a screw terminal.
    """
    spec = LibraryLoader().get("terminal-2p-5mm")
    if ref is None:
        ref = _next_ref(design, "J")
    design.components[ref] = Component(
        id=ref,
        ref=ref,
        type="connector",
        value=spec.name,
        mpn=spec.mpn,
        footprint=spec.footprint,
        pins={name: Pin(name=name, type=_pin_type(raw)) for name, raw in spec.pins.items()},
        package_pin_map=dict(spec.package_pin_map),
    )
    _connect(design, vin_net, ref, "P1")
    _connect(design, gnd_net, ref, "P2")
    return ref
