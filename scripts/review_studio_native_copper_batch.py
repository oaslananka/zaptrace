#!/usr/bin/python3
# pyright: reportMissingImports=false
"""Transactional 2–3 distinct-net KiCad 10 copper routes, local copies only.

A sequence is accepted only when EVERY link independently survives the
existing native KiCad DRC, custom .dru loader, default DRC and saved-PCB
identity proofs. On any failure, no publishable output directory exists.
Zones are explicitly unsupported: never change filled copper silently.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import pcbnew as pcb
from review_studio_native_copper_bundle import checked_batch_routes
from review_studio_native_copper_link import _portable_sources, digest, prove
from review_studio_pcb_eco import signature


def execute(source: Path, output: Path, requested: Any) -> dict:
    plans = checked_batch_routes(requested)
    if source.is_symlink() or source.suffix != ".kicad_pcb" or not source.is_file():
        raise ValueError("Regular native KiCad PCB required")
    source = source.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(source.parent):
        raise ValueError("New isolated destination outside input project required")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Invalid output parent directory")
    assets = _portable_sources(source)
    asset_hashes = {str(p.relative_to(source.parent)): digest(p) for p in assets}
    native = pcb.LoadBoard(str(source))
    if native is None or native.GetAreaCount() != 0:
        raise ValueError("Zone-bearing boards are blocked: KiCad zone refill not independently qualified")
    with tempfile.TemporaryDirectory(prefix=".zaptrace-native-batch-", dir=output.parent) as scratch:
        root = Path(scratch)
        chain: list[dict] = []
        previous = source
        seen_nets: set[str] = set()
        for index, route in enumerate(plans, 1):
            stage = root / f"stage-{index}"
            proof = prove(
                previous,
                stage,
                requested_uuids=(route["start_pad_uuid"], route["end_pad_uuid"]),
                waypoints=route["waypoints"],
                via_indices=route["via_indices"],
            )
            net = proof["link"]["net"]
            if net in seen_nets:
                raise ValueError("Every batch link must connect a distinct KiCad native net")
            seen_nets.add(net)
            expected_sha = asset_hashes[source.name] if index == 1 else chain[-1]["working_sha256"]
            if proof["source_sha256"] != expected_sha:
                raise RuntimeError("Native KiCad step's input does not match preceding verified working board")
            chain.append(proof)
            previous = stage / "project" / source.name
            if not previous.is_file() or digest(previous) != proof["working_sha256"]:
                raise RuntimeError("Native KiCad staged source chain is not SHA-consistent")
        assert len(chain) == len(plans)
        baseline = json.loads((root / "stage-1/baseline-drc.json").read_text())
        final = json.loads((root / f"stage-{len(chain)}/candidate-drc.json").read_text())
        start_count = len(baseline["unconnected_items"])
        final_count = len(final["unconnected_items"])
        if final_count != start_count - len(plans):
            raise RuntimeError("Cumulative native connectivity has not reduced by exactly one per step")
        if final["schematic_parity"] or baseline["schematic_parity"]:
            raise RuntimeError("Native cumulative schematic parity is not clean")
        for key in ("kicad_version", "included_severities", "ignored_checks"):
            if baseline.get(key) != final.get(key):
                raise RuntimeError("Cumulative KiCad DRC rule policy or engine changed")
        novel = Counter(map(signature, final["violations"])) - Counter(map(signature, baseline["violations"]))
        if novel:
            raise RuntimeError("Cumulative route introduced new KiCad DRC findings")
        if {str(p.relative_to(source.parent)): digest(p) for p in assets} != asset_hashes:
            raise RuntimeError("Original source assets changed during multi-step routing")
        result = {
            "type": "NATIVE_MULTINET_TRANSACTIONAL_COPPER_REVIEW_COPY",
            "status": "source_only_0_1_12_experimental_not_fab",
            "source_sha256": asset_hashes[source.name],
            "working_sha256": chain[-1]["working_sha256"],
            "source_asset_sha256": asset_hashes,
            "step_count": len(plans),
            "distinct_nets": [proof["link"]["net"] for proof in chain],
            "steps": [
                {
                    "index": i + 1,
                    "source_sha256": proof["source_sha256"],
                    "working_sha256": proof["working_sha256"],
                    "link": proof["link"],
                    "rule_context": proof["rule_context"],
                    "native_drc": proof["native_drc"],
                }
                for i, proof in enumerate(chain)
            ],
            "cumulative_drc": {
                "before_unconnected": start_count,
                "after_unconnected": final_count,
                "before_violations": len(baseline["violations"]),
                "after_violations": len(final["violations"]),
                "new_findings": 0,
                "schematic_parity": 0,
                "kiCadVersion": final["kicad_version"],
            },
            "zone_refill_verified": False,
            "automatic_complete_routing": False,
            "electricallyApproved": False,
            "fabApproved": False,
        }
        output.mkdir(mode=0o700)
        try:
            shutil.copytree(root / f"stage-{len(chain)}" / "project", output / "project")
            shutil.copyfile(root / "stage-1/baseline-drc.json", output / "baseline-drc.json")
            shutil.copyfile(root / f"stage-{len(chain)}/candidate-drc.json", output / "candidate-drc.json")
            for i, proof in enumerate(chain, 1):
                (output / f"step-{i}-evidence.json").write_text(json.dumps(proof, indent=2) + "\n")
                if proof["rule_context"]["default_drc_crosscheck_passed"]:
                    for side in ("baseline", "candidate"):
                        name = f"{side}-default-drc.json"
                        shutil.copyfile(root / f"stage-{i}" / name, output / f"step-{i}-{name}")
            (output / "EVIDENCE.json").write_text(json.dumps(result, indent=2) + "\n")
            if digest(output / "project" / source.name) != result["working_sha256"]:
                raise RuntimeError("Published candidate PCB hash changed after native DRC")
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--routes-json", required=True, help="Exact JSON array of two or three explicit pad-pair route objects"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.board, args.output, json.loads(args.routes_json)), indent=2))
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print("SAFE MULTI-NET ROUTE TRANSACTION BLOCKED:", exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
