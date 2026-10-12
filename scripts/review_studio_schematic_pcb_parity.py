#!/usr/bin/python3
# pyright: reportMissingImports=false
"""Read-only native KiCad schematic/PCB parity audit. Never auto-sync pin mappings.

A reference match is NOT a UUID/linkage match. KiCad F8 forward-annotation is
the authoritative GUI workflow; this audit is an evidence gate, not F8.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as pcb


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def expected_symbol_paths(component: ET.Element) -> frozenset[str]:
    """Return full KiCad sheet-instance KIID paths for native unit UUIDs.

    A symbol can have multiple KiCad unit IDs. The XML netlist documents its
    sheet-instance path separately from each symbol KIID. No reference-based
    substitution is allowed. Return empty if evidence is incomplete/invalid.
    """
    node = component.find("sheetpath")
    path = node.get("tstamps", "") if node is not None else ""
    if not path.startswith("/") or (path != "/" and any(not UUID.fullmatch(part) for part in path[1:].split("/"))):
        return frozenset()
    units = (component.findtext("tstamps") or "").split()
    if (
        not units
        or len(units) != len(set(unit.lower() for unit in units))
        or any(not UUID.fullmatch(unit) for unit in units)
    ):
        return frozenset()
    # KiCad's pcbnew KIID_PATH serializes paths with a leading '/', without
    # a trailing '/' or empty path segments.
    prefix = path.rstrip("/").lower()
    return frozenset(prefix + "/" + unit.lower() for unit in units)


def verify_uuid_paths(
    schematic_paths: dict[str, frozenset[str]],
    pcb_paths: dict[str, str],
) -> dict:
    """Read-only UUID linkage report; wrong/missing paths never confer proof."""
    findings: list[dict[str, str]] = []
    validated = 0
    seen: dict[str, str] = {}
    # A single symbol instance KIID cannot be assigned to two components;
    # fail closed even if a corrupted XML export happens to assert it.
    owner: dict[str, str] = {}
    for reference, options in schematic_paths.items():
        for expected in options:
            if expected in owner and owner[expected] != reference:
                findings.append(
                    {
                        "reference": reference,
                        "issue": "duplicate_schematic_symbol_uuid_path",
                    }
                )
            owner[expected] = reference
    for reference in sorted(schematic_paths.keys() | pcb_paths.keys()):
        if reference not in schematic_paths or reference not in pcb_paths:
            # Already identified by component discrepancies; not linked.
            continue
        actual = pcb_paths[reference]
        expected = schematic_paths[reference]
        if not expected:
            findings.append({"reference": reference, "issue": "schematic_uuid_path_unavailable"})
        if not actual:
            findings.append({"reference": reference, "issue": "pcb_footprint_uuid_path_missing"})
            continue
        if not actual.startswith("/") or any(not UUID.fullmatch(part) for part in actual[1:].split("/")):
            findings.append(
                {
                    "reference": reference,
                    "issue": "pcb_footprint_uuid_path_malformed",
                }
            )
            continue
        actual = actual.lower()
        if actual in seen:
            findings.append(
                {
                    "reference": reference,
                    "issue": "duplicate_pcb_footprint_uuid_path",
                    "other_reference": seen[actual],
                }
            )
        else:
            seen[actual] = reference
        if actual not in expected:
            findings.append(
                {
                    "reference": reference,
                    "issue": "schematic_footprint_uuid_path_mismatch",
                }
            )
        elif expected:
            validated += 1
    complete = validated == len(schematic_paths) == len(pcb_paths) and not findings and len(schematic_paths) > 0
    return {
        "verified": complete,
        "verified_reference_count": validated,
        "expected_reference_count": len(schematic_paths),
        "status": "fully_linked_native_uuid_paths" if complete else "not_verified_native_uuid_paths",
        "findings": findings,
    }


def inspect(schematic: Path, board_path: Path) -> dict:
    schematic = schematic.resolve(strict=True)
    board_path = board_path.resolve(strict=True)
    for path, suffix in ((schematic, ".kicad_sch"), (board_path, ".kicad_pcb")):
        if path.suffix != suffix or not path.is_file() or not 100 < path.stat().st_size <= 10_000_000:
            raise ValueError("A valid native KiCad schematic and PCB (<=10 MB each) are required")
    source_hashes = {"schematic": digest(schematic), "pcb": digest(board_path)}
    cli = shutil.which("kicad-cli")
    if cli is None:
        raise RuntimeError("Native KiCad CLI unavailable; no parity claims permitted")
    with tempfile.TemporaryDirectory(prefix="zaptrace-pcb-parity-") as folder:
        report = Path(folder) / "schematic-netlist.xml"
        proc = subprocess.run(
            [cli, "sch", "export", "netlist", "--format", "kicadxml", "--output", str(report), str(schematic)],
            capture_output=True,
            text=True,
            timeout=80,
            check=False,
        )
        if proc.returncode or not report.is_file() or report.stat().st_size > 10_000_000:
            raise RuntimeError("Native KiCad XML netlist export failed; correspondence unverified")
        netlist = ET.parse(report).getroot()
    if netlist.tag != "export":
        raise RuntimeError("Unexpected KiCad netlist structure")
    schematic_components: dict[str, dict] = {}
    schematic_paths: dict[str, frozenset[str]] = {}
    for item in netlist.findall("./components/comp"):
        ref = item.get("ref")
        if not ref or ref in schematic_components:
            raise RuntimeError("Duplicate or unannotated schematic reference; no reliable parity")
        schematic_components[ref] = {
            "value": item.findtext("value", ""),
            "footprint": item.findtext("footprint", ""),
            "schematic_id": item.findtext("tstamps", ""),
        }
        schematic_paths[ref] = expected_symbol_paths(item)
    if not schematic_components:
        raise RuntimeError("No native schematic component instances")
    native = pcb.LoadBoard(str(board_path))
    if native is None:
        raise RuntimeError("Native KiCad could not open PCB")
    pcb_components: dict[str, dict] = {}
    actual_pads: dict[tuple[str, str], str] = {}
    repeated_pads = False
    pad_number_net_conflicts = 0
    actual_pad_count = 0
    linked_paths: dict[str, str] = {}
    for fp in native.GetFootprints():
        ref = fp.GetReference()
        if not ref or ref in pcb_components:
            raise RuntimeError("Duplicate or unannotated PCB reference; no reliable parity")
        pads = list(fp.Pads())
        for pad in pads:
            actual_pad_count += 1
            label = (ref, pad.GetNumber())
            if label in actual_pads:
                # Native KiCad pads can share identifiers (e.g. exposed tabs).
                # Same ID on different nets is an additional contradiction.
                repeated_pads = True
                if actual_pads[label] != pad.GetNetname():
                    pad_number_net_conflicts += 1
            actual_pads[label] = pad.GetNetname()
        pcb_components[ref] = {
            "value": fp.GetValue(),
            "footprint": fp.GetFPIDAsString(),
            "footprint_uuid": fp.m_Uuid.AsString(),
            "pcb_path": fp.GetPath().AsString(),
            "pad_count": len(pads),
        }
        linked_paths[ref] = fp.GetPath().AsString()
    discrepancies = []
    matched = sorted(schematic_components.keys() & pcb_components.keys())
    for ref in sorted(schematic_components.keys() - pcb_components.keys()):
        discrepancies.append({"reference": ref, "field": "component", "issue": "missing_from_pcb"})
    for ref in sorted(pcb_components.keys() - schematic_components.keys()):
        discrepancies.append({"reference": ref, "field": "component", "issue": "missing_from_schematic"})
    for ref in matched:
        for field in ("value", "footprint"):
            if schematic_components[ref][field] != pcb_components[ref][field]:
                discrepancies.append(
                    {
                        "reference": ref,
                        "field": field,
                        "issue": "schematic_pcb_mismatch",
                        "schematic": schematic_components[ref][field],
                        "pcb": pcb_components[ref][field],
                    }
                )
    schematic_pins: dict[tuple[str, str], str] = {}
    repeated_pins = False
    for net in netlist.findall("./nets/net"):
        name = net.get("name")
        if not name:
            raise RuntimeError("Schematic net has no identity")
        for pin in net.findall("node"):
            key = (pin.get("ref", ""), pin.get("pin", ""))
            if not key[0] or not key[1] or key in schematic_pins:
                repeated_pins = True
            schematic_pins[key] = name
    schematic_ids = set(schematic_pins)
    board_ids = set(actual_pads)
    overlapping = schematic_ids & board_ids
    different_net_labels = sorted(
        identity for identity in overlapping if schematic_pins[identity] != actual_pads[identity]
    )
    unmatched_schematic = sorted(schematic_ids - board_ids)
    unmatched_board = sorted(board_ids - schematic_ids)
    # Put same native pin IDs with different nets at the top of the
    # bounded interactive preview; they are more actionable than missing IDs.
    pin_issues = [
        {
            "reference": ref,
            "pin": pin,
            "issue": "same_pin_number_but_native_net_labels_differ",
            "schematic_net": schematic_pins[(ref, pin)],
            "pcb_net": actual_pads[(ref, pin)],
        }
        for ref, pin in different_net_labels
    ]
    pin_issues.extend(
        {"reference": ref, "schematic_pin": pin, "issue": "no_identical_pcb_pad_number"}
        for ref, pin in unmatched_schematic
    )
    pin_issues.extend(
        {"reference": ref, "pcb_pad": pad, "issue": "no_identical_schematic_pin_number"} for ref, pad in unmatched_board
    )
    exact_pin_ids = not repeated_pins and not repeated_pads and schematic_ids == board_ids
    exact_net_labels = exact_pin_ids and not different_net_labels
    pin_net_evidence = {
        "status": "strict_native_pin_number_and_net_label_comparison_not_electrical_signoff",
        "schematic_connected_pin_identifiers": len(schematic_ids),
        "unique_pcb_pad_identifiers": len(board_ids),
        "pcb_physical_pads": actual_pad_count,
        "matching_pin_identifiers_by_reference": len(overlapping),
        "schematic_pin_identifiers_missing_from_pcb": len(unmatched_schematic),
        "pcb_pad_identifiers_missing_from_schematic": len(unmatched_board),
        "native_net_label_differences_for_matching_pin_ids": len(different_net_labels),
        "duplicate_pcb_pad_numbers": repeated_pads,
        "conflicting_nets_on_duplicate_pcb_pad_numbers": pad_number_net_conflicts,
        "issue_samples": pin_issues[:24],
        "issue_count": len(pin_issues),
    }
    # KiCad F8 links by KIID path, not by reference. Prove the actual path
    # for every member with native schematic-exported UUIDs; otherwise block.
    uuid_evidence = verify_uuid_paths(schematic_paths, linked_paths)
    pin_net_status = (
        "exact_names_and_pad_ids_only_not_uuid_linkage"
        if exact_net_labels
        else "not_verified_requires_explicit_symbol_pin_to_pad_and_net_mapping"
    )
    if source_hashes != {"schematic": digest(schematic), "pcb": digest(board_path)}:
        raise RuntimeError("Source KiCad file changed during audit")
    return {
        "type": "NATIVE_SCHEMATIC_PCB_DRY_RUN_AUDIT",
        "source_sha256": source_hashes,
        "status": "read_only_findings_not_forward_annotation",
        "component_counts": {
            "schematic": len(schematic_components),
            "pcb": len(pcb_components),
            "shared_references": len(matched),
        },
        "schematic_net_count": len(netlist.findall("./nets/net")),
        "pcb_pad_count": actual_pad_count,
        "repeated_pcb_pad_numbers": repeated_pads,
        "schematic_connected_pin_count": len(schematic_pins),
        "component_field_discrepancies": discrepancies,
        "component_fields_match": len(discrepancies) == 0,
        "linkage_uuid_verified": uuid_evidence["verified"],
        "board_component_paths_present": bool(linked_paths) and all(linked_paths.values()),
        "native_uuid_linkage": uuid_evidence,
        "pin_net_correspondence": pin_net_status,
        "native_pin_net_evidence": pin_net_evidence,
        "source_files_modified": False,
        "automatic_sync_authorized": False,
        "electricallyApproved": False,
        "fabApproved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schematic", required=True, type=Path)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Report must use a fresh file; existing evidence cannot be overwritten")
        if not args.output.parent.is_dir() or args.output.parent.is_symlink():
            raise ValueError("Report parent folder invalid")
        sources = {args.schematic.resolve(strict=True), args.board.resolve(strict=True)}
        if args.output.resolve() in sources:
            raise ValueError("Cannot replace original KiCad sources with an audit")
        report = inspect(args.schematic, args.board)
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        args.output.chmod(0o600)
    except (ValueError, OSError, RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as error:
        print("SCHEMATIC PCB AUDIT BLOCKED:", str(error), file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
