#!/usr/bin/env python3
"""Emit an auditable, non-signature release manifest for a checked local .deb.

Run only after the complete release gate. The manifest NEVER declares GA,
source design manufacturability or a cryptographic code signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest(package: Path, gate_log: Path, container_qa: Path | None = None) -> dict:
    package, gate_log = package.resolve(), gate_log.resolve()
    if not package.is_file() or not gate_log.is_file():
        raise ValueError("Release package and completed gate log must exist")
    evidence = gate_log.read_text(encoding="utf-8")
    if "RELEASE GATE: PASS" not in evidence or not all(f"[{i}/9]" in evidence for i in range(1, 10)):
        raise ValueError("Complete nine-stage local engineering release gate was not verified")
    if "0 errors, 0 warnings, 0 informations" not in evidence:
        raise ValueError("Release gate did not record clean static type checks")
    if "Original KiCad" in package.name or not re.fullmatch(r"zaptrace-review-studio_0\.1\.10_all\.deb", package.name):
        raise ValueError("Unexpected package name or version for release manifest")
    recorded_sha = package.with_suffix(".sha256")
    if (
        not recorded_sha.is_file()
        or recorded_sha.read_text(encoding="ascii").strip() != f"{sha256(package)}  {package.name}"
    ):
        raise ValueError("Release package and registered SHA256 checksum do not match")
    fields = {}
    for field in ("Package", "Version", "Architecture", "Depends"):
        fields[field] = subprocess.run(
            ["dpkg-deb", "-f", str(package), field], check=True, capture_output=True, text=True, timeout=12
        ).stdout.strip()
    if fields["Package"] != "zaptrace-review-studio" or fields["Version"] != "0.1.10":
        raise ValueError("Versioned metadata mismatch")
    container_verified = False
    if container_qa is not None:
        if not container_qa.is_file():
            raise ValueError("Container acceptance report unavailable")
        log = container_qa.read_text(encoding="utf-8")
        markers = (
            "PACKAGE_SHA256=" + sha256(package),
            "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0",
            "Real APT in-place upgrade to installed 0.1.10 passed",
            "Installed 0.1.10 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
            (
                "Installed 0.1.10 native browser ECO value copy-on-write"
                " with KiCad netlist/ERC and separate download: PASS"
            ),
            "Installed 0.1.10 native browser PCB footprint placement ECO, copper/DRC and separate download: PASS",
            "Installed 0.1.10 native PCB quarter-turn and KiCad DRC: PASS",
            "Installed 0.1.10 native schematic/PCB readonly comparison: PASS",
            "Exact package 0.1.10 Chrome quarter-turn and private parity audit: PASS",
            "Installed 0.1.10 guarded native copper route and SHA-bounded DRC proof: PASS",
            "Exact package 0.1.10 Chrome guarded copper ZIP, SVG, discard: PASS",
            "Legacy 0.1.1 private ZIP restore: approved by source SHA",
            "Native localhost startup/shutdown after upgrade passed",
            "Actual APT remove 0.1.10 passed",
        )
        if not all(marker in log for marker in markers):
            raise ValueError("Real clean Ubuntu container QA report is missing required evidence")
        container_verified = True
    with tempfile.TemporaryDirectory(prefix="zaptrace-release-audit-") as temp:
        extracted = Path(temp)
        subprocess.run(["dpkg-deb", "-x", str(package), str(extracted)], check=True, capture_output=True, timeout=20)
        root = extracted / "usr"
        installed = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Unexpected symbolic link in release package")
            if path.is_file():
                relative = str(path.relative_to(extracted))
                if any(
                    part in relative for part in (".kicad_pcb", ".kicad_sch", ".kicad_pro", "local-imports/", ".pyc")
                ):
                    raise ValueError("Private KiCad user source or Python cache found in package")
                installed.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size})
        legal = extracted / "usr/share/doc/zaptrace-review-studio/copyright"
        if "PolyForm Noncommercial License 1.0.0" not in legal.read_text(encoding="utf-8"):
            raise ValueError("PolyForm Noncommercial license is absent from package")
        if not any(
            entry["path"] == "usr/lib/zaptrace-review-studio/scripts/review_studio_library.py" for entry in installed
        ):
            raise ValueError("Review Studio private backup/deletion module missing")
        if not any(
            entry["path"] == "usr/lib/zaptrace-review-studio/scripts/review_studio_schematic_eco.py"
            for entry in installed
        ):
            raise ValueError("Native source-safe schematic ECO authoring module missing")
        for required in (
            "review_studio_pcb_eco.py",
            "review_studio_pcb_eco_template.html",
            "review_studio_schematic_pcb_parity.py",
            "review_studio_native_copper_link.py",
            "review_studio_native_copper_bundle.py",
        ):
            if not any(entry["path"] == "usr/lib/zaptrace-review-studio/scripts/" + required for entry in installed):
                raise ValueError("Native footprint-placement ECO authoring resource missing: " + required)
    return {
        "schema": "zaptrace.review-studio.local-distribution.v1",
        "product": "ZapTrace Review Studio",
        "version": fields["Version"],
        "status": "locally-qualified-release-candidate; unsigned; NOT public GA",
        "target": {
            "operating_system": "Ubuntu 24.04 LTS",
            "architecture_tested": "amd64",
            "native_kicad": "10.x",
            "python": "system Python 3.12",
        },
        "package": {
            "filename": package.name,
            "sha256": sha256(package),
            "bytes": package.stat().st_size,
            "declared_architecture": fields["Architecture"],
            "declared_dependencies": fields["Depends"],
        },
        "license": "PolyForm Noncommercial 1.0.0 (package includes complete license)",
        "bundled_files": installed,
        "validation": {
            "nine_stage_release_gate": True,
            "reproducible_package_identical_hash": True,
            "rootless_dpkg_install_run_remove": True,
            "apt_install_simulated_no_host_mutation": True,
            "native_kicad_drc_and_erc": True,
            "read_only_external_sources": True,
            "local_browser_export_and_typed_deletion": True,
            "code_signed": False,
            "clean_ubuntu_disposable_container_real_apt_install": container_verified,
            "clean_ubuntu_container_native_erc_drc": container_verified,
            "clean_ubuntu_container_native_3d_isometric_and_top": container_verified,
            "clean_ubuntu_container_native_3d_eight_camera_orbit_frames": container_verified,
            "clean_ubuntu_localhost_schematic_value_eco_native_validation": container_verified,
            "clean_ubuntu_localhost_pcb_placement_eco_native_drc": container_verified,
            "clean_ubuntu_native_footprint_quarter_turn": container_verified,
            "clean_ubuntu_native_schematic_pcb_read_only_parity_audit": container_verified,
            "clean_ubuntu_exact_package_browser_rotation_and_parity": container_verified,
            "clean_ubuntu_guarded_native_copper_route": container_verified,
            "clean_ubuntu_exact_package_browser_guarded_copper": container_verified,
            "full_schematic_pcb_uuid_pin_net_sync_verified": False,
            "full_schematic_and_pcb_authoring_verified": False,
            "native_3d_model_coverage_independently_verified": False,
            "clean_ubuntu_container_apt_remove_preserves_user_data": container_verified,
            "clean_ubuntu_container_inplace_011_to_0110_upgrade": container_verified,
            "clean_ubuntu_container_legacy_zip_restored_using_fresh_kicad": container_verified,
            "independent_clean_machine_real_apt_install": False,
            "unassisted_external_user_acceptance": False,
            "fabrication_approved": False,
        },
        "release_limitations": [
            "Real APT install, KiCad ERC/DRC and uninstall passed in disposable Ubuntu 24.04 Docker "
            "container; no separate physical host acceptance",
            "Unsigned .deb; SHA256 detects changes but does not prove publisher identity",
            "Authentic KiCad OpenGL 3D screenshots are source-bounded previews; "
            "3D model completeness and mechanical assembly fit are NOT verified",
            "Not tested on Windows or macOS; KiCad 11 is unsupported",
            "Actual PCB fabrication requires separate DRC, ERC and DFM signoff",
            "Commercial use requires separate license review",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package", type=Path, default=Path("build/distribution/zaptrace-review-studio_0.1.10_all.deb")
    )
    parser.add_argument("--gate-log", type=Path, required=True)
    parser.add_argument("--container-qa-log", type=Path, help="Optional exact-package clean Ubuntu container QA record")
    parser.add_argument("--output", type=Path, default=Path("build/distribution/RELEASE_MANIFEST.json"))
    args = parser.parse_args()
    report = manifest(args.package, args.gate_log, args.container_qa_log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("AUDITED LOCAL RELEASE:", report["version"], report["status"])
    print("SHA256:", report["package"]["sha256"])
    print("BUNDLED FILES:", len(report["bundled_files"]))
    print("REPORT:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
