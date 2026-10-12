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
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pcbnew as pcb


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    for item in netlist.findall("./components/comp"):
        ref = item.get("ref")
        if not ref or ref in schematic_components:
            raise RuntimeError("Duplicate or unannotated schematic reference; no reliable parity")
        schematic_components[ref] = {
            "value": item.findtext("value", ""),
            "footprint": item.findtext("footprint", ""),
            "schematic_id": item.findtext("tstamps", ""),
        }
    if not schematic_components:
        raise RuntimeError("No native schematic component instances")
    native = pcb.LoadBoard(str(board_path))
    if native is None:
        raise RuntimeError("Native KiCad could not open PCB")
    pcb_components: dict[str, dict] = {}
    actual_pads: dict[tuple[str, str], str] = {}
    repeated_pads = False
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
                # Common KiCad tab/pin repetitions are valid PCB geometry
                # but cannot be used as proof of one-to-one pin mapping.
                repeated_pads = True
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
    exact_pin_ids = not repeated_pins and not repeated_pads and set(schematic_pins) == set(actual_pads)
    exact_net_labels = exact_pin_ids and all(
        schematic_pins[identity] == actual_pads[identity] for identity in schematic_pins
    )
    # Unlinked PCB paths or missing UUID evidence preclude proving that F8
    # forward-annotation will retain footprint identity. No ref-only guesses.
    link_proven = all(linked_paths.get(ref) and schematic_components[ref]["schematic_id"] for ref in matched) and len(
        matched
    ) == len(schematic_components) == len(pcb_components)
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
        "linkage_uuid_verified": False,
        "board_component_paths_present": bool(link_proven),
        "pin_net_correspondence": pin_net_status,
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
