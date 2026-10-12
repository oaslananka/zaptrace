#!/usr/bin/python3
# pyright: reportMissingImports=false
"""Guarded *single straight* KiCad 10 copper link on an isolated portable project copy.

No routing is committed to the input. Strict KiCad DRC, schematic parity,
source/library SHA hashes and native PCB metadata must all survive. This
experimental proof is NOT a router, copper completion or manufacturing signoff.
"""

from __future__ import annotations

import argparse
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
from review_studio_pcb_eco import signature, state

PROJECT_SIDECARS = (".kicad_sch", ".kicad_pro")
PORTABLE_FILES = ("fp-lib-table", "sym-lib-table", "ZapTrace.kicad_sym")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _portable_sources(board: Path) -> list[Path]:
    if board.suffix != ".kicad_pcb" or board.is_symlink() or not board.is_file():
        raise ValueError("Native regular KiCad PCB required")
    folder = board.parent
    paths = [board, *(board.with_suffix(suffix) for suffix in PROJECT_SIDECARS)]
    paths.extend(folder / name for name in PORTABLE_FILES)
    library = folder / "ZapTrace.pretty"
    if not library.is_dir() or library.is_symlink():
        raise ValueError("Verified self-contained ZapTrace.pretty source required")
    if any(not path.is_file() or path.is_symlink() for path in paths):
        raise ValueError("Project, schematic and portable library sidecars must exist as regular files")
    if (folder / (board.stem + ".kicad_dru")).exists():
        raise ValueError("Custom KiCad design rules require separate independent loader proof")
    expected_uri = {
        "fp-lib-table": "${KIPRJMOD}/ZapTrace.pretty",
        "sym-lib-table": "${KIPRJMOD}/ZapTrace.kicad_sym",
    }
    for table, expected in expected_uri.items():
        content = (folder / table).read_text()
        actual_uris = re.findall(r'\(uri\s+"([^"]+)"\)', content)
        if actual_uris != [expected] or len(re.findall(r"\(lib\s+\(", content)) != 1:
            raise ValueError("Only exact project-local ZapTrace library tables are supported")
    members = sorted(library.iterdir())
    if (
        not members
        or len(members) > 75
        or any(not path.is_file() or path.is_symlink() or path.suffix != ".kicad_mod" for path in members)
    ):
        raise ValueError("Unexpected or linked portable footprint assets")
    paths.extend(members)
    if sum(path.stat().st_size for path in paths) > 28_000_000:
        raise ValueError("Oversized local KiCad asset collection")
    return paths


def _clone_assets(paths: list[Path], source_folder: Path, destination: Path) -> None:
    destination.mkdir()
    for src in paths:
        relative = src.relative_to(source_folder)
        output = destination / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, output)


