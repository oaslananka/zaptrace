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


def _restore_verified_usb_c_art(folder: Path, components: dict, board: pcb.BOARD) -> dict:
    """Copy original vendor graphics only; never replace physical pads or PCB nets."""
    comp = components["J1"]
    if (
        comp.get("mpn") != "USB4105-15-A-120"
        or comp.get("footprint_def", {}).get("source")
        != "KiCad:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
    ):
        raise ValueError("Untrusted USB-C footprint source")
    source = (
        Path(__file__).resolve().parents[1]
        / "data/footprints/vendor"
        / "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal.kicad_mod"
    )
    expected_sha = "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
    if source.is_symlink() or sha(source) != expected_sha:
        raise ValueError("Pinned USB-C mechanical artwork changed")
    original = pcb.FootprintLoad(str(source.parent), source.stem)
    library_dir = folder / "ZapTracePilot.pretty"
    library_file = library_dir / "ZT_J1.kicad_mod"
    if library_dir.is_symlink() or library_file.is_symlink():
        raise ValueError("Unsafe generated USB-C footprint path")
    library = pcb.FootprintLoad(str(library_dir), "ZT_J1")
    matches = [fp for fp in board.GetFootprints() if fp.GetReference() == "J1"]
    if original is None or library is None or len(matches) != 1:
        raise ValueError("Missing USB-C geometry")
    instance = matches[0]
    artwork = list(original.GraphicalItems())
    if (
        len(artwork) != 7
        or list(library.GraphicalItems())
        or list(instance.GraphicalItems())
        or len(list(original.Pads())) != 22
        or len(list(library.Pads())) != 22
        or len(list(instance.Pads())) != 22
        or abs(instance.GetOrientationDegrees()) > 1e-6
    ):
        raise ValueError("Unexpected native USB-C artwork, pads or orientation")
    before = {pad.m_Uuid.AsString(): (pad.GetNumber(), pad.GetNetname()) for pad in instance.Pads()}
    for item in artwork:
        library.Add(item.Duplicate())
        placed = item.Duplicate()
        placed.Move(instance.GetPosition())
        instance.Add(placed)
    pcb.FootprintSave(str(library_dir), library)
    saved = pcb.FootprintLoad(str(library_dir), "ZT_J1")
    if (
        saved is None
        or len(list(saved.GraphicalItems())) != 7
        or before != {pad.m_Uuid.AsString(): (pad.GetNumber(), pad.GetNetname()) for pad in instance.Pads()}
    ):
        raise ValueError("Native USB-C artwork copy damaged footprint parity")
    return {
        "source_sha256": expected_sha,
        "graphical_items": 7,
        "three_d_model_qualified": False,
        "manufacturer_mating_approved": False,
    }


def assert_native_u3_manufacturer_geometry(footprint: pcb.FOOTPRINT) -> None:
    """Fail closed on U3 source copper/stencil loss, even with an unchanged DRC."""
    source = (
        Path(__file__).resolve().parents[1]
        / "data/footprints/vendor/Sensirion_DFN-8-1EP_2.5x2.5mm_P0.5mm_EP1.1x1.7mm.kicad_mod"
    )
    digest = "2380f3b4d6982902f05e8940603f19f7cfbc1bdfd6ae0f78ebd281c1a3f30a8f"
    if source.is_symlink() or sha(source) != digest:
        raise ValueError("SHT31 original manufacturer pad geometry checksum changed")
    original = pcb.FootprintLoad(str(source.parent), source.stem)
    if original is None:
        raise ValueError("Cannot load pinned SHT31 KiCad footprint")
    original_pads, placed_pads = list(original.Pads()), list(footprint.Pads())
    source_ids = Counter(pad.GetNumber() for pad in original_pads)
    if (
        len(original_pads) != 10
        or len(placed_pads) != 10
        or Counter(pad.GetNumber() for pad in placed_pads) != source_ids
    ):
        raise ValueError("SHT31 source paste-only stencil pad is missing or duplicated")

    def polygon_vertices(pad: pcb.PAD) -> tuple[tuple[int, int], ...]:
        polygon = pad.GetCustomShapeAsPolygon()
        if polygon.OutlineCount() != 1:
            raise ValueError("SHT31 custom pad polygon outline changed")
        outline = polygon.Outline(0)
        return tuple((outline.CPoint(i).x, outline.CPoint(i).y) for i in range(outline.PointCount()))

    for name in ("", "9"):
        source_pad = next(pad for pad in original_pads if pad.GetNumber() == name)
        native_pad = next(pad for pad in placed_pads if pad.GetNumber() == name)
        for layer in (pcb.F_Cu, pcb.B_Cu, pcb.F_Mask, pcb.B_Mask, pcb.F_Paste, pcb.B_Paste):
            if source_pad.GetLayerSet().Contains(layer) != native_pad.GetLayerSet().Contains(layer):
                raise ValueError(f"SHT31 source copper/stencil layers changed on pad {name!r}")
        if (
            native_pad.GetShape() != source_pad.GetShape()
            or native_pad.GetSize() != source_pad.GetSize()
            or polygon_vertices(native_pad) != polygon_vertices(source_pad)
        ):
            raise ValueError(f"SHT31 source copper/stencil polygon changed on pad {name!r}")
        if name == "" and (
            native_pad.GetNetCode() != 0
            or native_pad.GetLayerSet().Contains(pcb.F_Cu)
            or not native_pad.GetLayerSet().Contains(pcb.F_Paste)
        ):
            raise ValueError("SHT31 source stencil-only pad cannot carry a net or copper")


