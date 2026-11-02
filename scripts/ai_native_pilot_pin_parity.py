"""Fail-closed, source-linked native KiCad XML pin -> physical pad/net crosscheck.

Strictly limited to native KiCad exported connected net nodes and original
ZapTrace pad geometry. Whole-project pin function / physical readiness is NOT
certified, even when a scoped diagnostic is clean.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from zaptrace.core.models import Design


def crosscheck_native_pin_pad_net(design: Design, native_netlist: Path) -> dict[str, Any]:
    if (
        native_netlist.is_symlink()
        or not native_netlist.is_file()
        or not 100 < native_netlist.stat().st_size <= 12_000_000
    ):
        raise ValueError("Missing, unsafe or oversized native KiCad netlist")
    root = ET.parse(native_netlist).getroot()
    if root.tag != "export" or root.get("version") != "E":
        raise ValueError("Unsupported native KiCad XML netlist schema")

    reported: list[dict[str, str]] = []
    expected: Counter[tuple[str, str, str]] = Counter()
    physical_pad_sets: dict[str, set[str]] = {}
    for component in design.components.values():
        if component.footprint_def is None or not component.footprint_def.pads:
            reported.append({"code": "missing_physical_geometry", "ref": component.ref})
            continue
        pad_ids = [pad.id for pad in component.footprint_def.pads if pad.id]
        physical_pad_sets[component.ref] = set(pad_ids)
        if len(pad_ids) != len(set(pad_ids)):
            # Legitimate repeated numbered copper lands can exist. They require
            # stronger per-pad UUID/net verification, not this simplified oracle.
            reported.append({"code": "repeated_physical_pad_id_requires_more_evidence", "ref": component.ref})

    for _net_id, net in sorted(design.nets.items()):
        for node in net.nodes:
            component = design.get_component(node.component_ref)
            if component is None:
                reported.append({"code": "unknown_source_component", "ref": node.component_ref})
                continue
            if component.package_pin_map:
                matches = [pad_id for pad_id, logical in component.package_pin_map.items() if logical == node.pin_name]
            elif component.type in {"resistor", "capacitor"}:
                matches = [node.pin_name]
            else:
                reported.append(
                    {
                        "code": "missing_part_specific_pin_to_pad_map",
                        "ref": component.ref,
                        "pin": node.pin_name,
                    }
                )
                continue
            if not matches:
                reported.append(
                    {
                        "code": "unmapped_schematic_pin",
                        "ref": component.ref,
                        "pin": node.pin_name,
                    }
                )
            for number in matches:
                if number not in physical_pad_sets.get(component.ref, set()):
                    reported.append(
                        {
                            "code": "pin_maps_to_absent_physical_pad",
                            "ref": component.ref,
                            "pin": node.pin_name,
                            "pad": number,
                        }
                    )
                    continue
                expected[(component.ref, number, net.name)] += 1

    native: Counter[tuple[str, str, str]] = Counter()
    for net in root.findall("./nets/net"):
        name = net.get("name")
        if not name:
            raise ValueError("Native XML net without a name")
        for entry in net.findall("node"):
            ref, pad = entry.get("ref"), entry.get("pin")
            if not ref or not pad:
                raise ValueError("Native XML has an anonymous net node")
            native[(ref, pad, name)] += 1

    extra = native - expected
    missing = expected - native
    for code, diff in (("unexpected_native_net_node", extra), ("expected_net_node_missing_from_native", missing)):
        for (ref, pad, net), count in sorted(diff.items()):
            reported.append(
                {
                    "code": code,
                    "ref": ref,
                    "pad": pad,
                    "net": net,
                    "count": str(count),
                }
            )
    return {
        "status": "blocked" if reported else "scoped_pin_pad_net_match_not_engineering_approval",
        "original_net_count": len(design.nets),
        "native_net_count": len(root.findall("./nets/net")),
        "matched_native_nodes": sum((expected & native).values()),
        "native_nodes": sum(native.values()),
        "reasons": reported,
        "full_project_electrically_approved": False,
        "fabrication_approved": False,
    }
