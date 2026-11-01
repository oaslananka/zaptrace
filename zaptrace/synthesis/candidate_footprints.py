"""Narrow local pilot: geometry-backed passives and a documented 3.3V LDO.

Source pad geometry and the starter-library LDO pin map must agree with
actual connected terminals. Unreviewed sourcing/footprints do not grant
production or engineering approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from zaptrace.core.models import Design, NetNode, Pin, PinType
from zaptrace.ee.footprint_vendor import resolve_vendored_footprint
from zaptrace.ee.footprints import generate_footprint_for_component
from zaptrace.library.loader import LibraryLoader
from zaptrace.synthesis.requirements import Requirements

# Narrowly supported canonical two-terminal passive family only.
_PASSIVE_TYPES = frozenset({"resistor", "capacitor"})


@dataclass
class CandidateFootprints:
    qualified: list[dict[str, Any]] = field(default_factory=list)
    unresolved: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"qualified": self.qualified, "unresolved": self.unresolved}


def _qualify_ap2112_pilot(design: Design, requirements: Requirements) -> dict[str, Any] | None:
    """Substitute only the exact supported 3.3-V / 5-V USB-C pilot regulator.

    The manufacturer-linked starter record explicitly maps physical pads 1..5.
    Source trust-tier remains heuristic/unreviewed; selection cannot authorize
    procurement, manufacturing, thermal/current design, or simulation clearance.
    """
    if (
        not requirements.usb_c
        or requirements.rails_v != [3.3]
        or requirements.max_current_a is None
        or not 0 < requirements.max_current_a <= 0.5
    ):
        return None
    candidates = [c for c in design.components.values() if c.type == "ldo" and c.value == "LDO_3.3V"]
    if len(candidates) != 1:
        return None
    comp = candidates[0]
    if comp.footprint or comp.pins or comp.mpn or comp.footprint_def is not None:
        return None
    mapping = {"1": "VIN", "2": "GND", "3": "EN", "4": "NC", "5": "VOUT"}
    try:
        spec = LibraryLoader().get("ap2112k-3.3")
        geometry = resolve_vendored_footprint(spec.footprint)
    except (KeyError, ValueError, OSError):
        return None
    if (
        spec.mpn != "AP2112K-3.3TRG1"
        or spec.package_pin_map != mapping
        or geometry is None
        or sorted(pad.id for pad in geometry.pads) != sorted(mapping)
        or set(spec.pins) != set(mapping.values())
        or not spec.datasheet
        or not spec.provenance.get("review_status")
    ):
        return None
    required = {"VBUS": "1", "GND": "2", "VDD_3V3": "3"}
    if any(
        net_name not in design.nets
        or [(n.component_ref, n.pin_name) for n in design.nets[net_name].nodes if n.component_ref == comp.ref]
        != [(comp.ref, number)]
        for net_name, number in required.items()
    ):
        return None
    if any(
        node.component_ref == comp.ref
        for net_name, net in design.nets.items()
        if net_name not in required
        for node in net.nodes
    ):
        return None
    # All validation precedes mutation. Existing 3-pin pseudo-LDO wiring is
    # transformed to part-specific semantic pins using a documented unreviewed starter record,
    # and EN is explicitly tied to VBUS as an ALWAYS-ON design assumption.
    for net_name, number in required.items():
        for node in design.nets[net_name].nodes:
            if node.component_ref == comp.ref and node.pin_name == number:
                node.pin_name = {"1": "VIN", "2": "GND", "3": "VOUT"}[number]
    design.nets["VBUS"].nodes.append(NetNode(component_ref=comp.ref, pin_name="EN"))
    comp.value = spec.mpn
    comp.mpn = spec.mpn
    comp.footprint = spec.footprint
    comp.footprint_def = geometry
    comp.package_pin_map = mapping.copy()
    comp.pins = {
        name: Pin(name=name, type=PinType(info.get("type", "bidirectional"))) for name, info in spec.pins.items()
    }
    return {
        "ref": comp.ref,
        "mpn": spec.mpn,
        "footprint": spec.footprint,
        "pad_ids": sorted(mapping),
        "pin_map": mapping,
        "source": spec.datasheet,
        "trust": "unreviewed_starter_library_candidate_human_landing_pattern_review_required",
        "assumption": "AP2112 EN pin explicitly tied to VBUS for always-on operation",
    }


def qualify_candidate_footprints(design: Design, requirements: Requirements) -> CandidateFootprints:
    """Qualify two-pad passives and a narrowly supported library LDO.

    Do not call the generic ERC020 repair fallback for ICs: its SOT-23-3
    default is a package guess, not a device-backed VIN/GND/VOUT pin map.
    """
    report = CandidateFootprints()
    nodes: dict[str, set[str]] = {}
    for net in design.nets.values():
        for node in net.nodes:
            nodes.setdefault(node.component_ref, set()).add(node.pin_name)

    chosen = _qualify_ap2112_pilot(design, requirements)
    if chosen is not None:
        report.qualified.append(chosen)
    for ref, component in sorted(design.components.items()):
        if component.type not in _PASSIVE_TYPES or component.pins or component.footprint not in ("", "0402"):
            if not component.footprint:
                report.unresolved.append(
                    {
                        "ref": ref,
                        "reason": "no_part_specific_footprint_evidence",
                        "component_type": component.type,
                    }
                )
            continue
        pattern = component.footprint_def or generate_footprint_for_component("0402", component.type)
        pad_ids = [pad.id for pad in pattern.pads] if pattern is not None else []
        if sorted(pad_ids) != ["1", "2"] or nodes.get(ref) != {"1", "2"}:
            report.unresolved.append(
                {
                    "ref": ref,
                    "reason": "passive_pad_number_or_connectivity_inconsistent",
                    "component_type": component.type,
                }
            )
            continue
        # A two-terminal unlabeled passive supports a bounded canonical mapping
        # to geometry pad 1/2; NOT an evidence-backed orderable resistor/capacitor.
        component.footprint = "0402"
        component.footprint_def = pattern
        component.pins = {name: Pin(name=name, type=PinType.PASSIVE) for name in pad_ids}
        component.package_pin_map = {name: name for name in pad_ids}
        report.qualified.append(
            {
                "ref": ref,
                "footprint": "0402",
                "pad_ids": sorted(pad_ids),
                "source": "zaptrace.ee.footprints.generate_footprint_for_component",
                "trust": "generic_footprint_geometry_only_not_orderable_part",
            }
        )
    return report
