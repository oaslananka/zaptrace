#!/usr/bin/python3
"""Read-only, source-verified current/proposed review for actual native KiCad PCB ECO."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import subprocess
from pathlib import Path

from review_studio_native_kicad import _read_kicad

TEMPLATE = Path(__file__).with_name("review_studio_change_diff_template.html")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_native_board_transition(
    before: dict, after: dict, proof: dict, sha_before: str, sha_after: str
) -> list[dict]:
    if (
        proof.get("type") != "PCB_UNROUTED_FOOTPRINT_PLACEMENT_ECO"
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
    if len(changes) != 1 or changes[0]["ref"] != proof.get("ref"):
        raise ValueError("Exactly one source-linked physical footprint movement required")
    if changes[0]["old_mm"] != proof.get("old_mm") or changes[0]["new_mm"] != proof.get("new_mm"):
        raise ValueError("Saved ECO evidence footprint positions differ from actual PCB")
    return changes


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


def create_review(source: Path, candidate: Path, evidence: Path, output: Path) -> dict:
    source, candidate, evidence = (p.resolve(strict=True) for p in (source, candidate, evidence))
    if source == candidate or output.resolve() in (source, candidate, evidence):
        raise ValueError("ECO reviewer must not edit or compare the same source file")
    if any(p.stat().st_size > 15_000_000 for p in (source, candidate, evidence)):
        raise ValueError("Unexpected input size")
    source_sha, candidate_sha = digest(source), digest(candidate)
    evidence_sha = digest(evidence)
    proof = json.loads(evidence.read_text())
    before, after = _read_kicad(source), _read_kicad(candidate)
    changes = check_native_board_transition(before, after, proof, source_sha, candidate_sha)
    output.parent.mkdir(parents=True, exist_ok=True)
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
    if (digest(source), digest(candidate), digest(evidence)) != (source_sha, candidate_sha, evidence_sha):
        raise ValueError("Input board or ECO evidence changed during native verification")
    if any(proof.get("native_drc", {}).get(key) != value for key, value in native_result.items()):
        raise ValueError("Fresh independent KiCad DRC differs from ECO evidence")
    before_vector = native_svg(source, output.with_suffix(".current.svg"))
    after_vector = native_svg(candidate, output.with_suffix(".proposed.svg"))
    document = {
        "schema_version": 1,
        "kind": "unsigned_local_design_change_decision_not_approval",
        "source_sha256": source_sha,
        "proposed_sha256": candidate_sha,
        "native_svg": {
            "current": before_vector,
            "proposed": after_vector,
            "scope": "Native F.Cu/F.SilkS/Edge.Cuts; no fabrication or 3D fit evidence",
        },
        "current": before["footprints"],
        "proposed": after["footprints"],
        "changed": changes,
        "board_origin_mm": before["origin"],
        "board_size_mm": before["size"],
        "drc": {
            **native_result,
            "ignored_checks": len(a["ignored_checks"]),
            "engine": a["kicad_version"],
            "included_severities": a["included_severities"],
        },
        "approval_supported": False,
        "fabrication_approved": False,
        "electrically_approved": False,
        "schematic_erc_verified": False,
    }
    document["state_hash"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    template = TEMPLATE.read_text()
    if template.count("__CHANGE_DATA__") != 1:
        raise ValueError("Unsafe HTML review template contract")
    html = template.replace("__CHANGE_DATA__", json.dumps(document, ensure_ascii=True).replace("<", "\\u003c"))
    output.write_text(html)
    output.with_suffix(".state.json").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "candidate", "evidence", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = create_review(args.source, args.candidate, args.evidence, args.output)
    print("REAL_KICAD_ECO_BEFORE_AFTER_STATE_BOUND_REVIEW=PASS", result["state_hash"])


if __name__ == "__main__":
    main()
