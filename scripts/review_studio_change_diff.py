#!/usr/bin/python3
"""Read-only, source-verified current/proposed review for actual native KiCad PCB ECO."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from review_studio_local_csp import apply_offline_csp
from review_studio_native_kicad import _read_kicad

TEMPLATE = Path(__file__).with_name("review_studio_change_diff_template.html")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_native_board_transition(
    before: dict, after: dict, proof: dict, sha_before: str, sha_after: str
) -> list[dict]:
    kind = proof.get("type")
    if (
        kind
        not in (
            "PCB_UNROUTED_FOOTPRINT_PLACEMENT_ECO",
            "PCB_UNROUTED_MULTI_FOOTPRINT_PLACEMENT_ECO",
        )
        or proof.get("status") != "native_drc_verified_copy_not_original"
    ):
        raise ValueError("Unsupported native engineering change type")
    if (proof.get("source_sha256"), proof.get("working_sha256")) != (sha_before, sha_after):
        raise ValueError("Stale or different state hash: refusing proposed review")
    if proof.get("fabApproved") is not False or proof.get("electricallyApproved") is not False:
        raise ValueError("A local unsigned note cannot authorize hardware")
    if any(before[k] != after[k] for k in ("origin", "size", "zones", "tracks", "copper", "kicad")):
        raise ValueError("Copper, board outline, KiCad version or zones changed: unsupported")
    f0, f1 = ({f["ref"]: f for f in board["footprints"]} for board in (before, after))
    p0, p1 = ({(p["ref"], p["pad"]): p for p in board["pads"]} for board in (before, after))
    if (
        f0.keys() != f1.keys()
        or p0.keys() != p1.keys()
        or len(f0) != len(before["footprints"])
        or len(p0) != len(before["pads"])
    ):
        raise ValueError("Footprint/pad identity added, removed or duplicated")
    changes = []
    for ref in sorted(f0):
        original, new = f0[ref], f1[ref]
        if any(original[k] != new[k] for k in ("ref", "value", "footprint", "pad_count")):
            raise ValueError("Component identity or library footprint changed")
        delta = [round(new[k] - original[k], 5) for k in ("x", "y")]
        if not all(math.isfinite(value) for value in delta):
            raise ValueError("Non-finite KiCad position")
        for key in p0:
            if key[0] != ref:
                continue
            prev, nxt = p0[key], p1[key]
            if any(prev[k] != nxt[k] for k in ("ref", "pad", "net", "size")):
                raise ValueError("Pad identity, net or dimensions changed")
            if any(abs((nxt[k] - prev[k]) - delta[index]) > 0.00002 for index, k in enumerate(("x", "y"))):
                raise ValueError("Unsupported pin geometry/rotation, not a translation")
        if any(abs(d) > 0.000001 for d in delta):
            changes.append(
                {
                    "ref": ref,
                    "old_mm": [original["x"], original["y"]],
                    "new_mm": [new["x"], new["y"]],
                    "delta_mm": delta,
                    "pad_count": original["pad_count"],
                    "risk": "human_review_required",
                }
            )
    if kind == "PCB_UNROUTED_FOOTPRINT_PLACEMENT_ECO":
        if len(changes) != 1 or changes[0]["ref"] != proof.get("ref"):
            raise ValueError("Exactly one source-linked physical footprint movement required")
        if changes[0]["old_mm"] != proof.get("old_mm") or changes[0]["new_mm"] != proof.get("new_mm"):
            raise ValueError("Saved ECO evidence footprint positions differ from actual PCB")
    else:
        declared = proof.get("moves")
        steps = proof.get("steps")
        if (
            not 2 <= len(changes) <= 4
            or not isinstance(declared, list)
            or not isinstance(steps, list)
            or len(declared) != len(changes)
            or len(steps) != len(changes)
        ):
            raise ValueError("Multi-ECO requires 2–4 distinct source-proven footprint translations")
        planned = {}
        for move in declared:
            if (
                not isinstance(move, dict)
                or set(move) != {"ref", "old_mm", "new_mm"}
                or not isinstance(move["ref"], str)
                or move["ref"] in planned
            ):
                raise ValueError("Invalid or duplicate multi-ECO reference")
            planned[move["ref"]] = move
        if set(planned) != {change["ref"] for change in changes}:
            raise ValueError("Multi-ECO references differ from native footprint transitions")
        for change in changes:
            move = planned[change["ref"]]
            if move["old_mm"] != change["old_mm"] or move["new_mm"] != change["new_mm"]:
                raise ValueError("Multi-ECO positions differ from native KiCad footprints")
        if len({step["ref"] for step in steps if isinstance(step, dict) and "ref" in step}) != len(changes):
            raise ValueError("Multi-ECO step identities cannot be duplicated")
        for index, step in enumerate(steps):
            if (
                not isinstance(step, dict)
                or set(step)
                != {"ref", "dx_mm", "dy_mm", "source_sha256", "working_sha256", "old_mm", "new_mm", "native_drc"}
                or step["ref"] not in planned
                or step["old_mm"] != planned[step["ref"]]["old_mm"]
                or step["new_mm"] != planned[step["ref"]]["new_mm"]
                or any(
                    type(step[key]) not in (float, int) or not math.isfinite(step[key]) for key in ("dx_mm", "dy_mm")
                )
                or any(
                    abs((step["new_mm"][i] - step["old_mm"][i]) - step[key]) > 1e-6
                    for i, key in enumerate(("dx_mm", "dy_mm"))
                )
                or not isinstance(step["native_drc"], dict)
                or step["native_drc"].get("new_drc_rules") != 0
            ):
                raise ValueError("Invalid per-step native multi-ECO evidence")
            expected_source = sha_before if index == 0 else steps[index - 1]["working_sha256"]
            if step["source_sha256"] != expected_source:
                raise ValueError("Multi-ECO SHA chain does not link original source")
        if steps[-1]["working_sha256"] != sha_after:
            raise ValueError("Multi-ECO SHA chain does not match proposed PCB")
    return changes


def verified_rule_context(source: Path, candidate: Path, proof: dict) -> dict:
    """Bind both native KiCad rule sidecars to a reviewed design state.

    A board SHA alone is not enough: two different .kicad_pro/.kicad_dru
    files can give different DRC meaning for the exact same PCB bytes.
    """
    claim = proof.get("rule_context")
    if not isinstance(claim, dict) or set(claim) != {
        "mode",
        "project_sha256",
        "custom_rules_sha256",
        "custom_rule_loader_probe_passed",
        "effective_rules_independently_verified",
    }:
        raise ValueError("Missing or unexpected native KiCad project-rule evidence")
    mode = claim["mode"]
    if mode not in ("defaults_without_project", "project", "project_with_custom_rules"):
        raise ValueError("Unsupported native KiCad rule context")
    expected = (claim["project_sha256"], claim["custom_rules_sha256"])
    if any(
        value is not None
        and (not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value))
        for value in expected
    ):
        raise ValueError("Invalid KiCad project/rule SHA-256 claim")
    if (
        (mode == "defaults_without_project" and expected != (None, None))
        or (mode == "project" and (expected[0] is None or expected[1] is not None))
        or (mode == "project_with_custom_rules" and None in expected)
        or type(claim["custom_rule_loader_probe_passed"]) is not bool
        or claim["custom_rule_loader_probe_passed"] != (mode == "project_with_custom_rules")
        or claim["effective_rules_independently_verified"] is not False
    ):
        raise ValueError("Native KiCad project/rule mode conflicts with verified ECO evidence")
    for suffix, expected_sha, limit in (
        (".kicad_pro", expected[0], 3_000_000),
        (".kicad_dru", expected[1], 1_000_000),
    ):
        for board in (source, candidate):
            sidecar = board.with_suffix(suffix)
            if sidecar.is_symlink() or (sidecar.exists() and not sidecar.is_file()):
                raise ValueError("Unsafe KiCad design-rule sidecar")
            if expected_sha is None:
                if sidecar.exists():
                    raise ValueError("Unexpected native KiCad project-rule sidecar")
            elif not sidecar.is_file() or sidecar.stat().st_size > limit or digest(sidecar) != expected_sha:
                raise ValueError("Stale or altered native KiCad project-rule state")
    return {
        "mode": mode,
        "project_sha256": expected[0],
        "custom_rules_sha256": expected[1],
        "custom_rule_loader_probe_passed": claim["custom_rule_loader_probe_passed"],
        "effective_rules_independently_verified": False,
        "production_rule_approval": False,
    }


def native_drc(board: Path, report: Path) -> dict:
    run = subprocess.run(
        ["kicad-cli", "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(board)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if run.returncode != 0:
        raise RuntimeError("Native KiCad failed: DRC is not verified")
    content = json.loads(report.read_text())
    if content.get("coordinate_units") != "mm" or any(
        not isinstance(content.get(k), list)
        for k in ("violations", "unconnected_items", "ignored_checks", "included_severities")
    ):
        raise ValueError("Unexpected native KiCad DRC schema")
    return content


def native_svg(board: Path, output: Path) -> dict:
    """Render a bounded genuine KiCad SVG. Offline <img> context cannot execute scripts."""
    args = [
        "kicad-cli",
        "pcb",
        "export",
        "svg",
        "--layers",
        "F.Cu,F.SilkS,Edge.Cuts",
        "--mode-single",
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
        "--output",
        str(output),
        str(board),
    ]
    run = subprocess.run(args, capture_output=True, text=True, timeout=85, check=False)
    if run.returncode != 0 or not output.is_file():
        raise RuntimeError("Genuine native KiCad SVG plot unavailable")
    payload = output.read_bytes()
    if len(payload) > 4_000_000 or b"<svg" not in payload[:1500]:
        raise ValueError("Native SVG too large or invalid")
    lowered = payload.lower()
    if any(
        x in lowered
        for x in (
            b"<script",
            b"<foreignobject",
            b"<iframe",
            b"onload=",
            b"onclick=",
            b"javascript:",
            b"<image",
            b"<use ",
        )
    ):
        raise ValueError("Active or linked SVG content refused")
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "uri": "data:image/svg+xml;base64," + base64.b64encode(payload).decode("ascii"),
    }


def erc_findings(report: str, references: set[str], expected: int) -> list[dict]:
    """Read actual KiCad text ERC rule and object references, not invented positions."""
    entries = re.split(r"(?m)^(?=\[[a-z_0-9]+\]:)", report)
    parsed = []
    for item in entries[1:]:
        match = re.match(r"\[([a-z_0-9]+)\]: ([^\r\n]{1,500})", item)
        severity = re.search(r"(?m)^\s*; (error|warning)\s*$", item)
        target = re.search(r"@\((-?\d+(?:\.\d+)?) mm, (-?\d+(?:\.\d+)?) mm\): Symbol ([A-Za-z0-9]+)\b", item)
        if match is None or severity is None:
            raise ValueError("Unsupported KiCad ERC finding record; review blocked")
        ref = target.group(3) if target and target.group(3) in references else None
        parsed.append(
            {
                "rule": match.group(1),
                "message": match.group(2),
                "severity": severity.group(1),
                "ref": ref,
                "coordinate_mm": [float(target.group(1)), float(target.group(2))]
                if ref and target is not None
                else None,
            }
        )
    if len(parsed) != expected:
        raise ValueError("KiCad ERC count and parsed native findings disagree")
    return parsed


def _check_native_svg_target(target: Path) -> None:
    """Refuse indirect output aliases and unsafe existing review artifacts."""
    if (
        ".." in target.parts
        or any(part.is_symlink() for part in (target, *target.parents))
        or (target.exists() and not target.is_file())
    ):
        raise ValueError("Unsafe native schematic SVG target")


def native_schematic_svg(cli: str, source: Path, target: Path) -> dict:
    """One actual sheet only; reject unsafe embedded SVG content and external links."""
    _check_native_svg_target(target)
    with tempfile.TemporaryDirectory(prefix=".review-sch-svg-", dir=target.parent) as scratch:
        command = [cli, "sch", "export", "svg", "--output", scratch + "/", str(source)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=85, check=False)
        pages = list(Path(scratch).glob("*.svg"))
        if result.returncode != 0 or len(pages) != 1:
            raise RuntimeError("Native schematic SVG requires exactly one verified plotted sheet")
        payload = pages[0].read_bytes()
    if len(payload) > 4_000_000 or b"<svg" not in payload[:1000]:
        raise ValueError("Invalid or oversized native schematic SVG")
    low = payload.lower()
    if any(
        token in low
        for token in (
            b"<script",
            b"<foreignobject",
            b"<iframe",
            b"<image",
            b"<use ",
            b"onload=",
            b"onclick=",
            b"javascript:",
            b"data:text/html",
            b"href=",
            b"url(",
            b"@import",
            b"<style",
        )
    ):
        raise ValueError("Native schematic SVG contains unsupported active or linked content")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ValueError("Invalid native schematic SVG markup") from exc
    if root.tag != "{http://www.w3.org/2000/svg}svg" or not root.get("viewBox"):
        raise ValueError("Missing native schematic SVG viewport")
    if not root.get("width", "").endswith("mm") or not root.get("height", "").endswith("mm"):
        raise ValueError("Native KiCad schematic plot unit is not millimeters")
    try:
        x0, y0, width, height = (float(x) for x in root.attrib["viewBox"].split())
    except (ValueError, KeyError) as exc:
        raise ValueError("Invalid KiCad SVG coordinate viewport") from exc
    if not all(math.isfinite(x) for x in (x0, y0, width, height)) or width <= 0 or height <= 0:
        raise ValueError("Unbounded native schematic SVG viewport")
    _check_native_svg_target(target)
    # Atomically replace the output inode rather than truncating an existing
    # hard-linked file or following a swapped leaf symlink.
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".review-sch-safe-", dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        _check_native_svg_target(target)
        temporary.replace(target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "viewbox": root.get("viewBox"),
        "uri": "data:image/svg+xml;base64," + base64.b64encode(payload).decode("ascii"),
    }


def native_schematic_comparison(source: Path, candidate: Path, output: Path) -> dict:
    """Optional native *netlist/ERC* comparison; never asserts PCB synchronization.

    An exported KiCad netlist does not attest to drawing/layout geometry,
    hidden implementation rules, or a qualified electrical review.
    """
    inputs = (source, candidate)
    if any(
        p.is_symlink() or not p.is_file() or p.suffix != ".kicad_sch" or p.stat().st_size > 4_000_000 for p in inputs
    ):
        raise ValueError("Unsafe, missing or oversized native schematic input")
    source, candidate = (p.resolve(strict=True) for p in inputs)
    if source == candidate or output.resolve() in (source, candidate):
        raise ValueError("Schematic comparison requires two separate source files")
    start = (digest(source), digest(candidate))
    sidecars = {}
    for suffix, max_size in ((".kicad_pro", 3_000_000), (".kicad_dru", 1_000_000)):
        hashes = []
        for sch in (source, candidate):
            sidecar = sch.with_suffix(suffix)
            if sidecar.is_symlink() or (sidecar.exists() and not sidecar.is_file()):
                raise ValueError("Unsafe native schematic project-rule sidecar")
            if sidecar.exists() and sidecar.stat().st_size > max_size:
                raise ValueError("Oversized native schematic project-rule sidecar")
            hashes.append(digest(sidecar) if sidecar.exists() else None)
        if hashes[0] != hashes[1]:
            raise ValueError("Native schematic source/proposal project-rule bytes differ")
        sidecars[suffix] = hashes[0]

    from review_studio_schematic_eco import _erc, _netlist, _snapshot

    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("Native KiCad CLI required for schematic semantic comparison")
    # Distinct outputs from the PCB DRC and source files; source inputs read only.
    prefix = output.with_suffix("")
    before_net = prefix.with_name(prefix.name + ".sch-before-netlist.xml")
    after_net = prefix.with_name(prefix.name + ".sch-after-netlist.xml")
    before_erc = prefix.with_name(prefix.name + ".sch-before-erc.rpt")
    after_erc = prefix.with_name(prefix.name + ".sch-after-erc.rpt")
    comps0, nets0 = _snapshot(_netlist(cli, source, before_net))
    comps1, nets1 = _snapshot(_netlist(cli, candidate, after_net))
    erc0, erc1 = _erc(cli, source, before_erc), _erc(cli, candidate, after_erc)
    if not comps0 or not comps1:
        raise ValueError("Native schematic netlist lacks reviewable components")

    changed_values = [
        {"ref": ref, "before": comps0[ref]["value"], "after": comps1[ref]["value"]}
        for ref in sorted(comps0.keys() & comps1.keys())
        if comps0[ref]["value"] != comps1[ref]["value"]
    ]
    metadata_changed = [
        ref for ref in sorted(comps0.keys() & comps1.keys()) if comps0[ref]["unchanged"] != comps1[ref]["unchanged"]
    ]

    def named_nets(rows: list[tuple]) -> dict:
        names = {name: nodes for name, nodes in rows}
        if len(names) != len(rows) or None in names:
            raise ValueError("Ambiguous KiCad exported net names")
        return names

    net0, net1 = named_nets(nets0), named_nets(nets1)
    changed_nets = sorted(name for name in net0.keys() | net1.keys() if net0.get(name) != net1.get(name))
    findings0 = erc_findings(before_erc.read_text(encoding="utf-8"), set(comps0), erc0[0])
    findings1 = erc_findings(after_erc.read_text(encoding="utf-8"), set(comps1), erc1[0])
    svg0 = native_schematic_svg(cli, source, prefix.with_name(prefix.name + ".sch-before.svg"))
    svg1 = native_schematic_svg(cli, candidate, prefix.with_name(prefix.name + ".sch-after.svg"))
    if svg0["viewbox"] != svg1["viewbox"]:
        raise ValueError("KiCad schematic plot viewports differ: unsafe visual overlay")
    from review_studio_native_kicad import schematic_symbols

    anchors0 = schematic_symbols(source.read_text(encoding="utf-8"))
    anchors1 = schematic_symbols(candidate.read_text(encoding="utf-8"))
    if set(anchors0) != set(comps0) or set(anchors1) != set(comps1):
        raise ValueError("Single-page native schematic symbols and netlist references disagree")
    px, py, pw, ph = (float(value) for value in svg0["viewbox"].split())
    for symbol in (*anchors0.values(), *anchors1.values()):
        if not (px <= symbol["x"] <= px + pw and py <= symbol["y"] <= py + ph):
            raise ValueError("KiCad symbol position outside verified plotted viewport")
    if (digest(source), digest(candidate)) != start:
        raise ValueError("Schematic source changed during native comparison")
    for suffix in sidecars:
        for sch in (source, candidate):
            sidecar = sch.with_suffix(suffix)
            if sidecar.is_symlink() or (digest(sidecar) if sidecar.is_file() else None) != sidecars[suffix]:
                raise ValueError("Schematic native rule sidecar changed during verification")
    return {
        "kind": "native_kicad_exported_netlist_and_erc_only",
        "source_sha256": start[0],
        "proposed_sha256": start[1],
        "project_sha256": sidecars[".kicad_pro"],
        "custom_rules_sha256": sidecars[".kicad_dru"],
        "added_components": sorted(comps1.keys() - comps0.keys()),
        "removed_components": sorted(comps0.keys() - comps1.keys()),
        "changed_values": changed_values,
        "changed_metadata_refs": metadata_changed,
        "changed_nets": changed_nets,
        "symbol_anchors": {
            "current": anchors0,
            "proposed": anchors1,
            "scope": "Actual single-sheet KiCad source instance XY in millimeters; graphical highlight only",
        },
        "erc_findings_before": findings0,
        "erc_findings_after": findings1,
        "svg": {
            "current": svg0,
            "proposed": svg1,
            "scope": "One verified native KiCad sheet; no geometric symbol cross-probe or electrical parity claim",
        },
        "erc_before": {"total": erc0[0], "errors": erc0[1], "warnings": erc0[2]},
        "erc_after": {"total": erc1[0], "errors": erc1[1], "warnings": erc1[2]},
        "native_export_sha256": {
            "netlist_before": digest(before_net),
            "netlist_after": digest(after_net),
            "erc_before": digest(before_erc),
            "erc_after": digest(after_erc),
        },
        "pcb_schematic_parity_verified": False,
        "electrical_approval": False,
        "scope": (
            "KiCad native exported component/netlist semantics and ERC counters only; "
            "drawing geometry and PCB synchronization not established"
        ),
    }


def native_reported_findings(report: dict, limit: int = 8) -> tuple[list[dict], int]:
    """Expose a bounded subset of genuine KiCad DRC findings, not inferred approval."""
    rows = report["violations"]
    result = []
    for row in rows[:limit]:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(k), str) for k in ("type", "severity", "description")
        ):
            raise ValueError("Unexpected native KiCad DRC finding")
        result.append({"rule": row["type"], "severity": row["severity"], "description": row["description"]})
    return result, max(0, len(rows) - len(result))


def evidence_catalog(document: dict) -> list[dict]:
    """Stable source-derived review references, no free-text/fabrication claims."""
    entries = []
    for index, change in enumerate(document["changed"]):
        entries.append(
            {
                "id": f"pcb-change:{index}",
                "kind": "native_pcb_eco",
                "ref": change["ref"],
                "rule": "verified_footprint_translation",
                "summary": f"Footprint {change['ref']} translated; native PCB DRC evidence is separate",
            }
        )
    entries.append(
        {
            "id": "pcb-drc:summary",
            "kind": "native_pcb_drc",
            "ref": None,
            "rule": "native_drc_scope",
            "summary": (
                f"Native PCB DRC violations {document['drc']['before_rules']} to {document['drc']['after_rules']}"
            ),
        }
    )
    for index, finding in enumerate(document["drc"].get("reported_findings", [])):
        entries.append(
            {
                "id": f"pcb-drc:finding:{index}",
                "kind": "native_pcb_drc_finding",
                "ref": None,
                "rule": finding["rule"],
                "summary": f"{finding['severity'].upper()}: {finding['description']}",
            }
        )
    schematic = document.get("schematic")
    if schematic is not None:
        for index, change in enumerate(schematic["changed_values"]):
            entries.append(
                {
                    "id": f"schematic-value:{index}",
                    "kind": "native_netlist_value",
                    "ref": change["ref"],
                    "rule": "component_value_changed",
                    "summary": f"{change['ref']} value {change['before']} to {change['after']}",
                }
            )
        for index, finding in enumerate(schematic["erc_findings_after"]):
            entries.append(
                {
                    "id": f"schematic-erc:{index}",
                    "kind": "native_schematic_erc",
                    "ref": finding["ref"],
                    "rule": finding["rule"],
                    "summary": finding["message"],
                }
            )
    crossprobe = document.get("crossprobe")
    if crossprobe is not None:
        totals = crossprobe["totals"]
        entries.append(
            {
                "id": "pin-net:summary",
                "kind": "native_pin_pad_net_scoped_diagnostics",
                "ref": None,
                "rule": "scoped_pin_net_consistency_only",
                "summary": (
                    f"Native scoped pins: {totals['matched']} matched, "
                    f"{totals['mismatch']} mismatched, {totals['unverifiable']} unverifiable; "
                    "global board parity and electrical approval NOT verified"
                ),
            }
        )
        for index, finding in enumerate(crossprobe["rows"]):
            entries.append(
                {
                    "id": f"pin-net:{index}",
                    "kind": "native_pin_pad_net_scoped_diagnostics",
                    "ref": finding["ref"],
                    "rule": finding["reason"],
                    "summary": (
                        f"{finding['phase']} {finding['ref']} pin {finding['pin']}: "
                        f"{finding['status']}; schematic {finding['schematic_net']}, "
                        f"PCB {finding['pcb_net']}"
                    ),
                }
            )
    return entries


def canonical_decision_hash(document: dict) -> str:
    """Stable same-state identity, excluding KiCad CLI export timestamps.

    Raw SVG/netlist/ERC bytes and their digests stay available as evidence,
    but are volatile even for byte-identical source and equivalent outputs.
    """
    canonical = {key: value for key, value in document.items() if key not in ("native_svg", "schematic", "state_hash")}
    schematic = document.get("schematic")
    if schematic is not None:
        canonical["schematic"] = {
            key: value for key, value in schematic.items() if key not in ("svg", "native_export_sha256")
        }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def create_review(
    source: Path,
    candidate: Path,
    evidence: Path,
    output: Path,
    schematic_source: Path | None = None,
    schematic_candidate: Path | None = None,
) -> dict:
    if (schematic_source is None) != (schematic_candidate is None):
        raise ValueError("Both native schematic source and candidate must be provided together")
    source, candidate, evidence = (p.resolve(strict=True) for p in (source, candidate, evidence))
    # The report belongs to the native candidate's isolated workspace.
    # A caller-supplied --output may choose the HTML leaf, not a different
    # filesystem destination that could overwrite unrelated user data.
    candidate_dir = candidate.parent
    if output.suffix != ".html" or output.parent.resolve(strict=False) != candidate_dir:
        raise ValueError("Native review output must be an HTML child of the candidate directory")
    output = candidate_dir / output.name
    if source == candidate or output.resolve() in (source, candidate, evidence):
        raise ValueError("ECO reviewer must not edit or compare the same source file")
    if any(p.stat().st_size > 15_000_000 for p in (source, candidate, evidence)):
        raise ValueError("Unexpected input size")
    source_sha, candidate_sha = digest(source), digest(candidate)
    evidence_sha = digest(evidence)
    proof = json.loads(evidence.read_text())
    before, after = _read_kicad(source), _read_kicad(candidate)
    changes = check_native_board_transition(before, after, proof, source_sha, candidate_sha)
    rule_context = verified_rule_context(source, candidate, proof)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Refuse symlinked output artifacts, including reports that native KiCad CLI
    # would otherwise open for writing and the offline HTML decision destination.
    planned = [output, output.with_suffix(".state.json")]
    planned += [
        output.with_suffix(suffix)
        for suffix in (".before-drc.json", ".after-drc.json", ".current.svg", ".proposed.svg")
    ]
    prefix = output.with_suffix("")
    planned += [
        prefix.with_name(prefix.name + suffix)
        for suffix in (
            ".sch-before-netlist.xml",
            ".sch-after-netlist.xml",
            ".sch-before-erc.rpt",
            ".sch-after-erc.rpt",
            ".sch-before.svg",
            ".sch-after.svg",
        )
    ]
    if any(p.is_symlink() or (p.exists() and not p.is_file()) for p in planned):
        raise ValueError("Unsafe native review output artifact")
    a = native_drc(source, output.with_suffix(".before-drc.json"))
    b = native_drc(candidate, output.with_suffix(".after-drc.json"))
    if any(
        a.get(key) != b.get(key)
        for key in ("ignored_checks", "included_severities", "kicad_version", "schematic_parity")
    ):
        raise ValueError("KiCad engine, active rules or severity reporting differs")
    from review_studio_pcb_eco import compare_drc

    native_result = compare_drc(a, b)
    # A local file may change between hashing and invoking KiCad; reject stale
    # results rather than emitting a misleading source-hash-bound decision view.
    verified_rule_context(source, candidate, proof)
    if (digest(source), digest(candidate), digest(evidence)) != (source_sha, candidate_sha, evidence_sha):
        raise ValueError("Input board or ECO evidence changed during native verification")
    if any(proof.get("native_drc", {}).get(key) != value for key, value in native_result.items()):
        raise ValueError("Fresh independent KiCad DRC differs from ECO evidence")
    schematic = (
        native_schematic_comparison(schematic_source, schematic_candidate, output)
        if schematic_source is not None and schematic_candidate is not None
        else None
    )
    crossprobe = None
    if schematic is not None:
        from review_studio_pin_net_crossprobe import scoped_pin_net_crossprobe

        prefix = output.with_suffix("")
        net_before = prefix.with_name(prefix.name + ".sch-before-netlist.xml")
        net_after = prefix.with_name(prefix.name + ".sch-after-netlist.xml")
        expected_net_digests = schematic["native_export_sha256"]
        if (
            digest(net_before) != expected_net_digests["netlist_before"]
            or digest(net_after) != expected_net_digests["netlist_after"]
        ):
            raise ValueError("Native KiCad exported netlist bytes changed during crossprobe")
        pcb_pro = rule_context["project_sha256"]
        pcb_dru = rule_context["custom_rules_sha256"]
        project_linked = (
            pcb_pro is not None
            and pcb_pro == schematic["project_sha256"]
            and pcb_dru == schematic["custom_rules_sha256"]
        )
        crossprobe = scoped_pin_net_crossprobe(
            net_before,
            net_after,
            before,
            after,
            [change["ref"] for change in changes],
            project_rules_crosslinked=project_linked,
        )
        if (
            digest(net_before) != expected_net_digests["netlist_before"]
            or digest(net_after) != expected_net_digests["netlist_after"]
        ):
            raise ValueError("Native netlist changed while crossprobe was evaluated")
    before_vector = native_svg(source, output.with_suffix(".current.svg"))
    after_vector = native_svg(candidate, output.with_suffix(".proposed.svg"))
    verified_rule_context(source, candidate, proof)
    if schematic is not None and schematic_source is not None and schematic_candidate is not None:
        native_schematic_comparison_inputs = (schematic_source, schematic_candidate)
        for sch_input in native_schematic_comparison_inputs:
            for suffix, key in ((".kicad_pro", "project_sha256"), (".kicad_dru", "custom_rules_sha256")):
                sidecar = sch_input.with_suffix(suffix)
                actual = digest(sidecar) if sidecar.is_file() and not sidecar.is_symlink() else None
                if sidecar.is_symlink() or (sidecar.exists() and not sidecar.is_file()) or actual != schematic[key]:
                    raise ValueError("Schematic KiCad rule context changed during review rendering")
        if any(
            digest(p) != s
            for p, s in zip(
                native_schematic_comparison_inputs,
                (schematic["source_sha256"], schematic["proposed_sha256"]),
                strict=True,
            )
        ):
            raise ValueError("Schematic state changed during review rendering")
    reported_findings, omitted_findings = native_reported_findings(b)
    document = {
        "schema_version": 1,
        "kind": "unsigned_local_design_change_decision_not_approval",
        "source_sha256": source_sha,
        "proposed_sha256": candidate_sha,
        "evidence_sha256": evidence_sha,
        "decision_hash_contract": "native_source_and_semantic_evidence_v2",
        "native_svg": {
            "current": before_vector,
            "proposed": after_vector,
            "scope": "Native F.Cu/F.SilkS/Edge.Cuts; no fabrication or 3D fit evidence",
        },
        "current": before["footprints"],
        "proposed": after["footprints"],
        "changed": changes,
        "schematic": schematic,
        "rule_context": rule_context,
        "board_origin_mm": before["origin"],
        "board_size_mm": before["size"],
        "drc": {
            **native_result,
            "ignored_checks": len(a["ignored_checks"]),
            "engine": a["kicad_version"],
            "included_severities": a["included_severities"],
            "reported_findings": reported_findings,
            "omitted_findings": omitted_findings,
        },
        "approval_supported": False,
        "fabrication_approved": False,
        "electrically_approved": False,
        "schematic_erc_verified": schematic is not None,
    }
    # Preserve legacy PCB-only state identity with no optional schematic supplied.
    if crossprobe is not None:
        document["crossprobe"] = crossprobe
    document["audit_evidence_catalog"] = evidence_catalog(document)
    document["state_hash"] = canonical_decision_hash(document)
    template = TEMPLATE.read_text()
    if template.count("__CHANGE_DATA__") != 1:
        raise ValueError("Unsafe HTML review template contract")
    html = template.replace("__CHANGE_DATA__", json.dumps(document, ensure_ascii=True).replace("<", "\\u003c"))
    html = apply_offline_csp(html)
    output.write_text(html)
    output.with_suffix(".state.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "candidate", "evidence", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--schematic-source", type=Path)
    parser.add_argument("--schematic-candidate", type=Path)
    args = parser.parse_args()
    result = create_review(
        args.source,
        args.candidate,
        args.evidence,
        args.output,
        args.schematic_source,
        args.schematic_candidate,
    )
    print("REAL_KICAD_ECO_BEFORE_AFTER_STATE_BOUND_REVIEW=PASS", result["state_hash"])


if __name__ == "__main__":
    main()