_PILOT_0402 = {f"R{i}" for i in range(1, 6)} | {f"C{i}" for i in range(1, 4)}


def _preserve_source_bounded_passive_courtyards(folder: Path, components: dict, board: pcb.BOARD) -> dict:
    """Copy candidate-derived original courtyard graphics; never alter native pads/nets."""
    library_dir = folder / "ZapTracePilot.pretty"
    if library_dir.is_symlink():
        raise ValueError("Unsafe synthetic pilot KiCad footprint directory")
    footprints = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
    if not _PILOT_0402.issubset(footprints):
        raise ValueError("Missing pilot passive physical components")
    for ref in sorted(_PILOT_0402):
        comp = components[ref]
        model = comp.get("footprint_def") or {}
        if (
            comp.get("type") not in ("resistor", "capacitor")
            or model.get("source") != "IPC-7351B"
            or model.get("courtyard") != [2.0, 1.5]
            or comp.get("footprint") != "ZapTracePilot:ZT_" + ref
        ):
            raise ValueError(f"Source-bound 0402 courtyard identity invalid: {ref}")
        library_file = library_dir / ("ZT_" + ref + ".kicad_mod")
        if library_file.is_symlink():
            raise ValueError("Unsafe local 0402 library file")
        source = pcb.FootprintLoad(str(library_dir), "ZT_" + ref)
        placed = footprints[ref]
        if source is None:
            raise ValueError(f"Missing local 0402 footprint source: {ref}")
        art = list(source.GraphicalItems())
        if (
            len(art) != 1
            or art[0].GetLayer() != pcb.F_CrtYd
            or len(list(placed.GraphicalItems())) != 0
            or len(list(source.Pads())) != 2
            or len(list(placed.Pads())) != 2
        ):
            raise ValueError(f"Untrusted 0402 courtyard geometry: {ref}")
        # Verify the source rectangle really matches the bounded candidate.
        rect = art[0]
        endpoints = sorted(
            (round(pcb.ToMM(point.x), 5), round(pcb.ToMM(point.y), 5)) for point in (rect.GetStart(), rect.GetEnd())
        )
        if endpoints != [(-1.0, -0.75), (1.0, 0.75)] or abs(pcb.ToMM(rect.GetWidth()) - 0.05) > 1e-6:
            raise ValueError(f"0402 courtyard differs from model-specified 2x1.5 mm: {ref}")
        before = {pad.m_Uuid.AsString(): (pad.GetNumber(), pad.GetNetname()) for pad in placed.Pads()}
        original_art = rect.Duplicate()
        original_art.Move(placed.GetPosition())
        placed.Add(original_art)
        after = {pad.m_Uuid.AsString(): (pad.GetNumber(), pad.GetNetname()) for pad in placed.Pads()}
        if before != after:
            raise ValueError(f"0402 courtyard propagation altered pad-net identity: {ref}")
    return {
        "refs": sorted(_PILOT_0402),
        "source": "canonical_ipc_0402_model_and_KiCad_KLC_F5.3_not_manufacturer_approved",
        "courtyard_mm": [2.0, 1.5],
        "min_pad_edge_margin_mm": 0.15,
        "fabrication_approved": False,
    }


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
        expected_id = components[ref]["footprint"]
        if not components[ref].get("footprint_asset") and fp.GetFPIDAsString() == "zaptrace:" + components[ref]["type"]:
            fp.SetFPID(pcb.LIB_ID("ZapTracePilot", "ZT_" + ref))
        if fp.GetFPIDAsString() != expected_id:
            raise ValueError("Physical footprint library ID is not source linked")
    vendor_art = _restore_verified_usb_c_art(folder, components, board)
    passive_courtyards = _preserve_source_bounded_passive_courtyards(folder, components, board)
    if not pcb.SaveBoard(str(board_file), board):
        raise ValueError("Native KiCad PCB save failed")
    board = pcb.LoadBoard(str(board_file))
    if board is None:
        raise ValueError("Native KiCad PCB cannot reopen")
    refs = {fp.GetReference(): fp for fp in board.GetFootprints()}
    if len(refs) != len(components) or set(refs) != set(components):
        raise ValueError("Native KiCad PCB lost a component on save/reload")
    graphics = list(refs["J1"].GraphicalItems())
    edge_lines = [item for item in graphics if isinstance(item, pcb.PCB_SHAPE) and item.GetLayer() == pcb.Dwgs_User]
    if len(graphics) != 7 or len(edge_lines) != 1:
        raise ValueError("USB-C drawing was lost in native KiCad PCB")
    edge = edge_lines[0]
    edge_endpoints = sorted(
        (round(pcb.ToMM(point.x), 5), round(pcb.ToMM(point.y), 5)) for point in (edge.GetStart(), edge.GetEnd())
    )
    if edge_endpoints != [(45.0, 80.0), (55.0, 80.0)]:
        raise ValueError("Verified USB-C PCB edge art does not coincide with outline")
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
        if fp.GetFPIDAsString() != comp["footprint"]:
            raise ValueError("Native PCB library identity changed after reload")
        if fp.GetValue() != (comp.get("value") or comp["type"] or ref):
            raise ValueError("Physical component value differs from schematic")
        if not fp.GetPath().AsString().startswith("/"):
            raise ValueError("Footprint missing schematic UUID association")
        source_pads = comp["footprint_def"]["pads"]
        pads = list(fp.Pads())
        # U3 has a tenth *unnumbered* F.Paste-only manufacturing primitive,
        # absent from the canonical electrical footprint model by design.
        stencil_pads = [p for p in pads if ref == "U3" and p.GetNumber() == ""]
        if ref == "U3":
            assert_native_u3_manufacturer_geometry(fp)
        if ref == "U2" and (
            comp.get("footprint_asset") != "stm32-lqfp48"
            or any(
                sum(p.GetNumber() == number for p in pads) != 1
                or next(p for p in pads if p.GetNumber() == number).GetNetCode() != 0
                for number in ("5", "6")
            )
        ):
            raise ValueError("Unmodeled STM32 PD0/PD1 copper pads must stay netless")
        if ref in ("U1", "U2") and not any(item.GetLayer() == pcb.F_CrtYd for item in fp.GraphicalItems()):
            raise ValueError("Pinned U1/U2 original courtyard is absent")
        if ref in _PILOT_0402:
            drawings = [item for item in fp.GraphicalItems() if item.GetLayer() == pcb.F_CrtYd]
            if len(drawings) != 1:
                raise ValueError(f"0402 source courtyard lost in KiCad roundtrip: {ref}")
            rectangle = drawings[0]
            center = fp.GetPosition()
            relative = sorted(
                (
                    round(pcb.ToMM(point.x - center.x), 5),
                    round(pcb.ToMM(point.y - center.y), 5),
                )
                for point in (rectangle.GetStart(), rectangle.GetEnd())
            )
            if relative != [(-1.0, -0.75), (1.0, 0.75)]:
                raise ValueError(f"0402 source courtyard dimension changed after reload: {ref}")
        physical_pads = [p for p in pads if p not in stencil_pads]
        if Counter(p.GetNumber() for p in physical_pads) != Counter(p["id"] for p in source_pads):
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
            if number == "" and ref != "U3" and (pad.GetNetCode() != 0 or pad.GetAttribute() != pcb.PAD_ATTRIB_NPTH):
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
    if len(all_pads) != 101:
        raise ValueError("Expected 100 source physical pads plus one U3 paste-only pad")
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
            "physical_pads": len(all_pads) - 1,
            "native_pad_objects": len(all_pads),
            "non_copper_stencil_only": 1,
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
        "usb_c_manufacturer_art": vendor_art,
        "passive_source_courtyards": passive_courtyards,
    }


if __name__ == "__main__":
    root = Path(sys.argv[1]).resolve()
    result = audit(root)
    (root / "native-placement-audit.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps(result["summary"]))