def _native_report(cli: str, source: Path, output: Path) -> dict:
    result = subprocess.run(
        [
            cli,
            "pcb",
            "drc",
            "--schematic-parity",
            "--severity-all",
            "--format",
            "json",
            "--output",
            str(output),
            str(source),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=100,
    )
    if result.returncode != 0:
        raise RuntimeError("Native KiCad DRC command did not finish successfully")
    report = json.loads(output.read_text())
    if (
        not str(report.get("kicad_version", "")).startswith("10.")
        or report.get("coordinate_units") != "mm"
        or not isinstance(report.get("violations"), list)
        or not isinstance(report.get("unconnected_items"), list)
        or not isinstance(report.get("schematic_parity"), list)
        or not isinstance(report.get("ignored_checks"), list)
    ):
        raise RuntimeError("Unexpected native KiCad 10 DRC evidence")
    return report


def _pad_lookup(board: Any) -> dict[str, Any]:
    pads: dict[str, Any] = {}
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            ident = pad.m_Uuid.AsString()
            if ident in pads:
                raise ValueError("Duplicate native pad UUIDs")
            pads[ident] = pad
    return pads


def _link_description(
    report: dict,
    index: int | None,
    pads: dict[str, Any],
    requested_uuids: tuple[str, str] | None,
) -> dict:
    items = report["unconnected_items"]
    if requested_uuids is not None:
        if requested_uuids[0] == requested_uuids[1]:
            raise ValueError("Two different native physical pad UUIDs required")
        matches = [
            i
            for i, item in enumerate(items)
            if isinstance(item.get("items"), list)
            and len(item["items"]) == 2
            and {x.get("uuid") for x in item["items"]} == set(requested_uuids)
        ]
        if len(matches) != 1:
            raise ValueError("Exact requested pad UUID pair is not a unique native unconnected link")
        if index is not None and matches[0] != index:
            raise ValueError("Requested UUIDs differ from the selected KiCad DRC item")
        index = matches[0]
    if index is None or index < 0 or index >= len(items):
        raise ValueError("Specify a valid KiCad DRC link index or exact pad UUID pair")
    finding = items[index]
    objects = finding.get("items")
    if finding.get("type") != "unconnected_items" or not isinstance(objects, list) or len(objects) != 2:
        raise ValueError("Selected finding is not a native KiCad two-pad unconnected link")
    # Native DRC is permitted to enumerate the same pair in either order.
    # Explicit user-supplied waypoints are always start→end, so preserve the
    # caller's exact pad UUID orientation rather than DRC's arbitrary order.
    uuids = list(requested_uuids) if requested_uuids is not None else [x.get("uuid") for x in objects]
    if any(uid not in pads for uid in uuids) or uuids[0] == uuids[1]:
        raise ValueError("Native DRC link endpoints are not two distinct PCB pads")
    a, b = (pads[uid] for uid in uuids)
    if a.GetNetCode() <= 0 or a.GetNetCode() != b.GetNetCode() or a.GetNetname() != b.GetNetname():
        raise ValueError("Native PCB pad nets disagree")
    if not a.IsOnLayer(pcb.F_Cu) or not b.IsOnLayer(pcb.F_Cu):
        raise ValueError("Only pads exposed on F.Cu qualify")
    coords = [(pcb.ToMM(p.GetPosition().x), pcb.ToMM(p.GetPosition().y)) for p in (a, b)]
    length = math.dist(*coords)
    if not 0.2 <= length <= 20.0:
        raise ValueError("Only 0.2–20 mm straight, center-to-center F.Cu routes allowed")
    return {"index": index, "net": a.GetNetname(), "pad_uuids": uuids, "points_mm": coords, "length_mm": length}


def _bounded_route_points(board: Any, link: dict, waypoints: list) -> None:
    """Validate an explicit physical F.Cu polyline, never synthesize geometry."""
    if not isinstance(waypoints, list) or len(waypoints) > 4:
        raise ValueError("At most four explicitly requested intermediate points")
    bound = board.GetBoardEdgesBoundingBox()
    points = [link["points_mm"][0]]
    for raw in waypoints:
        if (
            not isinstance(raw, list)
            or len(raw) != 2
            or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 2000
                for v in raw
            )
        ):
            raise ValueError("Every route waypoint must have two finite millimetre coordinates")
        point = (float(raw[0]), float(raw[1]))
        native = pcb.VECTOR2I(pcb.FromMM(point[0]), pcb.FromMM(point[1]))
        if not bound.Contains(native):
            raise ValueError("Intermediate route point outside native board outline")
        points.append([pcb.ToMM(native.x), pcb.ToMM(native.y)])
    points.append(link["points_mm"][-1])
    if len(set(tuple(p) for p in points)) != len(points):
        raise ValueError("Repeated route points are prohibited")
    distances = [math.dist(a, b) for a, b in zip(points, points[1:], strict=False)]
    if not distances or any(not 0.15 <= value <= 25 for value in distances) or sum(distances) > 60:
        raise ValueError("Route segment must be 0.15–25 mm, total 60 mm or less")
    link["points_mm"] = points
    link["length_mm"] = sum(distances)
    link["segment_count"] = len(distances)


