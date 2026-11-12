#!/usr/bin/python3
"""LOCAL-ONLY engineering review of *actual* KiCad PCB geometry.

Use Ubuntu's Python installed alongside pcbnew 10.x. Reads a KiCad PCB,
plots its unmodified native SVG layers, loads native pad/net coordinates,
and runs KiCad native DRC. Never sends or modifies board data; no fab signoff.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from review_studio_local_csp import apply_offline_csp
from review_studio_local_file_guard import read_regular_bytes


def safe_inline_json(obj: object) -> str:
    return (
        json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def parse_native_drc(report: str) -> list[dict]:
    """Native KiCad text DRC findings, retaining raw messages and coordinates."""
    findings = []
    for m in re.finditer(r"^\[([^\]]+)\]:\s*(.+)$", report, re.M):
        end = report.find("\n[", m.end())
        block = report[m.end() : end if end != -1 else len(report)]
        if m.group(1) == "footprint_library_mismatch":
            # This can still be a genuine project-level problem: do NOT skip it.
            pass
        severity = re.search(r"^\s*(?:Rule: .*|Local override);\s*(error|warning)$", block, re.M)
        coords = re.search(r"@\((-?\d+(?:\.\d+)?) mm,\s*(-?\d+(?:\.\d+)?) mm\)", block)
        findings.append(
            {
                "rule": m.group(1),
                "message": m.group(2).strip(),
                "severity": severity.group(1) if severity else "unknown",
                "x": float(coords.group(1)) if coords else None,
                "y": float(coords.group(2)) if coords else None,
                "objects": [x.strip() for x in block.splitlines() if " mm): " in x][:3],
            }
        )
    return findings


def validated_native_drc(report: str) -> list[dict]:
    """Refuse success if native KiCad counts and parsed findings disagree."""
    findings = parse_native_drc(report)
    rules = re.search(r"\*\* Found (\d+) DRC violations \*\*", report)
    opened = re.search(r"\*\* Found (\d+) unconnected pads \*\*", report)
    if rules is None or opened is None:
        raise RuntimeError("Native KiCad DRC counters absent; refusing a false clean state")
    expected_rules, expected_open = int(rules.group(1)), int(opened.group(1))
    actual_open = sum(item["rule"] == "unconnected_items" for item in findings)
    actual_rules = len(findings) - actual_open
    if actual_rules != expected_rules or actual_open != expected_open:
        raise RuntimeError(
            f"Native DRC counters disagree with parsed findings: "
            f"rules {actual_rules}/{expected_rules}, open {actual_open}/{expected_open}"
        )
    return findings


def _model_file_probe(source: str, board_dir: Path) -> tuple[bool, bool]:
    """Conservative file existence only, NOT trusted 3D/mechanical validation.

    KiCad 10 can map older KiCad-version model variable names to its current
    model root. A same-stem STEP file is a *candidate*, not auto-approved.
    """
    match = re.fullmatch(r"\$\{KICAD(?:\d+)?_3DMODEL_DIR\}/(.+)", source)
    project = re.fullmatch(r"\$\{KIPRJMOD\}/(.+)", source)
    candidate: Path | None = None
    if match:
        relative = Path(match.group(1))
        root = Path(os.environ.get("KICAD10_3DMODEL_DIR") or "/usr/share/kicad/3dmodels")
        if not relative.is_absolute() and ".." not in relative.parts:
            candidate = root / relative
    elif project:
        relative = Path(project.group(1))
        if not relative.is_absolute() and ".." not in relative.parts:
            candidate = board_dir / relative
    # Deliberately do not expand arbitrary variables, user-home or filesystem
    # paths into source-linked browser evidence. Unknown is NOT a passing check.
    if candidate is None:
        return False, False
    try:
        present = candidate.is_file()
        alternative = candidate.with_suffix(".step").is_file() if candidate.suffix.lower() == ".wrl" else False
        return present, alternative and not present
    except (OSError, ValueError):
        return False, False


def _model_inventory(model_links: dict[str, list[str]], board_dir: Path) -> dict:
    rows = []
    for reference, models in sorted(model_links.items()):
        for source in models:
            present, same_stem_step = _model_file_probe(source, board_dir)
            rows.append(
                {"reference": reference, "declared_file_present": present, "same_stem_step_candidate": same_stem_step}
            )
    unresolved = sorted({row["reference"] for row in rows if not row["declared_file_present"]})
    unmodelled = sorted(ref for ref, refs in model_links.items() if not refs)
    return {
        "footprints": len(model_links),
        "declared_references": len(rows),
        "present_files": sum(row["declared_file_present"] for row in rows),
        "unresolved_refs": unresolved,
        "without_model_refs": unmodelled,
        "same_stem_step_candidates": sorted({row["reference"] for row in rows if row["same_stem_step_candidate"]}),
        "scope": "file-presence-only; mechanical geometry, model alignment and fabrication NOT verified",
        "model_geometry_approved": False,
    }


def _read_kicad(board_path: Path) -> dict:
    # Do not pip-import pcbnew from the wrong interpreter: this is the native oracle.
    try:
        import pcbnew as pcb  # type: ignore[reportMissingImports]  # system KiCad 10 Python binding
    except ImportError as exc:
        raise RuntimeError("Native pcbnew unavailable; use /usr/bin/python3 with KiCad installed") from exc
    board = pcb.LoadBoard(str(board_path))
    bounds = board.GetBoardEdgesBoundingBox()
    x0, y0 = pcb.ToMM(bounds.GetX()), pcb.ToMM(bounds.GetY())
    w, h = pcb.ToMM(bounds.GetWidth()), pcb.ToMM(bounds.GetHeight())
    if not (0 < w < 2000 and 0 < h < 2000):
        raise ValueError("Unsupported / missing Edge.Cuts board outline")
    footprints = []
    pads = []
    model_links: dict[str, list[str]] = {}
    for fp in sorted(board.GetFootprints(), key=lambda x: x.GetReference()):
        pos = fp.GetPosition()
        f = {
            "ref": fp.GetReference(),
            "value": fp.GetValue(),
            "footprint": fp.GetFPIDAsString(),
            "x": round(pcb.ToMM(pos.x), 5),
            "y": round(pcb.ToMM(pos.y), 5),
            "pad_count": len(list(fp.Pads())),
        }
        footprints.append(f)
        model_links[f["ref"]] = [str(model.m_Filename) for model in fp.Models() if model.m_Filename]
        for pad in fp.Pads():
            point = pad.GetPosition()
            pads.append(
                {
                    "ref": f["ref"],
                    "pad": pad.GetNumber(),
                    "net": pad.GetNetname() or "(no net)",
                    "x": round(pcb.ToMM(point.x), 5),
                    "y": round(pcb.ToMM(point.y), 5),
                    "size": [round(pcb.ToMM(pad.GetSize().x), 5), round(pcb.ToMM(pad.GetSize().y), 5)],
                }
            )
    copper = []
    for track in board.GetTracks():
        start, end = track.GetStart(), track.GetEnd()
        copper.append(
            {
                "net": track.GetNetname() or "(no net)",
                "layer": track.GetLayerName(),
                "start": [round(pcb.ToMM(start.x), 5), round(pcb.ToMM(start.y), 5)],
                "end": [round(pcb.ToMM(end.x), 5), round(pcb.ToMM(end.y), 5)],
                "width": round(pcb.ToMM(track.GetWidth()), 5),
                "via": isinstance(track, pcb.PCB_VIA),
            }
        )
    return {
        "copper": copper,
        "origin": [round(x0, 4), round(y0, 4)],
        "size": [round(w, 4), round(h, 4)],
        "footprints": footprints,
        "model_assets": _model_inventory(model_links, board_path.parent),
        "pads": pads,
        "tracks": len(list(board.GetTracks())),
        "zones": len(list(board.Zones())),
        "kicad": pcb.GetBuildVersion(),
    }


def _export_layer(cli: str, board: Path, output: Path, layer: str) -> tuple[str, tuple[float, float]]:
    # Read-only export from actual native KiCad; output in a separate build dir.
    cmd = [
        cli,
        "pcb",
        "export",
        "svg",
        "--mode-single",
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
        "--layers",
        layer,
        "--output",
        str(output),
        str(board),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0 or not output.is_file():
        raise RuntimeError(f"Native KiCad could not plot {layer}: {res.stderr[:550]}")
    data = output.read_bytes()
    if b"<svg" not in data[:600]:
        raise RuntimeError(f"KiCad output for {layer} is not SVG")
    text = data.decode("utf-8")
    m = re.search(r'viewBox="0\.0000 0\.0000 ([\d.]+) ([\d.]+)"', text)
    if not m:
        raise RuntimeError(f"Unexpected native KiCad SVG viewBox on {layer}")
    return (
        "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii"),
        (float(m.group(1)), float(m.group(2))),
    )


def native_erc_summary(report: str) -> tuple[int, int, int]:
    """Extract KiCad 10 ERC counts; reject unknown report grammar."""
    groups = re.findall(r"\*\* ERC messages: (\d+)\s+Errors (\d+)\s+Warnings (\d+)", report)
    if not groups:
        raise RuntimeError("Native KiCad ERC report counters absent; not claiming an ERC pass")
    total = sum(int(m[0]) for m in groups)
    errors = sum(int(m[1]) for m in groups)
    warnings = sum(int(m[2]) for m in groups)
    if total != errors + warnings:
        raise RuntimeError("Native KiCad ERC report counters inconsistent")
    return total, errors, warnings


def _run_erc(cli: str, schematic: Path, output: Path) -> dict:
    report = output / "native-erc.rpt"
    r = subprocess.run(
        [cli, "sch", "erc", "--exit-code-violations", "--output", str(report), str(schematic.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    if r.returncode not in (0, 5) or not report.is_file():
        raise RuntimeError(f"Native KiCad ERC failed: {r.returncode}: {r.stderr[:550]}")
    total, errors, warnings = native_erc_summary(report.read_text(encoding="utf-8"))
    if (total > 0) != (r.returncode == 5):
        raise RuntimeError("Native KiCad ERC exit code does not match its report")
    return {
        "state": "reported" if total else "no_reported_findings",
        "count": total,
        "errors": errors,
        "warnings": warnings,
        "scope": "Only enabled KiCad ERC checks; ignored rule categories may exist.",
    }


def schematic_symbols(source: str, *, allow_empty: bool = False) -> dict[str, dict]:
    """Get unique root-sheet symbol anchors from actual KiCad S-expressions.

    This deliberately supports one sheet only. It skips the separate `lib_symbols`
    definition and checks balanced parentheses, quotes and reference identity.
    """
    symbols = {}
    starts = list(re.finditer(r"(?m)^  \(symbol\s*$", source))
    for found in starts:
        start = found.start() + 2
        level, quoted, escaped, end = 0, False, False, None
        for index in range(start, len(source)):
            ch = source[index]
            if escaped:
                escaped = False
            elif quoted and ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = not quoted
            elif not quoted and ch == "(":
                level += 1
            elif not quoted and ch == ")":
                level -= 1
                if level == 0:
                    end = index + 1
                    break
        if end is None or quoted or level:
            raise RuntimeError("Malformed native schematic symbol S-expression")
        block = source[start:end]
        ref = re.search(r'\(property\s+"Reference"\s+"([^"\\]+)"', block)
        position = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
        if not ref or not position:
            raise RuntimeError("Native schematic instance lacks a reference or position")
        name = ref.group(1)
        if name in symbols:
            raise RuntimeError(f"Ambiguous repeated schematic reference: {name}")
        symbols[name] = {
            "ref": name,
            "x": float(position.group(1)),
            "y": float(position.group(2)),
            "rotation": float(position.group(3)),
        }
    if not symbols and not allow_empty:
        raise RuntimeError("No single-sheet schematic symbol instances found")
    return symbols


def schematic_pin_anchors(source: str, symbols: dict[str, dict], nodes: list[dict]) -> list[dict]:
    """Read *real native KiCad library pin endpoints*, not guessed geometry.

    Scope: single sheet, unrotated and unmirrored schematic instances. For
    unsupported transforms fail closed rather than plot misplaced markers.
    """
    ref_map = {}
    symbol_instances = list(re.finditer(r"(?m)^  \(symbol\s*$", source))
    for m in symbol_instances:
        start = m.end()
        next_symbol = source.find("\n  (symbol\n", start)
        end = next_symbol if next_symbol != -1 else len(source)
        block = source[start:end]
        ref = re.search(r'\(property\s+"Reference"\s+"([^"\\]+)"', block)
        lib = re.search(r'\(lib_id\s+"([^"\\]+)"\)', block)
        if not ref or not lib:
            raise RuntimeError("Native schematic lacks reference/library ID for pin anchors")
        if ref.group(1) not in symbols or ref.group(1) in ref_map:
            raise RuntimeError("Missing or duplicate native instance when locating pin anchors")
        ref_map[ref.group(1)] = lib.group(1)
        if re.search(r"\(mirror\s+", block):
            raise RuntimeError("Mirrored schematic symbols not yet supported for pin-accurate overlay")
    if set(ref_map) != set(symbols):
        raise RuntimeError("Schematic pin reference list differs from symbol instances")
    # KiCad XML exposes *physical* pin numbers (e.g. U1.2), while source
    # symbols name their logical functions (e.g. U1.VCC). Joining those
    # strings directly is incorrect and silently breaks supplier-pin proof.
    # Require the exact physical native pin key and validate XML pinfunction
    # against the actual embedded KiCad symbol's pin name.
    native_nodes = {(item["ref"], item.get("physical_pin", item["pin"])): item for item in nodes}
    if len(native_nodes) != len(nodes):
        raise RuntimeError("KiCad XML netlist includes duplicated physical pin numbers")
    pins = []
    for ref, lib in ref_map.items():
        inst = symbols[ref]
        if abs(inst["rotation"]) > 0.000001:
            raise RuntimeError("Rotated native schematic instance requires coordinate transform review")
        # The generator uses a unique per-ref embedded library symbol.
        pattern = r'(?m)^    \(symbol "' + re.escape(lib) + r'"\s*$'
        match = re.search(pattern, source)
        if match is None:
            raise RuntimeError(f"Native KiCad embedded library symbol missing for {ref}")
        # End before next same-indentation library symbol or top-level instances.
        next_lib = re.search(r'(?m)^    \(symbol "', source[match.end() :])
        next_top = re.search(r"(?m)^  \(symbol\s*$", source[match.end() :])
        candidates = [match.end() + m.start() for m in (next_lib, next_top) if m]
        stop = min(candidates) if candidates else len(source)
        block = source[match.end() : stop]
        pin_pattern = (
            r"\(pin\s+\w+\s+line\s+\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\)"
            r'.*?\(name\s+"([^"\\]+)"'
            r'.*?\(number\s+"([^"\\]+)"'
        )
        found = list(re.finditer(pin_pattern, block, re.S))
        if not found:
            raise RuntimeError(f"No native numbered pin anchors on {lib}")
        native_names = [m.group(4) for m in found]
        for match_pin in found:
            local_x, local_y = float(match_pin.group(1)), float(match_pin.group(2))
            name, physical = match_pin.group(4), match_pin.group(5)
            key = (ref, physical)
            entry = native_nodes.get(key)
            if entry is None:
                raise RuntimeError(f"KiCad physical pin {ref}.{physical} ({name}) absent from native XML netlist")
            # Eeschema may qualify a name with its physical number to avoid
            # duplicate pinfunctions (notably four ESP32 GND pads). This
            # correspondence is checked, never inferred from a net label.
            function = entry.get("pinfunction", "")
            if function and function not in (name, name + "_" + physical):
                raise RuntimeError(f"KiCad XML pinfunction disagrees with embedded {ref}.{physical}")
            if any(p["ref"] == ref and p["physical_pin"] == physical for p in pins):
                raise RuntimeError(f"Duplicate embedded physical pin {ref}.{physical}")
            identity = name if native_names.count(name) == 1 else name + "_" + physical
            if any(p["ref"] == ref and p["logical_pin"] == identity for p in pins):
                raise RuntimeError(f"Ambiguous embedded logical pin anchor {ref}.{identity}")
            pins.append(
                {
                    "ref": ref,
                    "logical_pin": identity,
                    "canonical_pin": name,
                    "physical_pin": physical,
                    "pinfunction": function,
                    "net": entry["net"],
                    "x": round(inst["x"] + local_x, 5),
                    "y": round(inst["y"] - local_y, 5),
                    "source": "embedded KiCad library pin name/number/at + native Eeschema XML physical pin",
                }
            )
    if {(p["ref"], p["physical_pin"]) for p in pins} != set(native_nodes):
        raise RuntimeError("KiCad physical pin anchors differ from native Eeschema XML netlist")
    return pins


def _read_schematic_netlist(cli: str, schematic: Path, output: Path) -> dict:
    """Use the native Eeschema netlist for crossprobe reference identity."""
    xml_path = output / "native-schematic-netlist.xml"
    result = subprocess.run(
        [cli, "sch", "export", "netlist", "--format", "kicadxml", "--output", str(xml_path), str(schematic.resolve())],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not xml_path.is_file():
        raise RuntimeError(f"Native Eeschema netlist unavailable: {result.stderr[:400]}")
    xml_data = xml_path.read_bytes()
    if b"<!DOCTYPE" in xml_data or b"<!ENTITY" in xml_data:
        raise RuntimeError("Unsupported Eeschema XML DTD/entity declaration")
    root = ET.fromstring(xml_data)
    refs = [node.attrib["ref"] for node in root.findall("./components/comp")]
    if len(refs) != len(set(refs)) or not refs:
        raise RuntimeError("Native netlist contains ambiguous or empty component references")
    nets = []
    logical_nodes = []
    for net in root.findall("./nets/net"):
        raw_name = net.attrib.get("name", "")
        if not raw_name:
            raise RuntimeError("Native Eeschema netlist includes an unnamed net")
        # '/' prefixes are root-sheet net names only, e.g. '/GND'.
        normalized = raw_name[1:] if raw_name.startswith("/") and raw_name.count("/") == 1 else raw_name
        nets.append(normalized)
        for node in net.findall("node"):
            ref, pin = node.attrib.get("ref", ""), node.attrib.get("pin", "")
            if not ref or not pin:
                raise RuntimeError("Native Eeschema node lacks ref/pin")
            function = node.attrib.get("pinfunction", "")
            logical_nodes.append({"ref": ref, "pin": pin, "pinfunction": function, "net": normalized})
    if len(nets) != len(set(nets)) or not nets:
        raise RuntimeError("Native Eeschema netlist contains duplicate/empty nets")
    if len({(n["ref"], n["pin"]) for n in logical_nodes}) != len(logical_nodes):
        raise RuntimeError("Native Eeschema pin appears on multiple nets")
    return {"refs": set(refs), "nets": set(nets), "logical_nodes": logical_nodes}


def schematic_svg_drawn_elements(plot: bytes) -> int:
    """Count only actual KiCad SVG draw primitives, never decorative SVG wrappers."""
    try:
        document = ET.fromstring(plot)
    except ET.ParseError as exc:
        raise RuntimeError("Native KiCad schematic SVG is malformed") from exc
    drawable = {"path", "text", "rect", "line", "polyline", "polygon", "circle", "ellipse", "image", "use"}
    return sum(node.tag.rsplit("}", 1)[-1] in drawable for node in document.iter() if isinstance(node.tag, str))


def _export_schematic(cli: str, schematic: Path, output: Path, *, root_only: bool = False) -> dict:
    """Native root-page KiCad plot; hierarchy ERC is separate, no false pin parity."""
    if schematic.suffix != ".kicad_sch":
        raise ValueError("Provide an existing .kicad_sch for native schematic inspection")
    schematic_bytes = read_regular_bytes(schematic, max_size=4 * 1024 * 1024)
    text = schematic_bytes.decode("utf-8")
    symbols = schematic_symbols(text, allow_empty=root_only)
    names = _read_schematic_netlist(cli, schematic, output)
    if not set(symbols).issubset(names["refs"]) if root_only else set(symbols) != names["refs"]:
        raise RuntimeError("Native netlist and schematic references differ; refusing ambiguous crossprobe")
    # For hierarchical input the netlist includes ALL sheets. Only root-sheet
    # symbols are plotted here; do not project child sheet pins onto root SVG.
    root_nodes = (
        [node for node in names["logical_nodes"] if node["ref"] in symbols] if root_only else names["logical_nodes"]
    )
    real_pin_anchors = schematic_pin_anchors(text, symbols, root_nodes)
    directory = output / "native-schematic"
    directory.mkdir(parents=True, exist_ok=True)
    # KiCad-generated source may put symbols beyond the default A4 page.
    # Changing *only the display copy's page size* avoids truncating symbols.
    # KiCad designs commonly keep the root hierarchy page symbol-free.
    # Child-sheet symbols are genuine but are never painted onto root canvas.
    largest_x = max((v["x"] for v in symbols.values()), default=0)
    largest_y = max((v["y"] for v in symbols.values()), default=0)
    resized = False
    export_source = schematic.resolve()
    paper = re.search(r'\(paper\s+"([^"]+)"\)', text)
    if paper is None and (largest_x > 280 or largest_y > 193):
        if largest_x > 574 or largest_y > 400:
            raise RuntimeError("Schematic symbols extend beyond supported A2 display copy")
        header = re.search(r'\(generator\s+"[^"]+"\)', text)
        if header is None:
            raise RuntimeError("Cannot safely expand a schematic without a KiCad generator header")
        resized = True
        preview = directory / "display-only-A2.kicad_sch"
        preview.write_text(text[: header.end()] + '\n  (paper "A2")' + text[header.end() :], encoding="utf-8")
        export_source = preview
    elif paper is not None and (largest_x > 280 or largest_y > 193) and paper.group(1) == "A4":
        # Existing explicit A4 paper cannot be silently assumed to fit.
        raise RuntimeError("Schematic symbols exceed explicit A4 page; manual page review required")
    # This output directory can be rebuilt with a different preview page.
    # Remove only previously-generated SVG plots to avoid stale multi-page data.
    for stale in directory.glob("*.svg"):
        stale.unlink()
    result = subprocess.run(
        [
            cli,
            "sch",
            "export",
            "svg",
            "--exclude-drawing-sheet",
            "--no-background-color",
            "--output",
            str(directory),
            str(export_source),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Native KiCad schematic export failed: {result.stderr[:500]}")
    pages = sorted(directory.glob("*.svg"))
    root_svg = directory / (export_source.stem + ".svg")
    if not root_svg.is_file():
        raise RuntimeError("Native KiCad root schematic SVG not found in generated page set")
    if (not root_only and len(pages) != 1) or (root_only and len(pages) < 2):
        raise RuntimeError(f"Unexpected native KiCad schematic page count {len(pages)}")
    native_pages = [root_svg, *[item for item in pages if item != root_svg]]
    page_views = []
    for page in native_pages:
        plot = page.read_bytes()
        viewbox = re.search(rb'viewBox="0\.0000 0\.0000 ([\d.]+) ([\d.]+)"', plot)
        if not viewbox:
            raise RuntimeError("Native schematic SVG page dimensions missing")
        drawn_element_count = schematic_svg_drawn_elements(plot)
        name = "Root sheet" if page == root_svg else page.stem.removeprefix(export_source.stem + "-")
        page_views.append(
            {
                "name": name,
                "src": "data:image/svg+xml;base64," + base64.b64encode(plot).decode("ascii"),
                "viewbox": [float(viewbox.group(1)), float(viewbox.group(2))],
                "root_only_crossprobe": page == root_svg,
                "drawn_element_count": drawn_element_count,
            }
        )
    data = root_svg.read_bytes()
    match = re.search(rb'viewBox="0\.0000 0\.0000 ([\d.]+) ([\d.]+)"', data)
    if not match:
        raise RuntimeError("Native schematic SVG dimensions missing")
    w, h = float(match.group(1)), float(match.group(2))
    if any(v["x"] >= w - 5 or v["y"] >= h - 5 or v["x"] < 0 or v["y"] < 0 for v in symbols.values()):
        raise RuntimeError("At least one schematic symbol lies outside KiCad SVG; refusing clipped preview")
    return {
        "src": "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii"),
        "viewbox": [w, h],
        "source_sha256": hashlib.sha256(schematic_bytes).hexdigest(),
        "filename": schematic.name,
        "net_names": sorted(names["nets"]),
        "logical_nodes": [
            {
                "ref": anchor["ref"],
                "pin": anchor["logical_pin"],
                "canonical_pin": anchor["canonical_pin"],
                "physical_pin": anchor["physical_pin"],
                "net": anchor["net"],
            }
            for anchor in real_pin_anchors
        ],
        "root_only": root_only,
        "pages": page_views,
        "pin_anchors": real_pin_anchors,
        "symbols": list(symbols.values()),
        "display_page_expanded": resized,
        "scope": "Display-only page enlargement, no symbol/wire editing; native ERC on original schematic.",
    }


def physical_pin_parity(board: dict, schematic: dict, design_path: Path) -> dict:
    """Triangulate native PCB, Eeschema netlist and explicit design pin map.

    This is *not* datasheet/package qualification or electrical continuity.
    Every mapped pad instance must have the exact expected KiCad net; pads
    outside the authored map must remain unconnected, or report a mismatch.
    """
    try:
        import yaml  # type: ignore[reportMissingTypeStubs]
    except ImportError as exc:
        raise RuntimeError("PyYAML is required by native KiCad pin parity") from exc
    if design_path.suffix not in (".yaml", ".yml"):
        raise ValueError("Provide a real, matching, local .yaml design source")
    raw = read_regular_bytes(design_path, max_size=3 * 1024 * 1024)
    design = yaml.safe_load(raw)
    if not isinstance(design, dict) or not isinstance(design.get("components"), dict):
        raise ValueError("Design source missing canonical components")
    components = design["components"]
    by_ref = {}
    for name, component in components.items():
        if not isinstance(component, dict):
            raise ValueError(f"Malformed component {name}")
        ref = component.get("ref", name)
        if not isinstance(ref, str) or ref in by_ref:
            raise ValueError("Missing/duplicate canonical component reference")
        by_ref[ref] = component
    physical_refs = {f["ref"] for f in board["footprints"]}
    native_sch_refs = {s["ref"] for s in schematic["symbols"]}
    if set(by_ref) != physical_refs or set(by_ref) != native_sch_refs:
        raise ValueError("Design, native PCB and native schematic component references do not match")
    native_nodes = {}
    physical_numbers: dict[tuple[str, str], str] = {}
    original_keys = set()
    errors = []
    for node in schematic["logical_nodes"]:
        ref, alias = node["ref"], node["pin"]
        key = (ref, alias)
        if key in original_keys:
            raise RuntimeError("Native Eeschema pin-to-net assignment is not unique")
        original_keys.add(key)
        canonical = node.get("canonical_pin", alias)
        logical_key = (ref, canonical)
        if logical_key in native_nodes and native_nodes[logical_key] != node["net"]:
            errors.append(
                {
                    "ref": ref,
                    "logical_pin": canonical,
                    "reason": "native-logical-pin-has-conflicting-physical-nets",
                    "expected": native_nodes[logical_key],
                    "actual": node["net"],
                }
            )
        native_nodes[logical_key] = node["net"]
        number = node.get("physical_pin")
        if number is not None:
            physical_key = (ref, str(number))
            if physical_key in physical_numbers:
                raise RuntimeError("Duplicated physical Eeschema pad number")
            physical_numbers[physical_key] = canonical
    links = []
    mapped = 0
    unassigned = 0
    missing_pad_numbers = []
    native_pad_keys = {(p["ref"], p["pad"]) for p in board["pads"]}
    for ref, comp in by_ref.items():
        mapping = comp.get("package_pin_map") or {}
        if not isinstance(mapping, dict):
            raise ValueError(f"Invalid package_pin_map for {ref}")
        pins = comp.get("pins") or {}
        if not isinstance(pins, dict):
            raise ValueError(f"Invalid logical pins for {ref}")
        for number, logical in mapping.items():
            if not isinstance(number, str) or not isinstance(logical, str) or logical not in pins:
                raise ValueError(f"Invalid logical pin assignment: {ref} {number}")
            if (ref, number) not in native_pad_keys:
                missing_pad_numbers.append({"ref": ref, "pad": number, "logical_pin": logical})
            if any(key[0] == ref for key in physical_numbers) and physical_numbers.get((ref, number)) != logical:
                errors.append(
                    {
                        "ref": ref,
                        "pad": number,
                        "logical_pin": logical,
                        "actual": physical_numbers.get((ref, number)),
                        "reason": "native-physical-pin-number-name-mismatch",
                    }
                )
        for logical, details in pins.items():
            if not isinstance(details, dict):
                raise ValueError(f"Invalid logical pin details: {ref}.{logical}")
            reported_net = details.get("net")
            native_net = native_nodes.get((ref, logical))
            # Canonical declared nets should agree with Eeschema. This also
            # catches a same-ref pin rewired on a different net in the .sch.
            if reported_net is not None and str(reported_net) != native_net:
                errors.append(
                    {
                        "ref": ref,
                        "logical_pin": logical,
                        "expected": str(reported_net),
                        "actual": native_net,
                        "reason": "canonical-versus-schematic-net",
                    }
                )
    for (ref, logical), net in native_nodes.items():
        if ref not in by_ref or logical not in (by_ref[ref].get("pins") or {}):
            errors.append(
                {
                    "ref": ref,
                    "logical_pin": logical,
                    "actual": net,
                    "reason": "native-schematic-pin-not-in-canonical-design",
                }
            )
    for index, pad in enumerate(board["pads"]):
        ref, number, actual_net = pad["ref"], pad["pad"], pad["net"]
        logical = (by_ref[ref].get("package_pin_map") or {}).get(number)
        if logical is None:
            unassigned += 1
            if actual_net != "(no net)":
                errors.append(
                    {
                        "ref": ref,
                        "pad": number,
                        "actual": actual_net,
                        "expected": "(no net)",
                        "reason": "unmapped-but-connected-pad",
                    }
                )
            continue
        expected_net = native_nodes.get((ref, logical))
        if expected_net is None or expected_net != actual_net:
            errors.append(
                {
                    "ref": ref,
                    "pad": number,
                    "logical_pin": logical,
                    "expected": expected_net,
                    "actual": actual_net,
                    "reason": "physical-pad-versus-schematic-net",
                }
            )
        else:
            mapped += 1
            links.append({"pad_index": index, "ref": ref, "pad": number, "logical_pin": logical, "net": actual_net})
    for p in missing_pad_numbers:
        errors.append({**p, "reason": "package-map-pad-absent-from-native-pcb"})
    return {
        "state": "mismatch" if errors else "mapped_net_consistent",
        "mapped_pad_instances": mapped,
        "unmapped_pad_instances": unassigned,
        "total_pad_instances": len(board["pads"]),
        "schematic_logical_pin_nodes": len(schematic["logical_nodes"]),
        "unique_canonical_logical_functions": len(native_nodes),
        "native_physical_pin_number_links": len(physical_numbers),
        "mismatch_count": len(errors),
        "mismatches": errors,
        "pad_links": links,
        "design_sha256": hashlib.sha256(raw).hexdigest(),
        "design_name": design_path.name,
        "scope": (
            "Cross-check of authored package-pin map, native Eeschema logical netlist "
            "and native PCB pad nets only; no datasheet qualification, solder "
            "connectivity or fab approval."
        ),
    }


def native_open_connection_pairs(board: dict, findings: list[dict]) -> list[dict]:
    """Resolve each real KiCad DRC open *endpoint* to a unique source object.

    A pair is an inspection-only Euclidean airwire: not an electrical graph,
    clearance-safe route, proof of continuity, or manufacturing suggestion.
    """
    pairs = []
    for index, finding in enumerate(findings):
        if finding["rule"] != "unconnected_items":
            continue
        endpoints = []
        for row in finding["objects"]:
            m = re.fullmatch(r"@\((-?[\d.]+) mm,\s*(-?[\d.]+) mm\): (.*)", row)
            if not m:
                raise RuntimeError(f"Native open DRC endpoint has unsupported format: {row}")
            x, y, description = float(m.group(1)), float(m.group(2)), m.group(3)
            pad = re.fullmatch(r"Pad ([^ ]+) \[([^]]+)\] of ([A-Za-z]+\d+) on (\S+)", description)
            track = re.fullmatch(r"Track \[([^]]+)\] on (\S+), length ([\d.]+) mm", description)
            if pad:
                number, net, ref, layer = pad.groups()
                candidates = [
                    (i, p)
                    for i, p in enumerate(board["pads"])
                    if p["ref"] == ref
                    and p["pad"] == number
                    and p["net"] == net
                    and math.hypot(x - p["x"], y - p["y"]) < 0.025
                ]
                if len(candidates) != 1:
                    raise RuntimeError(f"KiCad open DRC pad endpoint ambiguous or unavailable: {row}")
                ix, _source = candidates[0]
                endpoints.append(
                    {
                        "x": x,
                        "y": y,
                        "kind": "pad",
                        "pad_index": ix,
                        "net": net,
                        "label": ref + "." + number,
                        "layer": layer,
                    }
                )
            elif track:
                net, layer, reported_length = track.groups()
                matches = []
                for i, segment in enumerate(board["copper"]):
                    if segment["net"] != net or segment["layer"] != layer:
                        continue
                    ax, ay = segment["start"]
                    bx, by = segment["end"]
                    dx, dy = bx - ax, by - ay
                    length = math.hypot(dx, dy)
                    if abs(length - float(reported_length)) > 0.015:
                        continue
                    u = min(1, max(0, ((x - ax) * dx + (y - ay) * dy) / length**2)) if length else 0
                    if math.hypot(x - (ax + u * dx), y - (ay + u * dy)) < 0.025:
                        matches.append(i)
                if len(matches) != 1:
                    raise RuntimeError(f"KiCad open DRC copper endpoint ambiguous or unavailable: {row}")
                endpoints.append(
                    {
                        "x": x,
                        "y": y,
                        "kind": "track",
                        "track_index": matches[0],
                        "net": net,
                        "label": net + " copper segment",
                        "layer": layer,
                    }
                )
            else:
                raise RuntimeError(f"Native open DRC object kind not understood: {row}")
        if len(endpoints) != 2 or endpoints[0]["net"] != endpoints[1]["net"]:
            raise RuntimeError("Native KiCad open pair lacks exactly two same-net endpoints")
        direct = math.hypot(endpoints[0]["x"] - endpoints[1]["x"], endpoints[0]["y"] - endpoints[1]["y"])
        pairs.append(
            {
                "finding_index": index,
                "net": endpoints[0]["net"],
                "endpoints": endpoints,
                "straight_line_mm": round(direct, 4),
                "scope": "Inspection-only straight-line separation; not a routed path or clearance-safe suggestion.",
            }
        )
    return pairs


def native_review_report(payload: dict) -> str:
    """Deterministic read-only evidence note; never a manufacturing signoff."""

    def cell(value: object) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    board = payload["board"]
    findings = payload["findings"]
    opens = payload["open_pairs"]
    drc_state = payload["drc_state"]
    errs = [f for f in findings if f["rule"] != "unconnected_items"]
    erc = payload["erc"]
    pins = payload["pin_parity"]
    parity = payload["net_parity"]
    schematic = payload["schematic"]
    blockers = (
        "**FABRICATION BLOCKED** — native DRC not executed"
        if drc_state == "not_run"
        else "**FABRICATION BLOCKED** — native DRC violations, open connections or unsupported sign-off remain"
    )
    reported_drc = len(errs) if drc_state != "not_run" else "not checked"
    reported_open = len(opens) if drc_state != "not_run" else "not checked"
    reported_erc = erc["count"] if erc["count"] is not None else "not checked"
    mapped_pad_count = pins["mapped_pad_instances"] if pins["mapped_pad_instances"] is not None else "not checked"
    pin_mismatches = pins["mismatch_count"] if pins["mismatch_count"] is not None else "not checked"
    lines = [
        "# ZapTrace — native KiCad local engineering review",
        "",
        "**READ ONLY · NOT FABRICATION APPROVED · NOT A ROUTING PROPOSAL**",
        "",
        blockers,
        "",
        "This document records what KiCad and the authored project inputs actually report. "
        "Nothing in this report authorizes PCB manufacture, purchasing or Gerber export.",
        "",
        "## Source provenance",
        "",
        f"- Native PCB: `{cell(payload['board_name'])}.kicad_pcb`",
        f"- PCB SHA-256: `{payload['source_sha256']}`",
        f"- Schematic hierarchy: {cell(payload.get('schematic_hierarchy', {}).get('scope', 'NOT VERIFIED'))}",
        f"- pcbnew version: `{cell(board['kicad'])}`",
        f"- Project settings: {cell(payload.get('project_settings', {}).get('scope', 'NOT VERIFIED'))}",
        f"- Footprints: **{len(board['footprints'])}**; physical pad objects: **{len(board['pads'])}**",
        f"- Native copper items: **{len(board['copper'])}**; zones: **{board['zones']}**",
        "",
        "## Evidence gates",
        "",
        "| Gate | Native result | Scope |",
        "| --- | --- | --- |",
        f"| Board DRC | {drc_state}; {reported_drc} non-open findings | Original active KiCad rules; no waiver |",
        f"| Connectivity | {reported_open} native open items | DRC pairs; continuity not certified |",
        f"| Schematic ERC | {erc['state']}; {reported_erc} findings | Only enabled Eeschema ERC rules |",
        f"| Net-name parity | {parity['state']} | Names only; not physical continuity |",
        (
            f"| Canonical pin-to-pad parity | {pins['state']}; {mapped_pad_count}/{pins['total_pad_instances']} "
            f"pad instances; {pin_mismatches} mismatches | Authored map, not independent supplier verification |"
        ),
        "| Fabricator / DFM acceptance | NOT OBTAINED | Human engineering/fabricator acceptance required |",
        "| Full physical routing | NOT VERIFIED | A straight airwire is not a safe track |",
        "",
    ]
    if schematic:
        lines += [
            "## Native schematic source",
            "",
            f"- Schematic: `{cell(schematic['filename'])}`",
            f"- Schematic SHA-256: `{schematic['source_sha256']}`",
            f"- Native Eeschema logical pin anchors: **{len(schematic['pin_anchors'])}**",
            "",
        ]
    if pins.get("design_sha256"):
        lines += [
            f"- Canonical design: `{cell(pins['design_name'])}`",
            f"- Canonical design SHA-256: `{pins['design_sha256']}`",
            f"- Unmapped physical pad objects: **{pins['unmapped_pad_instances']}** (NOT QUALIFIED)",
            "",
        ]
    if errs:
        lines += [
            "## Remaining native DRC manufacturing findings",
            "",
            "| Rule | Native position | Diagnostic |",
            "| --- | --- | --- |",
        ]
        for f in errs:
            at = "not supplied" if f["x"] is None else f"({f['x']:.4f}, {f['y']:.4f}) mm"
            lines.append(f"| {cell(f['rule'])} | {at} | {cell(f['message'])} |")
        lines.append("")
    if opens:
        lines += [
            "## Outstanding native connection pairs",
            "",
            "**AIRWIRE ONLY:** straight-line endpoint separation is NOT a routed distance "
            "or clearance-safe suggestion.",
            "",
            "| KiCad finding | Net | Endpoint A | Endpoint B | Straight-line separation |",
            "| --- | --- | --- | --- | --- |",
        ]
        for pair in opens:
            a, b = pair["endpoints"]

            def descr(endpoint: dict) -> str:
                return f"{endpoint['label']} ({endpoint['x']:.4f}, {endpoint['y']:.4f}) mm"

            lines.append(
                f"| {pair['finding_index']} | {cell(pair['net'])} | "
                f"{cell(descr(a))} | {cell(descr(b))} | {pair['straight_line_mm']:.4f} mm |"
            )
        lines.append("")
    if pins["mismatches"]:
        lines += [
            "## Canonical source disagreements — STOP",
            "",
            "| Reason | Ref | Pad / logical pin |",
            "| --- | --- | --- |",
        ]
        for error in pins["mismatches"]:
            location = cell(error.get("pad", error.get("logical_pin", "?")))
            lines.append(f"| {cell(error['reason'])} | {cell(error['ref'])} | {location} |")
        lines.append("")
    lines += [
        "## Engineering decisions still required",
        "",
        "1. Resolve each physical open with actual native copper and independently rerun KiCad connectivity/DRC.",
        "2. Resolve ESP32 thermal-via drill and USB-C locating-hole constraints with "
        "controlled footprint revisions or written fabricator DFM acceptance. Never silently weaken rules.",
        "3. Qualify supplier pinouts, enclosure, antenna keepout, thermal behavior, assembly and test plan.",
        "4. Complete independent Proof Pack and fabricator review before any manufacturing authorization.",
        "",
        "Generated locally from the exact native KiCad inputs; this is a review record, not a production release.",
        "",
    ]
    return "\n".join(lines)


def native_review_report_html(payload: dict) -> str:
    """Static, script-free local evidence view with explicit unverified gates."""

    def h(value: object) -> str:
        return html.escape(str(value), quote=True)

    findings = payload["findings"]
    bad = [f for f in findings if f["rule"] != "unconnected_items"]
    opens = payload["open_pairs"]
    drc_run = payload["drc_state"] != "not_run"
    schematic = payload["schematic"]
    pins = payload["pin_parity"]
    erc = payload["erc"]
    drc_rows = []
    if drc_run:
        for item in bad:
            place = "Not reported" if item["x"] is None else f"{item['x']:.4f}, {item['y']:.4f} mm"
            drc_rows.append(
                f"<tr><td><code>{h(item['rule'])}</code></td><td>{h(place)}</td><td>{h(item['message'])}</td></tr>"
            )
    open_rows = []
    if drc_run:
        for pair in opens:
            a, b = pair["endpoints"]
            place_a = f"{a['label']} ({a['x']:.4f}, {a['y']:.4f} mm)"
            place_b = f"{b['label']} ({b['x']:.4f}, {b['y']:.4f} mm)"
            open_rows.append(
                f"<tr><td><code>{h(pair['net'])}</code></td><td>{h(place_a)}</td>"
                f"<td>{h(place_b)}</td><td class='num'>{pair['straight_line_mm']:.4f}</td></tr>"
            )
    state_drc = f"{len(bad)} violations" if drc_run else "NOT RUN"
    state_opens = f"{len(opens)} pairs" if drc_run else "NOT RUN"
    state_erc = f"{erc['count']} findings (enabled rules)" if erc["state"] != "not_run" else "NOT RUN"
    state_pins = (
        f"{pins['mapped_pad_instances']}/{pins['total_pad_instances']} mapped"
        if pins["state"] != "not_checked"
        else "NOT CHECKED"
    )
    lib_count = sum(
        f["rule"] in {"lib_footprint_issues", "lib_footprint_mismatch", "footprint_library_mismatch"} for f in bad
    )
    models = payload.get("board", {}).get("model_assets") or {}
    model_value = (
        f"{models['present_files']}/{models['declared_references']} source files found"
        if models.get("model_geometry_approved") is False
        else "NOT CHECKED"
    )
    model_scope = (
        "Unresolved references: "
        + ", ".join(models.get("unresolved_refs") or [])
        + "; no model: "
        + ", ".join(models.get("without_model_refs") or [])
        + ". File presence only; fit/assembly NOT qualified."
        if models
        else "Native 3D model file presence not checked; approval blocked."
    )
    rows = [
        ("Board DRC", state_drc, "Native KiCad DRC under supplied context; no waiver"),
        (
            "Library/footprint consistency",
            f"{lib_count} native DRC findings",
            "Library or footprint status depends on complete original KiCad library context",
        ),
        (
            "Project-specific KiCad rules",
            "SUPPLIED" if payload.get("project_settings", {}).get("project_provided") else "NOT SUPPLIED",
            payload.get("project_settings", {}).get("scope", "Project rules not verified"),
        ),
        ("Physical connectivity", state_opens, "Native DRC pairs, not route validation"),
        ("Schematic ERC", state_erc, "Only enabled native schematic checks"),
        ("Pad mapping", state_pins, "Authored map; no vendor pin qualification"),
        ("3D model file references", model_value, model_scope),
        ("Fabrication authorization", "BLOCKED", "No fabricator or human production approval"),
    ]
    gate_html = "".join(
        f"<tr><th>{h(name)}</th><td><b>{h(value)}</b></td><td>{h(scope)}</td></tr>" for name, value, scope in rows
    )
    schematic_info = (
        f"<div class='source'><span>SCHEMATIC SHA-256</span><code>{h(schematic['source_sha256'])}</code></div>"
        if schematic
        else "<div class='source'><span>SCHEMATIC</span><b>Not supplied</b></div>"
    )
    design_info = (
        f"<div class='source'><span>CANONICAL DESIGN SHA-256</span><code>{h(pins['design_sha256'])}</code></div>"
        if pins.get("design_sha256")
        else ""
    )
    html_css = Path(__file__).with_name("review_studio_native_report.css").read_text(encoding="utf-8")
    source = Path(__file__).with_name("review_studio_native_report_template.html").read_text(encoding="utf-8")
    tokens = {
        "CSS": html_css,
        "GATE_ROWS": gate_html,
        "SCHEMATIC_INFO": schematic_info,
        "DESIGN_INFO": design_info,
        "PCB_SHA": h(payload["source_sha256"]),
        "DRC_NOTE": (
            "The actual DRC report is shown below."
            if drc_run
            else "KiCad DRC was NOT RUN; do not infer that there are no violations."
        ),
        "DRC_ROWS": "".join(drc_rows)
        if drc_rows
        else ("<tr><td colspan='3'>No recorded findings (or DRC not run); not manufacturing authorization.</td></tr>"),
        "OPEN_ROWS": "".join(open_rows)
        if open_rows
        else (
            "<tr><td colspan='4'>Open-pair evidence unavailable or none reported; "
            "this does not prove complete routing.</td></tr>"
        ),
    }

    for key in tokens:
        if source.count(f"__{key}__") != 1:
            raise RuntimeError(f"Missing or repeated evidence-template placeholder: {key}")
    matcher = re.compile("|".join(re.escape(f"__{key}__") for key in tokens))
    rendered = matcher.sub(lambda match: tokens[match.group(0)[2:-2]], source)
    return apply_offline_csp(rendered)


def render_native_3d(cli: str, board: Path, output: Path, *, enabled: bool) -> dict:
    """Optional read-only KiCad 10 OpenGL images, never fake part models.

    Absent or unsupported render never counts as a native engineering error or
    a DRC pass. The renderer output itself remains an unverified model preview.
    """
    status: dict = {
        "state": "not_run" if not enabled else "unavailable",
        "renderer": "KiCad 10 native pcb render",
        "model_coverage": "not_verified",
        "model_notice": "3D geometry uses only models actually available in local KiCad. "
        "Completeness, enclosure fit, assembly and manufacturing are NOT verified.",
        "views": [],
        "orbit_frames": [],
    }
    for stale in output.glob("native-kicad-3d-*.png"):
        if stale.is_symlink():
            raise RuntimeError("Unsafe symlink in local 3D review output")
        stale.unlink()
    if not enabled:
        return status
    base = [cli, "pcb", "render"]
    # Render requires a GUI/OpenGL context. The app remains usable without one.
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if xvfb is None:
            status["reason"] = "No graphics display or supported offscreen renderer available"
            return status
        base = [xvfb, "-a", "-s", "-screen 0 1600x1000x24", "env", "LIBGL_ALWAYS_SOFTWARE=1", *base]
    layouts = (
        ("Isometric", "native-kicad-3d-isometric.png", ["--perspective", "--rotate", "-32,0,55"], "views"),
        ("Top", "native-kicad-3d-top.png", [], "views"),
        # Eight genuine KiCad OpenGL camera renders. UI rotates through native
        # snapshots; this is NOT continuous OpenCascade geometry editing.
        *(
            (
                f"Orbit {angle}°",
                f"native-kicad-3d-orbit-{angle:03}.png",
                ["--perspective", "--rotate", f"-32,0,{angle}"],
                "orbit_frames",
            )
            for angle in range(0, 360, 45)
        ),
    )
    original = hashlib.sha256(board.read_bytes()).hexdigest()
    for label, filename, angle, channel in layouts:
        path = output / filename
        path.unlink(missing_ok=True)
        command = [
            *base,
            "--side",
            "top",
            "--width",
            "1200",
            "--height",
            "800",
            "--background",
            "transparent",
            "--quality",
            "basic",
            *angle,
            "--output",
            str(path),
            str(board),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=50, check=False)
        except (OSError, subprocess.TimeoutExpired):
            result = None
        try:
            data = path.read_bytes() if path.is_file() else b""
            valid = bool(
                result is not None
                and result.returncode == 0
                and 2000 < len(data) < 12_000_000
                and data[:8] == b"\x89PNG\r\n\x1a\n"
            )
            if not valid:
                for view_file in output.glob("native-kicad-3d-*.png"):
                    view_file.unlink()
                status["views"].clear()
                status["orbit_frames"].clear()
                status["reason"] = "Native KiCad OpenGL rendering did not complete on this machine"
                return status
            width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            if not 300 <= width <= 2400 or not 300 <= height <= 2000:
                for view_file in output.glob("native-kicad-3d-*.png"):
                    view_file.unlink()
                status["views"].clear()
                status["orbit_frames"].clear()
                status["reason"] = "Native KiCad rendered image has unexpected geometry"
                return status
            status[channel].append(
                {
                    "label": label,
                    "source": "data:image/png;base64," + base64.b64encode(data).decode("ascii"),
                    "width": width,
                    "height": height,
                    "file": filename,
                }
            )
        except OSError:
            for view_file in output.glob("native-kicad-3d-*.png"):
                view_file.unlink()
            status["views"].clear()
            status["orbit_frames"].clear()
            status["reason"] = "Native KiCad preview image unavailable"
            return status
    if hashlib.sha256(board.read_bytes()).hexdigest() != original:
        raise RuntimeError("Native 3D render modified the source PCB; aborting preview")
    status["state"] = "rendered"
    return status


def prepare_native_review_output(board: Path, output: Path) -> Path:
    """Preserve user-chosen destinations without overwriting unrelated content."""
    destination = output.resolve(strict=False)
    source_dir = board.parent.resolve(strict=True)
    if destination == source_dir or destination in source_dir.parents:
        raise ValueError("Native review output must not overwrite the KiCad source tree or its ancestors")
    if output.is_symlink():
        raise ValueError("Refusing a symlinked native review output directory")
    if destination.exists():
        if not destination.is_dir():
            raise ValueError("Native review output must be a directory")
        if any(destination.iterdir()):
            proof = destination / "evidence.json"
            try:
                evidence = json.loads(read_regular_bytes(proof, max_size=4 * 1024 * 1024))
            except ValueError as exc:
                raise ValueError("Native review output directory contains unrelated files") from exc
            source_digest = hashlib.sha256(read_regular_bytes(board, max_size=10 * 1024 * 1024)).hexdigest()
            if not isinstance(evidence, dict) or evidence.get("source_sha256") != source_digest:
                raise ValueError("Native review output belongs to a different PCB source")
            if any(item.is_symlink() for item in destination.rglob("*")):
                raise ValueError("Native review output contains an unsafe symlink")
    else:
        destination.mkdir(parents=True, exist_ok=False)
    return destination


def build(
    board: Path,
    output: Path,
    template: Path,
    *,
    with_drc: bool = True,
    with_3d: bool = False,
    schematic: Path | None = None,
    design_source: Path | None = None,
    workspace_home: Path | None = None,
    expected_source_sha256: str | None = None,
) -> Path:
    if board.suffix != ".kicad_pcb" or board.is_symlink():
        raise ValueError("Provide an existing nonsymlink native .kicad_pcb input")
    raw_board = read_regular_bytes(board, max_size=10 * 1024 * 1024)
    if expected_source_sha256 is not None and hashlib.sha256(raw_board).hexdigest() != expected_source_sha256:
        raise ValueError("Source KiCad PCB changed since selection; native review refused")
    if output.is_symlink():
        raise ValueError("Refusing a symlinked native review output directory")
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("Native kicad-cli must be installed")
    board = board.resolve()
    if output.resolve() == board.parent or output.resolve() == board:
        raise ValueError("Refusing to export into the original KiCad PCB directory")
    if design_source is not None and schematic is None:
        raise ValueError("A native schematic is required for physical pad mapping")
    # A direct native viewer export must obey the same completeness gate as a
    # GUI import. KiCad can otherwise report ERC on a partial hierarchy.
    from review_studio_workspace import validate_schematic_hierarchy

    sheet_inventory = validate_schematic_hierarchy(schematic) if schematic is not None else []
    source = _read_kicad(board)
    output = prepare_native_review_output(board, output)
    layers = {}
    dims = None
    names = ["F.Cu", "B.Cu", "F.Mask", "B.Mask", "F.SilkS", "B.SilkS", "Edge.Cuts"]
    for layer in names:
        image, current_dims = _export_layer(cli, board, output / f"plot-{layer}.svg", layer)
        if dims is not None and any(abs(a - b) > 0.02 for a, b in zip(dims, current_dims, strict=True)):
            raise RuntimeError(f"Nonaligned native layers: {layer} has viewbox {current_dims}, expected {dims}")
        dims = current_dims
        layers[layer] = image
    if dims is None:
        raise RuntimeError("No native KiCad PCB layers rendered")
    # SVG board-area plotting crops the physical board around its perimeter.
    # Convert absolute pcbnew positions into plot-local millimetres; do not
    # assume every EDA board was drawn at (0, 0).
    if any(abs(a - b) > 0.5 for a, b in zip(source["size"], dims, strict=True)):
        raise RuntimeError(f"Native plotted bounds do not match board bounds: {source['size']} vs {dims}")
    plot_origin = [round(source["origin"][i] + (source["size"][i] - dims[i]) / 2, 5) for i in (0, 1)]
    findings = []
    drc_state = "not_run"
    if not with_drc:
        # Never leave an old DRC report in a deliberately unchecked output.
        stale_report = output / "native-drc.rpt"
        if stale_report.is_file():
            stale_report.unlink()
    if with_drc:
        report = output / "native-drc.rpt"
        r = subprocess.run(
            [cli, "pcb", "drc", "--exit-code-violations", "--output", str(report), str(board)],
            text=True,
            capture_output=True,
            check=False,
        )
        if r.returncode not in (0, 5) or not report.is_file():
            raise RuntimeError(f"Native KiCad DRC failed to execute: {r.returncode}: {r.stderr[:500]}")
        raw_drc = report.read_text(encoding="utf-8")
        findings = validated_native_drc(raw_drc)
        drc_state = "reported" if findings else "no_reported_findings"
    open_pairs = native_open_connection_pairs(source, findings) if drc_state != "not_run" else []
    native_schematic = (
        _export_schematic(cli, schematic, output, root_only=len(sheet_inventory) > 1) if schematic is not None else None
    )
    net_parity = {
        "state": "not_checked",
        "common": [],
        "board_only": [],
        "schematic_only": [],
        "refs_match": None,
        "scope": "No native schematic netlist provided",
    }
    if native_schematic is not None:
        board_refs = {f["ref"] for f in source["footprints"]}
        sch_refs = {v["ref"] for v in native_schematic["symbols"]}
        native_schematic["crossprobe_refs"] = sorted(board_refs & sch_refs)
        board_nets = {p["net"] for p in source["pads"] if p["net"] != "(no net)"}
        sch_nets = set(native_schematic["net_names"])
        net_parity = {
            "state": (
                "root_only_not_verified"
                if len(sheet_inventory) > 1
                else "names_match"
                if board_nets == sch_nets
                else "names_differ"
            ),
            "common": sorted(board_nets & sch_nets),
            "board_only": sorted(board_nets - sch_nets),
            "schematic_only": sorted(sch_nets - board_nets),
            "refs_match": board_refs == sch_refs,
            "scope": (
                "Multi-sheet net/ref parity is NOT checked across child sheets; native ERC is separate."
                if len(sheet_inventory) > 1
                else "Native net names and footprint refs only; physical/schematic pin mapping NOT verified."
            ),
        }
    pin_parity = (
        physical_pin_parity(source, native_schematic, design_source)
        if (design_source is not None and native_schematic is not None and len(sheet_inventory) <= 1)
        else {
            "state": "not_checked",
            "scope": (
                "Hierarchical schematic pin map NOT verified: canvas/net extraction covers the root sheet only."
                if len(sheet_inventory) > 1
                else "No canonical design source supplied; pin-level correspondence NOT checked."
            ),
            "mapped_pad_instances": None,
            "unmapped_pad_instances": None,
            "total_pad_instances": len(source["pads"]),
            "schematic_logical_pin_nodes": None,
            "mismatch_count": None,
            "mismatches": [],
            "pad_links": [],
        }
    )
    erc = (
        _run_erc(cli, schematic, output)
        if schematic is not None
        else {
            "state": "not_run",
            "count": None,
            "errors": None,
            "warnings": None,
            "scope": "No source schematic supplied; native KiCad ERC not run.",
        }
    )
    project_pro = board.with_suffix(".kicad_pro")
    project_dru = board.with_suffix(".kicad_dru")
    pro_present = project_pro.is_file()
    dru_present = project_dru.is_file()
    context_hash = hashlib.sha256()
    for label, source_file in (("PCB", board), ("KiCad project", project_pro), ("KiCad custom rules", project_dru)):
        context_hash.update(label.encode("utf-8"))
        context_hash.update(source_file.read_bytes() if source_file.is_file() else b"NOT_SUPPLIED")
    # Provenance includes schematic sheet inventory, not just PCB and KiCad
    # rule files; otherwise a changed child sheet could reuse an old review.
    if schematic is None:
        context_hash.update(b"SCHEMATIC_NOT_SUPPLIED")
    else:
        for sheet in sheet_inventory:
            context_hash.update(b"SHEET")
            context_hash.update(sheet.encode("utf-8"))
            context_hash.update((schematic.parent / sheet).read_bytes())
    project_settings = {
        "project_provided": pro_present,
        "custom_rules_provided": dru_present,
        "analysis_context_sha256": context_hash.hexdigest(),
        "scope": (
            "Matching .kicad_pro supplied for this native KiCad run; external footprint libraries "
            "and manufacturing acceptance are not independently qualified."
            if pro_present
            else (
                "Matching .kicad_pro NOT supplied: standalone KiCad/default board DRC settings "
                "may differ from the original project."
            )
        ),
    }
    payload = {
        "schematic_hierarchy": {
            "page_count": len(sheet_inventory),
            "page_paths": sheet_inventory,
            "scope": (
                "Referenced native schematic files present; ERC processes hierarchy but "
                "the SVG/pin cross-probe preview shows the root sheet only."
                if len(sheet_inventory) > 1
                else "Single-root native schematic checked."
                if sheet_inventory
                else "No native schematic provided; hierarchy/ERC NOT RUN."
            ),
        },
        "project_settings": project_settings,
        "board_name": board.stem,
        "source_sha256": hashlib.sha256(board.read_bytes()).hexdigest(),
        "board": source,
        "layers": layers,
        "schematic": native_schematic,
        "erc": erc,
        "net_parity": net_parity,
        "pin_parity": pin_parity,
        "layer_names": names,
        "viewbox": dims,
        "findings": findings,
        "open_pairs": open_pairs,
        "drc_state": drc_state,
        "plot_origin": plot_origin,
        "nonclaim": (
            "Native PCB/optional schematic review is inspection-only. Completed ERC checks "
            "cover only enabled schematic rules; neither DRC nor ERC establishes full physical continuity, "
            "proof pack, thermal/RF, assembly or fabricator approval."
        ),
    }
    # This optional source-linked visualization never changes the engineering
    # verdict; render failure or incomplete local 3D models never imply safety.
    render3d = render_native_3d(cli, board, output, enabled=with_3d)
    payload["render3d"] = render3d
    # No third-party CSS/JS, all SVG plotted by KiCad as inert images.
    page = template.read_text(encoding="utf-8").replace("__NATIVE_DATA__", safe_inline_json(payload))
    if workspace_home is None:
        back = ""
    else:
        from urllib.parse import quote

        home = workspace_home.resolve()
        relative = Path(os.path.relpath(home, output.resolve()))
        href = "/".join(quote(part) for part in relative.parts)
        back = f'<a class="project-back" id="workspaceHome" href="{html.escape(href, quote=True)}">← Projects</a>'
    page = page.replace("__WORKSPACE_LINK__", back)
    if "__NATIVE_DATA__" in page or "__WORKSPACE_LINK__" in page:
        raise RuntimeError("Template injection failed")
    target = output / "index.html"
    target.write_text(page, encoding="utf-8")
    summary = {k: v for k, v in payload.items() if k not in ("layers", "schematic", "render3d")}
    summary["render3d_meta"] = {
        **{key: value for key, value in render3d.items() if key != "views"},
        "views": [{key: value for key, value in view.items() if key != "source"} for view in render3d["views"]],
        "orbit_frames": [
            {key: value for key, value in frame.items() if key != "source"} for frame in render3d["orbit_frames"]
        ],
    }
    if native_schematic is not None:
        summary["schematic_meta"] = {k: v for k, v in native_schematic.items() if k not in ("src", "pages")}
        summary["schematic_meta"]["pages"] = [
            {k: v for k, v in pg.items() if k != "src"} for pg in native_schematic["pages"]
        ]
    (output / "evidence.json").write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    (output / "REVIEW_REPORT.md").write_text(native_review_report(payload), encoding="utf-8")
    (output / "REVIEW_REPORT.html").write_text(native_review_report_html(payload), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True, help="Source native KiCad .kicad_pcb (read only)")
    parser.add_argument("--output", type=Path, required=True, help="Separate local viewer build directory")
    parser.add_argument("--no-drc", action="store_true", help="Disable native DRC; must display NOT RUN")
    parser.add_argument(
        "--no-3d", action="store_true", help="Skip optional KiCad 3D render (native ERC/DRC unaffected)"
    )
    parser.add_argument(
        "--workspace-home", type=Path, help="Optional local projects index for read-only back navigation"
    )
    parser.add_argument("--schematic", type=Path, help="Optional real KiCad schematic, read-only one-page view")
    parser.add_argument(
        "--design-source", type=Path, help="Optional canonical YAML with explicit physical package-pin maps"
    )
    args = parser.parse_args()
    result = build(
        args.board,
        args.output,
        Path(__file__).with_name("review_studio_native_template.html"),
        with_drc=not args.no_drc,
        with_3d=not args.no_3d,
        schematic=args.schematic,
        design_source=args.design_source,
        workspace_home=args.workspace_home,
    )
    print(f"LOCAL ONLY: {result}")
    print("Read-only KiCad SVG + pad/net inspection. Not a fabrication sign-off.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as e:
        print(f"BLOCKED: {e}", file=sys.stderr)
        sys.exit(2)
