# pyright: reportMissingImports=false
#!/usr/bin/python3
"""Copy-on-write KiCad 10 PCB footprint ECO; deny routed-pad moves and new DRC findings.

Only a translation and/or quarter-turn of one unrouted footprint is supported.
Fabrication, electrical correctness, fit and source updates remain unapproved.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pcbnew as pcb

REFERENCE = re.compile(r"^[A-Za-z]{1,5}[1-9][0-9]{0,5}$")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vec(position: Any) -> tuple[int, int]:
    return int(position.x), int(position.y)


def state(board: Any) -> dict:
    """Capture authored KiCad metadata before native save/reopen round-trip."""
    footprints = {}
    for fp in board.GetFootprints():
        ref = fp.GetReference()
        if not REFERENCE.fullmatch(ref) or ref in footprints:
            raise ValueError("KiCad footprint references are missing, duplicated or unsupported")
        pads = {}
        for pad in fp.Pads():
            uid = pad.m_Uuid.AsString()
            if uid in pads:
                raise ValueError("KiCad duplicate pad identity")
            pads[uid] = (
                pad.GetNumber(),
                pad.GetNetname(),
                pad.GetNetCode(),
                vec(pad.GetPosition()),
                pad.GetLayerSet().FmtBin(),
                vec(pad.GetSize()),
                vec(pad.GetDrillSize()),
                int(pad.GetShape()),
                int(pad.GetAttribute()),
                pad.GetOrientationDegrees(),
            )
        footprints[ref] = {
            "uuid": fp.m_Uuid.AsString(),
            "value": fp.GetValue(),
            "layer": fp.GetLayer(),
            "library": fp.GetFPIDAsString(),
            "pos": vec(fp.GetPosition()),
            "angle": fp.GetOrientationDegrees(),
            "locked": fp.IsLocked(),
            "pads": pads,
        }
    traces = {}
    for item in board.GetTracks():
        traces[item.m_Uuid.AsString()] = (
            item.GetNetCode(),
            item.GetNetname(),
            vec(item.GetStart()),
            vec(item.GetEnd()),
            item.GetWidth(),
            item.GetLayer(),
            item.GetLayerSet().FmtBin(),
            vec(item.GetMid()) if isinstance(item, pcb.PCB_ARC) else None,
            (
                item.GetDrillValue(),
                item.GetViaType(),
            )
            if isinstance(item, pcb.PCB_VIA)
            else None,
        )
    return {"footprints": footprints, "tracks": traces, "zones": board.GetAreaCount()}


def eligible(board: Any, reference: str, dx: int, dy: int, rotation: int = 0) -> Any:
    candidates = [fp for fp in board.GetFootprints() if fp.GetReference() == reference]
    if not REFERENCE.fullmatch(reference) or len(candidates) != 1:
        raise ValueError("Select an existing, unique native KiCad footprint reference")
    fp = candidates[0]
    if fp.IsLocked():
        raise ValueError("Locked footprint cannot be edited")
    if board.GetAreaCount():
        raise ValueError("Copper zones require refill-aware routing; footprint edit blocked")
    # KiCad's native shape bounding boxes include track width, arcs and vias.
    # Endpoint-only checks miss traces crossing a pad between their endpoints.
    # Block contacts at both locations: landing on same-net copper could create
    # an unintended connection without generating a DRC clearance violation.
    copper = [track.GetBoundingBox() for track in board.GetTracks()]
    if any(box.Intersects(pad.GetBoundingBox()) for pad in fp.Pads() for box in copper):
        raise ValueError(f"{reference} has pad-adjacent copper; real drag routing required")
    # Both the original and final native pad bounds must be clear. KiCad
    # handles rotation of odd pad shapes and footprint-defined local origins.
    # A DRC comparison alone can miss same-net copper connectivity changes.
    original_pos = fp.GetPosition()
    fp.SetPosition(pcb.VECTOR2I(original_pos.x + dx, original_pos.y + dy))
    if rotation:
        fp.SetOrientationDegrees(fp.GetOrientationDegrees() + rotation)
    if any(box.Intersects(pad.GetBoundingBox()) for pad in fp.Pads() for box in copper):
        raise ValueError(f"{reference} has pad-adjacent copper; real drag routing required")
    return fp


def command(args: list[str], timeout: int = 65) -> None:
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError("Native KiCad command failed (exit " + str(result.returncode) + ")")


def drc(cli: str, source: Path, report: Path) -> dict:
    command([cli, "pcb", "drc", "--format", "json", "--severity-all", "--output", str(report), str(source)], 95)
    result = json.loads(report.read_text())
    if (
        not isinstance(result.get("violations"), list)
        or not isinstance(result.get("unconnected_items"), list)
        or not isinstance(result.get("ignored_checks"), list)
        or result.get("coordinate_units") != "mm"
    ):
        raise RuntimeError("Unexpected native KiCad DRC report; editing blocked")
    return result


def attest_custom_rule_loading(cli: str, root: Path, board: Path, rules: Path, source_sha: str) -> bool:
    """Prove a disposable sentinel rule reaches native KiCad DRC.

    This checks loader execution, NOT the semantics of every supplied rule,
    cross-editor parity, or fabrication suitability. If a sentinel cannot
    create a distinguishable KiCad finding, fail closed.
    """
    probe = root / "rule-loader-probe"
    probe.mkdir()
    test_board = probe / board.name
    shutil.copyfile(board, test_board)
    project = board.with_suffix(".kicad_pro")
    if not project.is_file():
        raise RuntimeError("Custom KiCad rules require their matching project")
    shutil.copyfile(project, probe / project.name)
    name = "ZAPTRACE_RULE_LOADER_PROBE_" + source_sha[:16]
    original_rules = rules.read_bytes()
    if name.encode() in original_rules:
        raise RuntimeError("Custom rule test marker collides with source rules")
    sentinel = '\n(rule "' + name + '"\n  (constraint courtyard_clearance (min 1000mm)))\n'
    (probe / rules.name).write_bytes(original_rules + sentinel.encode("ascii"))
    output = drc(cli, test_board, root / "loader-probe-drc.json")
    matches = [
        v
        for v in output["violations"]
        if v.get("type") == "courtyards_overlap" and name in str(v.get("description", ""))
    ]
    if not matches:
        raise RuntimeError("Native KiCad did not prove custom .kicad_dru loading; ECO blocked")
    return True


def signature(item: dict) -> tuple:
    items = item.get("items")
    if not isinstance(items, list) or any(not isinstance(x.get("uuid"), str) for x in items):
        raise RuntimeError("Native KiCad DRC item identities unavailable; editing blocked")
    return (
        item.get("severity"),
        item.get("type"),
        item.get("description"),
        tuple(sorted(x["uuid"] for x in items)),
    )


def compare_drc(before: dict, after: dict) -> dict:
    for name in ("ignored_checks", "included_severities", "kicad_version", "schematic_parity"):
        if before.get(name) != after.get(name):
            raise RuntimeError("KiCad active DRC rules, severities or engine changed")
    additions = Counter(map(signature, after["violations"])) - Counter(map(signature, before["violations"]))
    if additions:
        raise RuntimeError(f"PCB move introduced {sum(additions.values())} real DRC violation(s); copy blocked")
    if len(after["unconnected_items"]) > len(before["unconnected_items"]):
        raise RuntimeError("Native KiCad unconnected count increased; move blocked")
    return {
        "before_rules": len(before["violations"]),
        "after_rules": len(after["violations"]),
        "before_open": len(before["unconnected_items"]),
        "after_open": len(after["unconnected_items"]),
        "new_drc_rules": 0,
        "active_rules_unchanged": True,
    }


def plot(cli: str, source: Path, target: Path) -> str:
    command(
        [
            cli,
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
            str(target),
            str(source),
        ],
        65,
    )
    image = target.read_bytes()
    if b"<svg" not in image[:1200] or len(image) > 4_000_000:
        raise RuntimeError("Native KiCad copper SVG missing or too large")
    return "data:image/svg+xml;base64," + base64.b64encode(image).decode()


def verify_roundtrip(
    before: dict,
    after: dict,
    target: str,
    dx: int,
    dy: int,
    rotation: int = 0,
    expected_target: dict | None = None,
) -> None:
    if (
        before["tracks"] != after["tracks"]
        or before["zones"] != after["zones"]
        or set(before["footprints"]) != set(after["footprints"])
    ):
        raise RuntimeError("Native board copper, zones or component inventory changed")
    for ref, first in before["footprints"].items():
        second = after["footprints"][ref]
        delta = (dx, dy) if ref == target else (0, 0)
        expected = (first["pos"][0] + delta[0], first["pos"][1] + delta[1])
        if second["pos"] != expected:
            raise RuntimeError("Native footprint coordinates differ beyond approved ECO")
        for name in ("uuid", "value", "locked", "layer", "library"):
            if first[name] != second[name]:
                raise RuntimeError("Native footprint metadata changed unexpectedly")
        # KiCad normalizes 270° to -90° depending on version.
        expected_angle = first["angle"] + (rotation if ref == target else 0)
        if abs((second["angle"] - expected_angle + 180) % 360 - 180) > 1e-7:
            raise RuntimeError("Native footprint orientation changed beyond approved ECO")
        if set(first["pads"]) != set(second["pads"]):
            raise RuntimeError("Native pad identity changed unexpectedly")
        for uid, old in first["pads"].items():
            new = second["pads"][uid]
            coords = (old[3][0] + delta[0], old[3][1] + delta[1])
            if ref == target and rotation:
                # Capture native KiCad's expected transformed pad centers
                # before serializing; verify saved PCB did not shift any pad.
                if expected_target is None or uid not in expected_target["pads"]:
                    raise RuntimeError("Native rotated pad identity unavailable")
                coords = expected_target["pads"][uid][3]
            if old[:3] != new[:3] or coords != new[3] or old[4:9] != new[4:9]:
                raise RuntimeError("Native pad identity, dimensions, net, shape or layers changed")
            expected_pad_angle = old[9] + (rotation if ref == target else 0)
            if abs((new[9] - expected_pad_angle + 180) % 360 - 180) > 1e-7:
                raise RuntimeError("Native pad angle changed beyond approved footprint rotation")


def create(
    source: Path,
    output: Path,
    reference: str,
    dx_mm: float,
    dy_mm: float,
    rotation: int = 0,
) -> dict:
    source = source.resolve(strict=True)
    output = output.absolute()
    if source.suffix != ".kicad_pcb" or not source.is_file() or source.stat().st_size > 10_000_000:
        raise ValueError("Existing native KiCad board under 10 MB required")
    if not REFERENCE.fullmatch(reference):
        raise ValueError("Invalid KiCad reference")
    for x in (dx_mm, dy_mm):
        if not math.isfinite(x) or abs(x) > 5.0 or abs(x * 20 - round(x * 20)) > 1e-7:
            raise ValueError("Grid is 0.05 mm, offset must be ±5 mm or less")
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation not in (-90, 0, 90, 180):
        raise ValueError("Footprint rotation must be one quarter-turn: -90, 0, 90 or 180 degrees")
    if dx_mm == 0 and dy_mm == 0 and rotation == 0:
        raise ValueError("Zero-distance ECO not allowed")
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source.parent):
        raise ValueError("New, separate ECO output outside original source folder required")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("ECO parent directory invalid")
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("Native KiCad CLI unavailable")
    original = source.read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    with tempfile.TemporaryDirectory(prefix=".zaptrace-pcb-eco-", dir=output.parent) as temp:
        root = Path(temp)
        first = root / "before"
        second = root / "after"
        first.mkdir()
        second.mkdir()
        raw = first / source.name
        changed = second / source.name
        raw.write_bytes(original)
        # The project and custom-rule files are a matched KiCad context.
        # Omitting .kicad_dru silently changes production DRC semantics.
        context: dict[str, tuple[Path, str]] = {}
        for suffix, max_bytes in ((".kicad_pro", 3_000_000), (".kicad_dru", 1_000_000)):
            path = source.with_suffix(suffix)
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError("Native KiCad design-rule sidecar is not a regular file")
            if path.is_file():
                if path.stat().st_size > max_bytes:
                    raise ValueError("Native KiCad project rules oversized")
                context[suffix] = path, sha(path)
        if ".kicad_dru" in context and ".kicad_pro" not in context:
            raise ValueError("Custom KiCad DRC rules without their project context are blocked")
        for folder in (first, second):
            for path, _digest in context.values():
                shutil.copyfile(path, folder / path.name)
        board = pcb.LoadBoard(str(raw))
        if board is None:
            raise ValueError("KiCad rejected PCB")
        before = state(board)
        dx, dy = pcb.FromMM(dx_mm), pcb.FromMM(dy_mm)
        footprint = eligible(board, reference, dx, dy, rotation)
        old = before["footprints"][reference]["pos"]
        new = vec(footprint.GetPosition())
        staged_target = state(board)["footprints"][reference]
        pcb.SaveBoard(str(changed), board)
        reopened = pcb.LoadBoard(str(changed))
        if reopened is None:
            raise RuntimeError("Cannot reopen authored KiCad PCB")
        verify_roundtrip(before, state(reopened), reference, dx, dy, rotation, staged_target)
        drc_original = drc(cli, raw, root / "before-drc.json")
        rule_loader_verified = (
            attest_custom_rule_loading(cli, root, raw, first / raw.with_suffix(".kicad_dru").name, original_sha)
            if ".kicad_dru" in context
            else False
        )
        drc_modified = drc(cli, changed, root / "after-drc.json")
        summary = compare_drc(drc_original, drc_modified)
        before_svg = plot(cli, raw, root / "before.svg")
        after_svg = plot(cli, changed, root / "after.svg")
        if sha(source) != original_sha or any(sha(path) != digest for path, digest in context.values()):
            raise RuntimeError("Original KiCad PCB or project rule context changed during validation")
        output.mkdir(mode=0o700)
        try:
            copy = output / "source.kicad_pcb"
            copy.write_bytes(changed.read_bytes())
            for suffix, (path, digest) in context.items():
                # Reuse the exact sidecar snapshot validated by KiCad, not an
                # original file that may change after the final hash check.
                destination = output / ("source" + suffix)
                shutil.copyfile(first / path.name, destination)
                if sha(destination) != digest:
                    raise RuntimeError("Published KiCad project rule copy differs from verified snapshot")
            for name in ("before-drc.json", "after-drc.json"):
                shutil.copyfile(root / name, output / name)
            result = {
                "type": "PCB_UNROUTED_FOOTPRINT_PLACEMENT_ECO",
                "status": "native_drc_verified_copy_not_original",
                "rotation_degrees": rotation,
                "old_angle_degrees": before["footprints"][reference]["angle"],
                "new_angle_degrees": staged_target["angle"],
                "ref": reference,
                "old_mm": [pcb.ToMM(x) for x in old],
                "new_mm": [pcb.ToMM(x) for x in new],
                "source_sha256": original_sha,
                "working_sha256": sha(copy),
                "native_drc": summary,
                "rule_context": {
                    "mode": (
                        "project_with_custom_rules"
                        if ".kicad_dru" in context
                        else "project"
                        if ".kicad_pro" in context
                        else "defaults_without_project"
                    ),
                    "project_sha256": context[".kicad_pro"][1] if ".kicad_pro" in context else None,
                    "custom_rules_sha256": context[".kicad_dru"][1] if ".kicad_dru" in context else None,
                    "custom_rule_loader_probe_passed": rule_loader_verified,
                    "effective_rules_independently_verified": False,
                },
                "fabApproved": False,
                "electricallyApproved": False,
            }
            (output / "ECO_EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n")
            template = Path(__file__).with_name("review_studio_pcb_eco_template.html").read_text()
            substitutions = {
                "REF": reference,
                "BEFORE_XY": str(result["old_mm"]),
                "AFTER_XY": str(result["new_mm"]),
                "BEFORE_ANGLE": str(result["old_angle_degrees"]),
                "AFTER_ANGLE": str(result["new_angle_degrees"]),
                "BEFORE_SVG": before_svg,
                "AFTER_SVG": after_svg,
                "BEFORE_DRC": str(summary["before_rules"]),
                "AFTER_DRC": str(summary["after_rules"]),
                "BEFORE_OPEN": str(summary["before_open"]),
                "AFTER_OPEN": str(summary["after_open"]),
                "SOURCE_SHA": original_sha,
                "COPY_SHA": result["working_sha256"],
            }
            for key, value in substitutions.items():
                template = template.replace("__" + key + "__", value)
            (output / "PREVIEW.html").write_text(template)
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--dx", required=True, type=float)
    parser.add_argument("--dy", required=True, type=float)
    parser.add_argument("--rotate", default=0, type=int, choices=(-90, 0, 90, 180))
    args = parser.parse_args()
    try:
        result = create(args.board, args.output, args.ref, args.dx, args.dy, args.rotate)
    except (OSError, RuntimeError, ValueError, UnicodeError, subprocess.TimeoutExpired) as exc:
        print("PCB ECO BLOCKED:", str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    print("NATIVE PCB VISUAL:", args.output / "PREVIEW.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
