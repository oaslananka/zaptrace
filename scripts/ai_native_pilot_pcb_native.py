#!/usr/bin/python3
# pyright: reportMissingImports=false
"""Independent KiCad pcbnew audit of one complete, still-unrouted placement."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pcbnew as pcb

from scripts.review_studio_schematic_pcb_parity import inspect


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(folder: Path) -> dict:
    source = folder / "placed-design.json"
    design = json.loads(source.read_text())
    components, nets = design["components"], design["nets"]
    name = design["meta"]["name"]
    board_file = folder / (name + ".kicad_pcb")
    sch_file = folder / (name + ".kicad_sch")
    if any(p.is_symlink() for p in (source, board_file, sch_file)):
        raise ValueError("Unsafe KiCad source symlink")
    board = pcb.LoadBoard(str(board_file))
    if board is None:
        raise ValueError("Native KiCad cannot open complete placement board")
    if len(list(board.GetTracks())) or len(list(board.Zones())):
        raise ValueError("Placement baseline must contain no copper routing/zones")
    refs = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
    if len(refs) != len(components) or set(refs) != set(components):
        raise ValueError("Missing, unknown or duplicate PCB footprint references")
    for ref, fp in refs.items():
        expected_id = "ZapTracePilot:ZT_" + ref
        if fp.GetFPIDAsString() == "zaptrace:" + components[ref]["type"]:
            fp.SetFPID(pcb.LIB_ID("ZapTracePilot", "ZT_" + ref))
        if fp.GetFPIDAsString() != expected_id:
            raise ValueError("Physical footprint library ID is not source linked")
    if not pcb.SaveBoard(str(board_file), board):
        raise ValueError("Native KiCad PCB save failed")
    board = pcb.LoadBoard(str(board_file))
    if board is None:
        raise ValueError("Native KiCad PCB cannot reopen")
    refs = {fp.GetReference(): fp for fp in board.GetFootprints()}
    if len(refs) != len(components) or set(refs) != set(components):
        raise ValueError("Native KiCad PCB lost a component on save/reload")
    expected_node_nets: dict[tuple[str, str], str] = {}
    for net in nets.values():
        for node in net["nodes"]:
            pair = node["component_ref"], node["pin_name"]
            if pair in expected_node_nets:
                raise ValueError("Source logical pin assigned to more than one net")
            expected_node_nets[pair] = net["name"]
    all_pads: set[str] = set()
    all_footprints: set[str] = set()
    inventory = []
    connected = 0
    for ref, fp in sorted(refs.items()):
        comp = components[ref]
        if fp.GetFPIDAsString() != "ZapTracePilot:ZT_" + ref:
            raise ValueError("Native PCB library identity changed after reload")
        if fp.GetValue() != (comp.get("value") or comp["type"] or ref):
            raise ValueError("Physical component value differs from schematic")
        if not fp.GetPath().AsString().startswith("/"):
            raise ValueError("Footprint missing schematic UUID association")
        source_pads = comp["footprint_def"]["pads"]
        pads = list(fp.Pads())
        if Counter(p.GetNumber() for p in pads) != Counter(p["id"] for p in source_pads):
            raise ValueError("Native PCB physical pad number inventory differs from source")
        uuid = fp.m_Uuid.AsString()
        if not uuid or uuid in all_footprints:
            raise ValueError("Duplicate physical footprint UUID")
        all_footprints.add(uuid)
        pad_list = []
        for pad in pads:
            number = pad.GetNumber()
            uid = pad.m_Uuid.AsString()
            if not uid or uid in all_pads:
                raise ValueError("Repeated/missing physical PCB pad UUID")
            all_pads.add(uid)
            logical = comp.get("package_pin_map", {}).get(number, number)
            expected = expected_node_nets.get((ref, logical), "")
            actual = pad.GetNetname() or ""
            if actual != expected:
                raise ValueError(f"PCB pad/net mismatch: {ref}.{number}: {actual!r} != {expected!r}")
            if number == "" and (pad.GetNetCode() != 0 or pad.GetAttribute() != pcb.PAD_ATTRIB_NPTH):
                raise ValueError("Anonymous mechanical pad assigned to copper")
            if actual:
                connected += 1
            position = pad.GetPosition()
            pad_list.append(
                {
                    "number": number,
                    "net": actual,
                    "uuid": uid,
                    "front_paste": pad.GetLayerSet().Contains(pcb.F_Paste),
                    "back_paste": pad.GetLayerSet().Contains(pcb.B_Paste),
                    "at_mm": [round(pcb.ToMM(position.x), 5), round(pcb.ToMM(position.y), 5)],
                }
            )
        position = fp.GetPosition()
        planned = design.get("placement", {}).get(ref)
        if not isinstance(planned, list) or len(planned) != 2:
            raise ValueError("Native placement lacks source coordinates")
        native_x, native_y = pcb.ToMM(position.x), pcb.ToMM(position.y)
        if abs(native_x - float(planned[0])) > 0.00001 or abs(native_y - float(planned[1])) > 0.00001:
            raise ValueError("KiCad coordinates differ from recorded source placement")
        if not (0 < native_x < 100 and 0 < native_y < 80):
            raise ValueError("Component center outside provisional board outline")
        inventory.append(
            {
                "ref": ref,
                "value": fp.GetValue(),
                "footprint": fp.GetFPIDAsString(),
                "uuid": uuid,
                "schematic_uuid_path": fp.GetPath().AsString(),
                "at_mm": [round(pcb.ToMM(position.x), 5), round(pcb.ToMM(position.y), 5)],
                "pads": sorted(pad_list, key=lambda x: (x["number"], x["uuid"])),
            }
        )
    if len(all_pads) != 100:
        raise ValueError("Expected 100 real physical pads across exact 12-part pilot")
    j1 = next(x for x in inventory if x["ref"] == "J1")
    s1 = [p for p in j1["pads"] if p["number"] == "S1"]
    if len(s1) != 4 or len({p["uuid"] for p in s1}) != 4 or any(p["net"] != "GND" for p in s1):
        raise ValueError("Each of four native physical USB S1 pads must have unique UUID and GND")
    cross = inspect(sch_file, board_file)
    if not (
        cross["linkage_uuid_verified"]
        and cross["component_fields_match"]
        and cross["component_counts"]["pcb"] == len(components)
        and cross["component_counts"]["schematic"] == len(components)
        and cross["native_pin_net_evidence"]["connected_schematic_pin_net_subset_verified"]
        and cross["native_pin_net_evidence"]["native_unexplained_net_label_disagreements"] == 0
        and cross["native_pin_net_evidence"]["matching_pin_identifiers_by_reference"] == 52
    ):
        raise ValueError("KiCad native schematic->PCB UUID, field or node parity failed")
    drc_out = folder / "native-pcb-drc.json"
    run = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--schematic-parity",
            "--exit-code-violations",
            "-o",
            str(drc_out),
            str(board_file),
        ],
        capture_output=True,
        text=True,
        timeout=140,
        check=False,
    )
    if not drc_out.is_file():
        raise ValueError("Independent native PCB DRC report unavailable")
    drc = json.loads(drc_out.read_text())
    if drc.get("$schema") != "https://schemas.kicad.org/drc.v1.json":
        raise ValueError("Unknown native KiCad DRC JSON format")
    for key in ("violations", "unconnected_items", "ignored_checks"):
        if not isinstance(drc.get(key), list):
            raise ValueError("Incomplete native DRC evidence: " + key)
    if not {"error", "warning", "exclusion"}.issubset(set(drc.get("included_severities", []))):
        raise ValueError("Native PCB DRC severity coverage incomplete")
    board.BuildConnectivity()
    if board.GetConnectivity().GetUnconnectedCount(False) != len(drc["unconnected_items"]):
        raise ValueError("Native pcbnew and KiCad CLI report different open connections")
    if not drc["unconnected_items"] or not drc["violations"]:
        raise ValueError("Cannot treat first placement as a clean routed board")
    return {
        "kicad_version": pcb.GetBuildVersion(),
        "summary": {
            "footprints": len(inventory),
            "physical_pads": len(all_pads),
            "named_net_pads": connected,
            "nets": len(nets),
            "unconnected": len(drc["unconnected_items"]),
            "drc_findings": len(drc["violations"]),
            "ignored_drc_checks": len(drc["ignored_checks"]),
            "tracks": 0,
            "zones": 0,
        },
        "footprints": inventory,
        "s1_four_separate_uuid_net_associations": s1,
        "uuid_path_parity": cross["native_uuid_linkage"],
        "schematic_connected_pin_net_subset_verified": True,
        "all_physical_nets_verified_against_source": True,
        "drc_violations_by_type": dict(Counter(x["type"] for x in drc["violations"])),
        "pcb_sha256": sha(board_file),
        "schematic_sha256": sha(sch_file),
        "pcb_drc_sha256": sha(drc_out),
        "drc_cli_exit": run.returncode,
        "physical_copper_routing_verified": False,
        "pcb_drc_passed": False,
        "fabrication_approved": False,
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    result = audit(root)
    (root / "native-placement-audit.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result["summary"]))
