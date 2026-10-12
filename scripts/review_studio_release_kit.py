#!/usr/bin/env python3
"""Build deterministic offline QA bundle without publishing or signing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

FILES = (
    "zaptrace-review-studio_0.1.12_all.deb",
    "zaptrace-review-studio_0.1.12_all.sha256",
    "RELEASE_MANIFEST.json",
    "CLEAN_UBUNTU_2404_0112_QA.txt",
)
VERSIONED_KIT = "zaptrace-review-studio_0.1.12_ubuntu24.04-local-RC.zip"
TIMESTAMP = (2023, 11, 15, 1, 13, 20)


def create(distribution: Path, quickstart: Path) -> Path:
    if not quickstart.is_file():
        raise ValueError("Review Studio installation guide must be available")
    origin = distribution.resolve()
    mapped: dict[str, bytes] = {}
    for name in FILES:
        file = origin / name
        if not file.is_file() or file.is_symlink():
            raise ValueError("Missing or nonregular QA release evidence: " + name)
        mapped[name] = file.read_bytes()
    package = mapped[FILES[0]]
    actual = hashlib.sha256(package).hexdigest()
    if mapped[FILES[1]].decode("ascii").strip() != actual + "  " + FILES[0]:
        raise ValueError("Current .deb hash is not proven by the provided SHA manifest")
    metadata = json.loads(mapped[FILES[2]])
    if metadata.get("package", {}).get("sha256") != actual or metadata.get("version") != "0.1.12":
        raise ValueError("Release manifest does not match this exact .deb")
    verified = metadata.get("validation", {})
    required = (
        "nine_stage_release_gate",
        "clean_ubuntu_disposable_container_real_apt_install",
        "clean_ubuntu_container_native_3d_isometric_and_top",
        "clean_ubuntu_container_native_3d_eight_camera_orbit_frames",
        "clean_ubuntu_localhost_schematic_value_eco_native_validation",
        "clean_ubuntu_localhost_pcb_placement_eco_native_drc",
        "clean_ubuntu_native_footprint_quarter_turn",
        "clean_ubuntu_native_schematic_pcb_read_only_parity_audit",
        "clean_ubuntu_exact_package_browser_rotation_and_parity",
        "clean_ubuntu_guarded_native_copper_route",
        "clean_ubuntu_exact_package_browser_guarded_copper",
        "clean_ubuntu_container_inplace_0111_to_0112_upgrade",
        "clean_ubuntu_container_legacy_zip_restored_using_fresh_kicad",
        "clean_ubuntu_custom_rule_loader_and_default_drc_dual_proof",
        "clean_ubuntu_exact_package_browser_two_via_custom_rule_proof",
        "clean_ubuntu_verified_native_multinet_cumulative_drc",
        "clean_ubuntu_exact_package_browser_multinet_batch",
        "clean_ubuntu_installed_browser_multinet_batch",
    )
    if not all(verified.get(x) is True for x in required):
        raise ValueError("Missing real native clean Ubuntu QA evidence; no release kit issued")
    if any(verified.get(x) is not False for x in ("code_signed", "fabrication_approved")):
        raise ValueError("Release is not allowed to imply trusted signing or fabrication approval")
    qa = mapped[FILES[3]].decode("utf-8")
    if f"PACKAGE_SHA256={actual}" not in qa or "Actual APT remove 0.1.12 passed" not in qa:
        raise ValueError("Clean Ubuntu QA does not belong to this package")
    readme = quickstart.read_bytes()
    if (
        b"local release candidate, unsigned" not in readme
        or b"NOT public GA" not in str(metadata.get("status")).encode()
    ):
        raise ValueError("Do not omit release-candidate and unsigned disclosures")
    mapped["INSTALL_AND_RELEASE_NOTES.md"] = readme
    output = origin / VERSIONED_KIT
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, strict_timestamps=False
    ) as archive:
        for name in sorted(mapped):
            info = zipfile.ZipInfo(name, date_time=TIMESTAMP)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, mapped[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{checksum}  {output.name}\n", encoding="ascii")
    print("OFFLINE LOCAL-ONLY REVIEW RELEASE KIT:", output)
    print("KIT SHA256:", checksum)
    print("PACKAGE SHA256:", actual)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distribution", type=Path, default=Path("build/distribution"))
    parser.add_argument("--quickstart", type=Path, default=Path("scripts/REVIEW_STUDIO_INSTALL_QUICKSTART.md"))
    args = parser.parse_args()
    create(args.distribution, args.quickstart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
