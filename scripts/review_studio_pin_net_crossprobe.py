"""Strict scoped native KiCad exported schematic-pin ↔ PCB-pad/net diagnostics.

This is *not* whole-project parity, equivalence of schematic pin functions,
electrical certification, nor authenticated engineering approval.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

NO_NET = {"", "(no net)"}


def _schematic_nodes(export_path: Path, refs: set[str]) -> dict[str, dict[str, str | None]]:
    if export_path.is_symlink() or not export_path.is_file() or export_path.stat().st_size > 8_000_000:
        raise ValueError("Unsafe or oversized native KiCad netlist")
    root = ET.parse(export_path).getroot()
    if root.tag != "export" or root.get("version") != "E":
        raise ValueError("Unsupported KiCad native exported XML netlist")
    components: dict[str, set[str]] = {}
    for comp in root.findall("./components/comp"):
        ref = comp.get("ref")
        if not ref or ref in components:
            raise ValueError("Duplicate or missing native schematic component reference")
        pins: set[str] = set()
        for pin in comp.findall("./units/unit/pins/pin"):
            number = pin.get("num")
            if not number or number in pins:
                raise ValueError("Ambiguous, repeated or blank native schematic pin number")
            pins.add(number)
        components[ref] = pins

    result: dict[str, dict[str, str | None]] = {ref: {pin: None for pin in components.get(ref, set())} for ref in refs}
    names: set[str] = set()
    for net in root.findall("./nets/net"):
        name = net.get("name")
        if not name or name in names:
            raise ValueError("Missing or duplicated native schematic net name")
        names.add(name)
        nodes: set[tuple[str, str]] = set()
        for node in net.findall("./node"):
            ref, pin = node.get("ref"), node.get("pin")
            if not ref or not pin or (ref, pin) in nodes:
                raise ValueError("Duplicate or unnamed native netlist node")
            nodes.add((ref, pin))
            if ref not in components or pin not in components[ref]:
                raise ValueError("Native netlist node does not exist in component pin inventory")
            if ref in result:
                if result[ref][pin] is not None:
                    raise ValueError("Native pin belongs to several named schematic nets")
                result[ref][pin] = name
    return result


def _pcb_pads(board: dict, refs: set[str]) -> dict[str, dict[str, str]]:
    rows = board.get("pads")
    footprint_rows = board.get("footprints")
    if not isinstance(rows, list) or not isinstance(footprint_rows, list):
        raise ValueError("Missing actual native PCB pad/footprint inventory")
    footprint_count: dict[str, int] = {}
    for item in footprint_rows:
        if not isinstance(item, dict) or not isinstance(item.get("ref"), str):
            raise ValueError("Unsafe PCB footprint reference")
        ref = item["ref"]
        footprint_count[ref] = footprint_count.get(ref, 0) + 1
    if any(footprint_count.get(ref, 0) != 1 for ref in refs):
        raise ValueError("Moved PCB reference is missing or ambiguous")

    result: dict[str, dict[str, str]] = {ref: {} for ref in refs}
    for pad in rows:
        if not isinstance(pad, dict):
            raise ValueError("Invalid native PCB pad record")
        ref = pad.get("ref")
        if ref not in refs:
            continue
        number, name = pad.get("pad"), pad.get("net")
        if not isinstance(number, str) or not number or not isinstance(name, str) or number in result[ref]:
            raise ValueError("Unnumbered, duplicated or invalid native PCB pads")
        result[ref][number] = name
    for footprint in footprint_rows:
        ref = footprint["ref"]
        if ref in refs and footprint.get("pad_count") != len(result[ref]):
            raise ValueError("PCB pad count differs from native footprint inventory")
    return result


def scoped_pin_net_crossprobe(
    source_netlist: Path,
    proposed_netlist: Path,
    original_pcb: dict,
    proposed_pcb: dict,
    changed_refs: list[str],
    *,
    project_rules_crosslinked: bool,
) -> dict:
    if type(project_rules_crosslinked) is not bool:
        raise ValueError("Project context attestation must be an explicit boolean")
    if (
        not 1 <= len(changed_refs) <= 4
        or any(not isinstance(ref, str) or not ref for ref in changed_refs)
        or len(set(changed_refs)) != len(changed_refs)
    ):
        raise ValueError("Crossprobe requires unique source-verified changed footprints")
    refs = set(changed_refs)
    original_sch = _schematic_nodes(source_netlist, refs)
    proposed_sch = _schematic_nodes(proposed_netlist, refs)
    original_pads = _pcb_pads(original_pcb, refs)
    proposed_pads = _pcb_pads(proposed_pcb, refs)
    entries = []
    for ref in sorted(refs):
        for phase, pins, pads in (
            ("original", original_sch[ref], original_pads[ref]),
            ("proposed", proposed_sch[ref], proposed_pads[ref]),
        ):
            numbers = sorted(set(pins) | set(pads))
            if not numbers:
                entries.append(
                    {
                        "phase": phase,
                        "ref": ref,
                        "pin": None,
                        "schematic_net": None,
                        "pcb_net": None,
                        "status": "unverifiable",
                        "reason": "no_native_pin_or_pad_inventory",
                    }
                )
            for pin in numbers:
                schematic_net = pins.get(pin)
                pcb_net = pads.get(pin)
                if pin not in pins:
                    status, reason = "mismatch", "schematic_pin_missing_for_pcb_pad"
                elif pin not in pads:
                    status, reason = "mismatch", "pcb_pad_missing_for_schematic_pin"
                elif not schematic_net or schematic_net in NO_NET or not pcb_net or pcb_net in NO_NET:
                    status, reason = "unverifiable", "unnamed_or_unconnected_net"
                elif schematic_net != pcb_net:
                    status, reason = "mismatch", "native_net_name_conflict"
                else:
                    status, reason = "matched", "exact_pin_and_named_net"
                entries.append(
                    {
                        "phase": phase,
                        "ref": ref,
                        "pin": pin,
                        "schematic_net": schematic_net,
                        "pcb_net": pcb_net,
                        "status": status,
                        "reason": reason,
                    }
                )
    totals = {status: sum(x["status"] == status for x in entries) for status in ("matched", "mismatch", "unverifiable")}
    scoped_verified = (
        bool(entries) and totals["mismatch"] == 0 and totals["unverifiable"] == 0 and project_rules_crosslinked
    )
    blocked = {x["reason"] for x in entries if x["status"] != "matched"}
    if not project_rules_crosslinked:
        blocked.add("project_rule_context_not_crosslinked")
    return {
        "kind": "native_kicad_exported_pin_to_pad_named_net_diagnostics",
        "scope": (
            "Only moved reference/pin numbers and exact KiCad named net strings in both states; not whole PCB parity"
        ),
        "changed_refs": sorted(refs),
        "rows": entries,
        "totals": totals,
        "scoped_pin_net_consistent": scoped_verified,
        "project_rule_context_crosslinked": project_rules_crosslinked,
        "pcb_schematic_parity_verified": False,
        "electrically_approved": False,
        "full_project_covered": False,
        "reasons_when_unverified": sorted(blocked),
    }