def _check_board_metadata(before: dict, after: dict, route: dict) -> None:
    if before["footprints"] != after["footprints"] or before["zones"] != after["zones"]:
        raise RuntimeError("Native source footprint, pad or zone metadata changed")
    orig = before["tracks"]
    current = after["tracks"]
    if any(current.get(uid) != data for uid, data in orig.items()):
        raise RuntimeError("Existing board traces changed")
    additions = set(current) - set(orig)
    if len(additions) != route["segment_count"] or len(current) != len(orig) + route["segment_count"]:
        raise RuntimeError("Native PCB segment inventory changed beyond explicit route")
    expected = [
        ((pcb.FromMM(a[0]), pcb.FromMM(a[1])), (pcb.FromMM(b[0]), pcb.FromMM(b[1])))
        for a, b in zip(route["points_mm"], route["points_mm"][1:], strict=False)
    ]
    observed = []
    for uid in additions:
        track = current[uid]
        if track[1] != route["net"] or track[4] != pcb.FromMM(0.2) or track[5] != pcb.F_Cu:
            raise RuntimeError("New native trace net, copper layer or width unexpected")
        observed.append((track[2], track[3]))
    if Counter(observed) != Counter(expected):
        raise RuntimeError("Native KiCad saved different route segments")


def prove(
    source: Path,
    output: Path,
    link_index: int | None = None,
    requested_uuids: tuple[str, str] | None = None,
    waypoints: list | None = None,
) -> dict:
    if source.is_symlink():
        raise ValueError("Symlinked KiCad source board not accepted")
    source = source.resolve(strict=True)
    output = output.absolute()
    if source.stat().st_size > 10_000_000:
        raise ValueError("KiCad PCB too large for experimental single-link review")
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source.parent):
        raise ValueError("Review output must be a new directory outside the input project")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Invalid output directory")
    paths = _portable_sources(source)
    originals = {str(path.relative_to(source.parent)): digest(path) for path in paths}
    cli = shutil.which("kicad-cli")
    if not cli:
        raise RuntimeError("KiCad native DRC CLI required")
    with tempfile.TemporaryDirectory(prefix=".zaptrace-native-link-", dir=output.parent) as tmp:
        root = Path(tmp)
        first, second = root / "before", root / "after"
        _clone_assets(paths, source.parent, first)
        _clone_assets(paths, source.parent, second)
        first_board, second_board = first / source.name, second / source.name
        original_drc = _native_report(cli, first_board, root / "source-raw-drc.json")
        if original_drc["schematic_parity"]:
            raise ValueError("Native KiCad schematic/PCB parity must be clean")
        # Native pcbnew.SaveBoard normalizes net *indexes* and anonymous NPTH
        # layer masks even without edits. Normalize a separate, track-free
        # baseline; require KiCad to prove its actual DRC result is unchanged.
        # Never mutate the original source or accept a normalization finding.
        untouched = pcb.LoadBoard(str(first_board))
        if untouched is None or untouched.GetAreaCount() != 0:
            raise ValueError("Only zone-free, readable KiCad boards allowed")
        pcb.SaveBoard(str(first_board), untouched)
        normalized_board = pcb.LoadBoard(str(first_board))
        if normalized_board is None:
            raise RuntimeError("KiCad normalization of comparison copy failed")
        before = state(normalized_board)
        initial = _native_report(cli, first_board, root / "baseline.json")
        if (
            initial["ignored_checks"] != original_drc["ignored_checks"]
            or initial.get("included_severities") != original_drc.get("included_severities")
            or initial["kicad_version"] != original_drc["kicad_version"]
            or Counter(map(signature, initial["violations"])) != Counter(map(signature, original_drc["violations"]))
            or len(initial["unconnected_items"]) != len(original_drc["unconnected_items"])
            or initial["schematic_parity"] != original_drc["schematic_parity"]
        ):
            raise RuntimeError("Native KiCad normalization changed the original DRC context")
        board = pcb.LoadBoard(str(second_board))
        if board is None or board.GetAreaCount() != 0:
            raise ValueError("Only zone-free, readable native KiCad boards allowed")
        pads = _pad_lookup(board)
        link = _link_description(initial, link_index, pads, requested_uuids)
        if waypoints and requested_uuids is None:
            raise ValueError("Intermediate waypoints require explicit ordered pad UUID endpoints")
        _bounded_route_points(board, link, waypoints if waypoints is not None else [])
        net = board.FindNet(link["net"])
        if net is None:
            raise ValueError("Native board named net missing")
        native_points = [pcb.VECTOR2I(pcb.FromMM(x), pcb.FromMM(y)) for x, y in link["points_mm"]]
        for start, end in zip(native_points, native_points[1:], strict=False):
            track = pcb.PCB_TRACK(board)
            track.SetStart(start)
            track.SetEnd(end)
            track.SetWidth(pcb.FromMM(0.2))
            track.SetLayer(pcb.F_Cu)
            track.SetNet(net)
            board.Add(track)
        pcb.SaveBoard(str(second_board), board)
        reread = pcb.LoadBoard(str(second_board))
        if reread is None:
            raise RuntimeError("Native KiCad failed to reopen written copy")
        _check_board_metadata(before, state(reread), link)
        actual = _native_report(cli, second_board, root / "candidate.json")
        for key in ("kicad_version", "included_severities", "ignored_checks"):
            if initial.get(key) != actual.get(key):
                raise RuntimeError("Native KiCad rules or engine changed during routing")
        if actual["schematic_parity"]:
            raise RuntimeError("New schematic/PCB parity issue; route rejected")
        additions = Counter(map(signature, actual["violations"])) - Counter(map(signature, initial["violations"]))
        if additions:
            raise RuntimeError(f"New physical KiCad DRC violation(s): {sum(additions.values())}; route rejected")
        before_open = len(initial["unconnected_items"])
        after_open = len(actual["unconnected_items"])
        if after_open >= before_open:
            raise RuntimeError("No proven reduction in KiCad unconnected items")
        if any(
            digest(path) != sha for path, sha in ((source.parent / name, value) for name, value in originals.items())
        ):
            raise RuntimeError("Input KiCad source or supplier geometry changed during proof")
        evidence = {
            "type": "NATIVE_STRAIGHT_SINGLE_LINK_REVIEW_COPY",
            "status": "provisional_native_drc_10_verified_copy_not_fab",
            "source_sha256": originals[source.name],
            "working_sha256": digest(second_board),
            "source_asset_sha256": originals,
            "link": link,
            "native_drc": {
                "before_violations": len(initial["violations"]),
                "after_violations": len(actual["violations"]),
                "before_unconnected": before_open,
                "after_unconnected": after_open,
                "new_findings": 0,
                "schematic_parity": 0,
                "kiCadVersion": actual["kicad_version"],
            },
            "automatic_complete_routing": False,
            "electricallyApproved": False,
            "fabApproved": False,
        }
        output.mkdir(mode=0o700)
        try:
            _clone_assets(paths, source.parent, output / "project")
            shutil.copyfile(second_board, output / "project" / source.name)
            shutil.copyfile(root / "baseline.json", output / "baseline-drc.json")
            shutil.copyfile(root / "candidate.json", output / "candidate-drc.json")
            (output / "EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n")
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise
        return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--link-index", type=int, default=None, help="Index in normalized native DRC list")
    parser.add_argument("--start-pad-uuid", default=None)
    parser.add_argument("--end-pad-uuid", default=None)
    parser.add_argument(
        "--waypoints-json",
        default="[]",
        help="JSON list of up to four explicit [x_mm,y_mm] intermediate F.Cu points",
    )
    args = parser.parse_args()
    if (args.start_pad_uuid is None) != (args.end_pad_uuid is None):
        parser.error("Both start and end pad UUIDs must be supplied together")
    pair = (args.start_pad_uuid, args.end_pad_uuid) if args.start_pad_uuid is not None else None
    try:
        points = json.loads(args.waypoints_json)
        print(json.dumps(prove(args.board, args.output, args.link_index, pair, points), indent=2))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("SAFE NATIVE COPPER REVIEW BLOCKED:", exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
