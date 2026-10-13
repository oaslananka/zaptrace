#!/usr/bin/python3
# pyright: reportMissingImports=false
"""Isolated native KiCad 10 proof: repeated USB-C S1 pad copper continuity.

Must run with KiCad's system /usr/bin/python3 (pcbnew). Produces a two-state
connector-only test fixture; NEVER treats it as a placed/routed source board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pcbnew as pcb

_VENDOR_SHA = "db924af7ac6b9ed7b16df1f598a56268c6a32ec33583557b6e5d8aa5056e3b2c"
_VENDOR_NAME = "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
_VENDOR_ROOT = Path(__file__).resolve().parents[1] / "data" / "footprints" / "vendor"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _candidate_reference(folder: Path) -> dict[str, Any]:
    if folder.is_symlink() or not folder.is_dir():
        raise ValueError("Candidate directory unavailable or symlinked")
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("fabrication_approved") is not False:
        raise ValueError("Expected explicitly unapproved source candidate")
    expected = manifest.get("files_sha256", {})
    if set(expected) != {"design.json", "candidate-report.json"}:
        raise ValueError("Incomplete candidate source contract")
    for name, sha in expected.items():
        f = folder / name
        if f.is_symlink() or _sha(f) != sha:
            raise ValueError("Candidate source SHA mismatch")
    report = json.loads((folder / "candidate-report.json").read_text())
    design = json.loads((folder / "design.json").read_text())
    if report.get("candidate_id") != manifest.get("candidate_id"):
        raise ValueError("Source candidate ID mismatch")
    components = design.get("components", {})
    connector = components.get("J1")
    if not isinstance(connector, dict) or connector.get("mpn") != "USB4105-15-A-120":
        raise ValueError("Exact J1 part contract not established")
    if list(folder.glob("*.kicad_pcb")):
        raise ValueError("A source PCB was supplied; cannot pretend this connector fixture reviews it")
    geometry = connector.get("footprint_def", {})
    source_pads = geometry.get("pads") if isinstance(geometry, dict) else None
    if not isinstance(source_pads, list) or len(source_pads) != 22:
        raise ValueError("Source USB4105 physical pad inventory is incomplete")
    source_signature = Counter(
        (p.get("id"), tuple(round(float(x), 5) for x in p["position"]), tuple(round(float(x), 5) for x in p["size"]))
        for p in source_pads
    )
    if sum(source_signature.values()) != 22:
        raise ValueError("Malformed source USB4105 pad geometry")
    contact_map = connector.get("package_pin_map", {})
    if contact_map.get("S1") != "SHIELD":
        raise ValueError("J1 S1 shield pin identity missing")
    shield_on_ground = [
        n
        for key, value in design.get("nets", {}).items()
        for n in value.get("nodes", [])
        if n.get("component_ref") == "J1" and n.get("pin_name") == "SHIELD" and key == "GND"
    ]
    if len(shield_on_ground) != 1:
        raise ValueError("J1 shield logical GND is unverified")
    return {"id": manifest["candidate_id"], "files_sha256": expected, "source_pad_signature": source_signature}


def _build_fixture(
    path: Path,
    *,
    connect_s1: bool,
    filename: str,
    expected_signature: Counter[tuple[Any, ...]],
) -> tuple[dict[str, Any], Path]:
    vendor = _VENDOR_ROOT / (_VENDOR_NAME + ".kicad_mod")
    if _sha(vendor) != _VENDOR_SHA:
        raise ValueError("Pinned original GCT source footprint bytes changed")
    board = pcb.BOARD()
    footprint = pcb.FootprintLoad(str(_VENDOR_ROOT), _VENDOR_NAME)
    if footprint is None:
        raise ValueError("Unable to read native GCT USB4105 footprint")
    actual_signature = Counter(
        (
            pad.GetNumber(),
            (round(pcb.ToMM(pad.GetPosition().x), 5), round(pcb.ToMM(pad.GetPosition().y), 5)),
            (round(pcb.ToMM(pad.GetSize().x), 5), round(pcb.ToMM(pad.GetSize().y), 5)),
        )
        for pad in footprint.Pads()
    )
    if actual_signature != expected_signature:
        raise ValueError("Source PCB footprint geometry differs from pinned native GCT footprint")
    footprint.SetReference("J1")
    footprint.SetPosition(pcb.VECTOR2I(pcb.FromMM(50), pcb.FromMM(50)))
    board.Add(footprint)
    ground = pcb.NETINFO_ITEM(board, "GND")
    board.Add(ground)
    pads = [pad for pad in footprint.Pads() if pad.GetNumber() == "S1"]
    if len(pads) != 4:
        raise ValueError("Pinned GCT footprint does not contain exactly four S1 shield lands")
    positions = {(pad.GetPosition().x, pad.GetPosition().y) for pad in pads}
    if len(positions) != 4:
        raise ValueError("Shield pads have non-unique copper geometry")
    for pad in pads:
        pad.SetNet(ground)
    if connect_s1:
        # Intentionally crude B.Cu experiment ONLY: not a routed board.
        ordered = sorted(pads, key=lambda pad: (pad.GetPosition().x, pad.GetPosition().y))
        for first, second in zip(ordered, ordered[1:], strict=False):
            track = pcb.PCB_TRACK(board)
            track.SetStart(first.GetPosition())
            track.SetEnd(second.GetPosition())
            track.SetLayer(pcb.B_Cu)
            track.SetWidth(pcb.FromMM(0.25))
            track.SetNet(ground)
            board.Add(track)
    board.BuildConnectivity()
    count = board.GetConnectivity().GetUnconnectedCount(False)
    path.mkdir(exist_ok=False)
    target = path / filename
    if not pcb.SaveBoard(str(target), board):
        raise ValueError("Native KiCad PCB save failed")
    loaded = pcb.LoadBoard(str(target))
    if loaded is None:
        raise ValueError("Saved PCB cannot be reopened by native KiCad")
    saved_footprints = list(loaded.GetFootprints())
    if len(saved_footprints) != 1 or saved_footprints[0].GetReference() != "J1":
        raise ValueError("Saved test fixture does not preserve connector identity")
    saved_pads = [pad for pad in saved_footprints[0].Pads() if pad.GetNumber() == "S1"]
    if len(saved_pads) != 4 or any(pad.GetNetname() != "GND" for pad in saved_pads):
        raise ValueError("Saved test fixture silently changed physical S1 nets")
    uuids = [pad.m_Uuid.AsString() for pad in saved_pads]
    if len(set(uuids)) != 4:
        raise ValueError("Physical S1 pads not UUID-distinct")
    loaded.BuildConnectivity()
    after = loaded.GetConnectivity().GetUnconnectedCount(False)
    if after != count:
        raise ValueError("Copper connectivity does not survive native save/reopen")
    return {
        "pad_count": len(list(saved_footprints[0].Pads())),
        "s1_positions_mm": sorted(
            [[round(pcb.ToMM(pad.GetPosition().x), 5), round(pcb.ToMM(pad.GetPosition().y), 5)] for pad in saved_pads]
        ),
        "physical_s1_uuids": sorted(uuids),
        "s1_net": "GND",
        "native_unconnected_count": after,
        "tracks": len(list(loaded.GetTracks())),
        "zones": len(list(loaded.Zones())),
        "pcb_sha256": _sha(target),
    }, target


def _native_drc(board: Path, output: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "kicad-cli",
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--exit-code-violations",
            "-o",
            str(output),
            str(board),
        ],
        capture_output=True,
        text=True,
        timeout=100,
        check=False,
    )
    if not output.is_file():
        raise ValueError("KiCad PCB DRC failed without a parseable report")
    doc = json.loads(output.read_text())
    if doc.get("$schema") != "https://schemas.kicad.org/drc.v1.json":
        raise ValueError("Unknown KiCad PCB DRC JSON format")
    unconnected = doc.get("unconnected_items")
    violations = doc.get("violations")
    ignored = doc.get("ignored_checks")
    if any(not isinstance(obj, list) for obj in (unconnected, violations, ignored)):
        raise ValueError("Missing mandatory KiCad DRC evidence")
    if set(doc.get("included_severities", [])) < {"error", "warning", "exclusion"}:
        raise ValueError("KiCad PCB DRC severities incomplete")
    return {
        "cli_exit": completed.returncode,
        "kicad_version": doc.get("kicad_version"),
        "unconnected_items": len(unconnected),
        "unconnected_types": dict(Counter(i.get("type", "?") for i in unconnected)),
        "other_rule_violations": len(violations),
        "other_types": dict(Counter(i.get("type", "?") for i in violations)),
        "ignored_check_count": len(ignored),
        "json_sha256": _sha(output),
    }


def demonstrate_native_shield_connectivity(candidate_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Never map a connector-only fixture to a fabricated/routed board claim."""
    candidate = _candidate_reference(candidate_dir.absolute())
    output = output_dir.absolute()
    if output.exists() or output.is_symlink() or not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Fixture output requires a new local directory")
    with tempfile.TemporaryDirectory(prefix=".zaptrace-shield-", dir=output.parent) as tmp:
        stage = Path(tmp)
        before, before_board = _build_fixture(
            stage / "unrouted",
            connect_s1=False,
            filename="J1-unrouted.kicad_pcb",
            expected_signature=candidate["source_pad_signature"],
        )
        after, after_board = _build_fixture(
            stage / "test-track",
            connect_s1=True,
            filename="J1-tracks.kicad_pcb",
            expected_signature=candidate["source_pad_signature"],
        )
        before["native_drc"] = _native_drc(before_board, stage / "unrouted" / "native-drc.json")
        after["native_drc"] = _native_drc(after_board, stage / "test-track" / "native-drc.json")
        if before["physical_s1_uuids"] == after["physical_s1_uuids"]:
            raise ValueError("Two separate native PCB states must have independently generated pad UUIDs")
        if before["native_unconnected_count"] != before["native_drc"]["unconnected_items"]:
            raise ValueError("Original PCB KiCad API and CLI report different unconnected counts")
        if after["native_unconnected_count"] != after["native_drc"]["unconnected_items"]:
            raise ValueError("Track PCB KiCad API and CLI report different unconnected counts")
        if (
            before["native_unconnected_count"] != 3
            or before["tracks"] != 0
            or after["native_unconnected_count"] != 0
            or after["tracks"] != 3
            or before["s1_positions_mm"] != after["s1_positions_mm"]
        ):
            raise ValueError("Native PCB shield connectivity evidence is inconsistent")
        evidence = {
            "source_candidate_id": candidate["id"],
            "source_sha256": candidate["files_sha256"],
            "original_vendor_footprint_sha256": _VENDOR_SHA,
            "purpose": "connector_only_unapproved_native_pcb_test_fixture",
            "source_candidate_pcb_layout_present": False,
            "candidate_board_s1_copper_verified": False,
            "demonstrated": {
                "same_net_without_tracks": before,
                "isolated_test_tracks_not_fabrication_layout": after,
            },
            "main_pilot_physical_drc": "not_checked",
            "physical_fixture_drc": "blocked",
            "production_approved": False,
            "fabrication_approved": False,
        }
        (stage / "evidence.json").write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared during fixture validation")
        stage.rename(output)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    record = demonstrate_native_shield_connectivity(args.candidate_dir, args.output_dir)
    print(
        json.dumps(
            {
                "candidate_id": record["source_candidate_id"],
                "fixture_s1_unconnected_before": record["demonstrated"]["same_net_without_tracks"][
                    "native_unconnected_count"
                ],
                "fixture_s1_unconnected_after": record["demonstrated"]["isolated_test_tracks_not_fabrication_layout"][
                    "native_unconnected_count"
                ],
                "real_candidate_pcb_verified": False,
                "fabrication_approved": False,
            }
        )
    )


if __name__ == "__main__":
    main()
