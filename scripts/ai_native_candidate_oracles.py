#!/usr/bin/env python3
"""Run honest, read-only local KiCad ERC and SPICE coverage on a frozen candidate.

No result here is a full engineering/production approval. The native ERC JSON
itself is authoritative, not only the KiCad CLI return code or an error count.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from scripts.ai_native_pilot_kicad_lib import prepare_pilot_kicad_libraries
from scripts.ai_native_pilot_pin_parity import crosscheck_native_pin_pad_net
from zaptrace.analysis.spice_orchestrator import orchestrate_spice
from zaptrace.core.models import Design
from zaptrace.export.kicad import export_kicad_schematic
from zaptrace.synthesis.footprint_resolver import resolve_footprints


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run_local_oracles(candidate_dir: Path, output_dir: Path) -> dict[str, Any]:
    candidate_dir = candidate_dir.absolute()
    output = output_dir.absolute()
    if candidate_dir.is_symlink() or not candidate_dir.is_dir() or output.exists() or output.is_symlink():
        raise ValueError("Candidate must be a normal directory and oracle output must not exist")
    if not output.parent.is_dir() or output.parent.is_symlink():
        raise ValueError("Oracle output parent must be an existing normal directory")
    manifest = json.loads((candidate_dir / "manifest.json").read_text())
    if manifest.get("fabrication_approved") is not False:
        raise ValueError("Unsafe or externally modified candidate")
    for name, expected in manifest.get("files_sha256", {}).items():
        if name not in {"design.json", "candidate-report.json"} or (candidate_dir / name).is_symlink():
            raise ValueError("Unexpected candidate artifact")
        if _sha(candidate_dir / name) != expected:
            raise ValueError("Candidate source SHA mismatch")
    if set(manifest.get("files_sha256", {})) != {"design.json", "candidate-report.json"}:
        raise ValueError("Incomplete candidate input")
    report = json.loads((candidate_dir / "candidate-report.json").read_text())
    if (
        report.get("candidate_id") != manifest.get("candidate_id")
        or report.get("status") == "bounded_candidate"
        and not report.get("pending_assumptions")
    ):
        raise ValueError("Untrusted candidate status or identity")
    design = Design.model_validate_json((candidate_dir / "design.json").read_bytes())
    footprint_resolution = resolve_footprints(design)
    if not footprint_resolution.fully_resolved:
        raise ValueError(
            "No physical pad geometry for: " + ", ".join(x["ref"] for x in footprint_resolution.unresolved)
        )
    cli = shutil.which("kicad-cli")
    with tempfile.TemporaryDirectory(prefix=".zaptrace-native-oracle-", dir=output.parent) as tmp:
        stage = Path(tmp)
        native_dir = stage / "kicad"
        native_dir.mkdir()
        library_inventory = prepare_pilot_kicad_libraries(design, native_dir)
        files = export_kicad_schematic(design, native_dir)
        original = files["schematic"]
        native: dict[str, Any] = {"status": "not_checked", "why": "kicad_cli_unavailable"}
        pin_parity: dict[str, Any] = {"status": "not_checked", "why": "kicad_cli_unavailable"}
        if cli is not None:
            netlist = native_dir / "native-netlist.xml"
            exported = subprocess.run(
                [cli, "sch", "export", "netlist", "--format", "kicadxml", "-o", str(netlist), str(original)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if exported.returncode != 0:
                raise ValueError("Native KiCad schematic netlist export failed")
            pin_parity = crosscheck_native_pin_pad_net(design, netlist)
            pin_parity["native_netlist_sha256"] = _sha(netlist)
            result = subprocess.run(
                [
                    cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--severity-all",
                    "--exit-code-violations",
                    "-o",
                    str(native_dir / "native-erc.json"),
                    str(original),
                ],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            native_json = native_dir / "native-erc.json"
            if not native_json.is_file():
                raise ValueError("KiCad did not produce JSON native ERC report")
            erc = json.loads(native_json.read_text())
            if erc.get("$schema") != "https://schemas.kicad.org/erc.v1.json":
                raise ValueError("Unexpected native KiCad ERC schema")
            findings = [entry for sheet in erc["sheets"] for entry in sheet["violations"]]
            errors = sum(x.get("severity") == "error" for x in findings)
            warnings = sum(x.get("severity") == "warning" for x in findings)
            ignored = erc.get("ignored_checks", [])
            # No success if warning/exclusion rules, unrun checks or nonzero exit.
            status = "passed" if result.returncode == 0 and not findings and not ignored else "blocked"
            native = {
                "status": status,
                "kicad_version": erc.get("kicad_version"),
                "cli_exit": result.returncode,
                "errors": errors,
                "warnings": warnings,
                "other_findings": len(findings) - errors - warnings,
                "ignored_checks": ignored,
                "findings": findings,
                "schematic_sha256": _sha(original),
                "erc_json_sha256": _sha(native_json),
            }
        simulation = orchestrate_spice(design, expected_voltages={"VDD_3V3": 3.3})
        sim_raw = simulation.to_dict()
        simulation_status = "not_checked" if simulation.status == "skipped" else "blocked"
        if (
            simulation.status == "ok"
            and simulation.skipped_components == 0
            and simulation.all_checks_passed
            and simulation.checks
            and all(check.passed is True for check in simulation.checks)
        ):
            simulation_status = "dc_only_passed_not_transient_qualified"
        record = {
            "kind": "local_unapproved_native_kicad_and_simulation_evidence",
            "candidate_id": manifest["candidate_id"],
            "source_sha256": manifest["files_sha256"],
            "local_inspection_library": {
                "component_count": len(library_inventory),
                "geometry_resolution": footprint_resolution.to_dict(),
                "manifest_sha256": _sha(native_dir / "portable-library-manifest.json"),
                "status": "generated_pad_geometry_only_unqualified",
            },
            "native_erc": native,
            "native_pin_pad_net_parity": pin_parity,
            "simulation": {"status": simulation_status, "dc_evidence": sim_raw},
            "physical_routing_drc": "not_checked",
            "fabrication_approved": False,
        }
        (stage / "oracle-evidence.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        if output.exists() or output.is_symlink():
            raise ValueError("Oracle output appeared during run; no files overwritten")
        stage.rename(output)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = run_local_oracles(args.candidate_dir, args.output_dir)
    print(
        json.dumps(
            {
                "candidate_id": result["candidate_id"],
                "native_erc_status": result["native_erc"]["status"],
                "simulation_status": result["simulation"]["status"],
                "fabrication_approved": False,
            }
        )
    )


if __name__ == "__main__":
    main()
