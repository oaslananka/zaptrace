"""Behavioral DC bias resolver — an always-available power-topology check.

The full SPICE gate needs ngspice and device models; this is the cheap,
deterministic complement that runs everywhere. It assigns each power net its
nominal DC voltage (ground 0 V, USB VBUS 5 V, Li-ion VBAT 3.7 V, a ``VDD_<v>``
rail to ``<v>``) using ideal-regulator behaviour, and — the part ERC cannot do —
checks that **every rail a load depends on is actually driven by a regulator**.

A ``VDD_5`` net that loads reference but no regulator feeds (e.g. a boost rail
whose block is unrealized) is a real bug: the rail would float. This resolver
flags it, and can also emit ideal source cards so ngspice computes the rest.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from zaptrace.core.models import NetType

if TYPE_CHECKING:
    from zaptrace.core.models import Component, Design

# Input nets whose DC voltage is known by convention.
_INPUT_VOLTAGES: dict[str, float] = {"VBUS": 5.0, "VBAT": 3.7}
# Component types / value hints that drive a regulated rail.
_REGULATOR_TYPES = {"ldo", "regulator", "dcdc", "buck", "boost"}
_REGULATOR_VALUE_HINTS = ("TLV62569", "LDO_")


@dataclass
class DcBiasResult:
    """Net DC voltages and any rail that nothing drives."""

    net_voltages: dict[str, float] = field(default_factory=dict)
    rails_checked: list[str] = field(default_factory=list)
    undriven_rails: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.undriven_rails

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "net_voltages": self.net_voltages,
            "rails_checked": self.rails_checked,
            "undriven_rails": self.undriven_rails,
        }


def _rail_volts(net_name: str) -> float | None:
    """Inverse of the ``VDD_<v>`` rail convention: 'VDD_3V3' -> 3.3, 'VDD_5' -> 5."""
    if not net_name.startswith("VDD_"):
        return None
    token = net_name[len("VDD_") :].replace("V", ".", 1).rstrip(".")
    try:
        return float(token)
    except ValueError:
        return None


def _is_power_source(comp: Component) -> bool:
    """A regulator, or a connector that brings external power onto a rail."""
    if comp.type.lower() == "connector":
        return True
    if comp.type.lower() in _REGULATOR_TYPES:
        return True
    value = (comp.value or "").upper()
    return any(hint.upper() in value for hint in _REGULATOR_VALUE_HINTS)


def resolve_dc_bias(design: Design) -> DcBiasResult:
    """Assign nominal DC voltages and flag any rail with no regulator driving it."""
    result = DcBiasResult()

    # Nets a power source (regulator or input connector) touches; a rail among
    # them is driven.
    driven_nets: set[str] = set()
    source_refs = {c.ref for c in design.components.values() if _is_power_source(c)}
    for net in design.nets.values():
        if any(node.component_ref in source_refs for node in net.nodes):
            driven_nets.add(net.name)

    for net in design.nets.values():
        if net.type == NetType.GROUND or net.name.upper() in {"GND", "VSS"}:
            result.net_voltages[net.name] = 0.0
            continue
        if net.name in _INPUT_VOLTAGES:
            result.net_voltages[net.name] = _INPUT_VOLTAGES[net.name]
            continue
        rail_v = _rail_volts(net.name)
        if rail_v is None:
            continue
        result.rails_checked.append(net.name)
        result.net_voltages[net.name] = rail_v
        if net.name not in driven_nets:
            result.undriven_rails.append(net.name)

    return result


def behavioral_source_cards(design: Design) -> list[str]:
    """Emit ideal SPICE voltage-source cards for inputs and regulated rails.

    Lets the ngspice DC operating-point compute the rest of the netlist. Ground
    collapses to node 0; each driven net gets ``V<net> <node> 0 <volts>``. Only
    rails an actual regulator drives are sourced — an undriven rail is left for
    the resolver to report, not papered over with a source.
    """
    bias = resolve_dc_bias(design)
    driven_rails = set(bias.rails_checked) - set(bias.undriven_rails)
    cards: list[str] = []
    for net_name, volts in sorted(bias.net_voltages.items()):
        if math.isclose(volts, 0.0, rel_tol=0.0, abs_tol=1e-12):
            continue  # ground is node 0, no source needed
        if net_name in _INPUT_VOLTAGES or net_name in driven_rails:
            node = re.sub(r"(?a)\W", "_", net_name).strip("_") or "n"
            cards.append(f"V{node} {node} 0 {volts:g}")
    return cards
