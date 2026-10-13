"""Source-bound complete placement seed, not copper routing or fabrication."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from scripts.ai_native_pilot_kicad_lib import prepare_pilot_kicad_libraries
from scripts.ai_native_pilot_placement_geometry import (
    place_gct_receptacle_at_provisional_board_edge,
    require_pinned_physical_packages,
)
from zaptrace.algo.placer import place_components
from zaptrace.core.models import Design
from zaptrace.export.kicad import export_kicad_pcb, export_kicad_schematic
from zaptrace.kicad.verified_vendor import resolve_verified_footprint
from zaptrace.synthesis.footprint_resolver import resolve_footprints


def sha(file: Path) -> str:
    return hashlib.sha256(file.read_bytes()).hexdigest()


def create_baseline(candidate: Path, dest: Path) -> dict:
    candidate = candidate.absolute()
    dest = dest.absolute()
    if candidate.is_symlink() or not candidate.is_dir() or dest.exists() or dest.is_symlink():
        raise ValueError("Source must be real and output directory new")
    if not dest.parent.is_dir() or dest.parent.is_symlink():
        raise ValueError("Output parent must exist and not be a symlink")
    manifest = json.loads((candidate / "manifest.json").read_text())
    if manifest.get("fabrication_approved") is not False:
        raise ValueError("Untrusted source fabrication authority")
    hashes = manifest["files_sha256"]
    if set(hashes) != {"design.json", "candidate-report.json"}:
        raise ValueError("Unexpected candidate source inventory")
    for name, digest in hashes.items():
        source = candidate / name
        if source.is_symlink() or sha(source) != digest:
            raise ValueError("Tampered candidate source artifact")
    source_report = json.loads((candidate / "candidate-report.json").read_text())
    if (
        source_report.get("candidate_id") != manifest["candidate_id"]
        or source_report.get("status") != "review_required"
    ):
        raise ValueError("Expected exact review-required candidate")
    design = Design.model_validate_json((candidate / "design.json").read_bytes())
    references = {"C1", "C2", "C3", "J1", "R1", "R2", "R3", "R4", "R5", "U1", "U2", "U3"}
    if set(design.components) != references or len(design.nets) != 8 or design.meta.name != "SynthesizedBoard":
        raise ValueError("Unexpected source board family")
    if design.components["J1"].footprint_def != resolve_verified_footprint("usb4105-16p"):
        raise ValueError("USB-C geometry does not match independent pinned GCT original")
    source_nets = {key: value.model_dump(mode="json") for key, value in design.nets.items()}
    verified_packages = require_pinned_physical_packages(design)
    resolved = resolve_footprints(design)
    if not resolved.fully_resolved or len(resolved.resolved) != 12:
        raise ValueError("All 12 physical footprint inventories are required")
    proposed = place_components(design)
    if set(proposed) != set(design.components):
        raise ValueError("Placement omitted a component")
    design.placement = proposed
    connector_edge = place_gct_receptacle_at_provisional_board_edge(design)
    with tempfile.TemporaryDirectory(prefix=".zaptrace-pcb-place-", dir=dest.parent) as tmp:
        stage = Path(tmp)
        prepare_pilot_kicad_libraries(design, stage)
        export_kicad_schematic(design, stage)
        export_kicad_pcb(design, stage)
        if source_nets != {key: value.model_dump(mode="json") for key, value in design.nets.items()}:
            raise ValueError("Placement altered original netlist")
        (stage / "placed-design.json").write_text(
            json.dumps(design.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"
        )
        result = subprocess.run(
            ["/usr/bin/python3", "-B", "-m", "scripts.ai_native_pilot_pcb_native", str(stage)],
            capture_output=True,
            text=True,
            timeout=230,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Native KiCad placement verification failed: " + result.stderr[-1300:])
        native = json.loads((stage / "native-placement-audit.json").read_text())
        report = {
            "source_candidate_id": manifest["candidate_id"],
            "source_sha256": hashes,
            "source_netlist_unmodified": True,
            "source_candidate_pcb_not_previously_present": True,
            "placement_algorithm": "zaptrace.algo.placer.place_components",
            "physical_footprints_resolved": resolved.to_dict(),
            "physically_source_checked_packages": verified_packages,
            "provisional_usb_c_board_edge": connector_edge,
            "native": native,
            "artifact_sha256": {
                f.relative_to(stage).as_posix(): sha(f)
                for f in sorted(stage.rglob("*"))
                if f.is_file() and f.name not in {"placement-evidence.json"}
            },
            "routing_status": "not_routed",
            "pcb_drc_status": "blocked",
            "manufacturing_approved": False,
            "fabrication_approved": False,
        }
        (stage / "placement-evidence.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        if dest.exists() or dest.is_symlink():
            raise ValueError("Refusing output overwrite")
        stage.rename(dest)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = create_baseline(args.candidate_dir, args.output_dir)
    print(
        json.dumps(
            {
                "candidate_id": result["source_candidate_id"],
                "native": result["native"]["summary"],
                "fab_approved": False,
            }
        )
    )
