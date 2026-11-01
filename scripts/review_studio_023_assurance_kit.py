#!/usr/bin/env python3
"""Fail-closed reproducible 0.1.23 unsigned, source-bound QA archive.

Do not publish, sign, approve fabrication or rewrite accepted 0.1.13 bytes.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

VERSION = "0.1.23"
PKG_NAME = f"zaptrace-review-studio_{VERSION}_all.deb"
ZIP_NAME = f"zaptrace-review-studio_{VERSION}_ubuntu24.04-local-RC.zip"
REQUIRED = {
    "nine-stage-023": ("RELEASE GATE: PASS", "[9/9]", "0 errors, 0 warnings, 0 informations"),
    "exact-package-023": ("EXACT_023_INSTALLED_ROOTLESS_DEB_ALL_EIGHT_CHROME_KICAD_GATES=PASS", "[8/8]"),
    "viewer-modes-023": (
        "EXACT_020_SOURCE_LINKED_3D_MODEL_DIAGNOSTIC_CHROME=PASS",
        "390px model card has full-row readable warning and no horizontal overflow",
        "320px real native 3D model disclosure does not cover the PCB mode and tool controls",
        "320PX_3D_CONTROL_TOOLBAR_VERTICAL_OVERLAP_PX 0",
        "EXACT_020_MULTISHEET_NARROW_CHROME_GEOMETRY=PASS",
        "SOURCE_VERIFIED_KICAD_EMPTY_CHILD_STATE",
        "actual native KiCad blank child page has explicit, accurate and accessible source-empty explanation",
        "SCHEMATIC_GEOMETRY 320 PASS 0.00 px overlap",
        "EXACT_023_INSTALLED_3D_MULTISHEET_GALLERY_PREFERENCES_ALL_FOUR_GATES=PASS",
        "STAGED_020_NATIVE_KICAD_SESSION_TRIAGE_E2E=PASS",
        "TRIAGE_SCREEN_320_SHA256=",
        "TRIAGE_SCREEN_390_SHA256=",
        "MOBILE_021_REAL_SOURCE_BOUND_CHROME_CAMERA_QA=PASS",
        "MOBILE_021_REAL_CHROME_OPEN_MODEL_DIAGNOSTICS_320_TO_420_NO_TOOLBAR_OVERLAP=PASS",
        "MOBILE_3D_CAMERA_320_SHA256=",
        "MOBILE_3D_CAMERA_390_SHA256=",
        "MOBILE_3D_CAMERA_1440_SHA256=",
    ),
    "data-lifecycle-023": ("EXACT_023_REAL_CHROME_IMPORT_BACKUP_DELETE_RESTORE_AND_SOURCE_IMMUTABLE=PASS",),
    "ubuntu-apt-baseline-verified": (
        "UBUNTU_24_04_SIGNED_KICAD_10_PPA_AND_APT_BASELINE=PASS",
        "ACTUAL_020_APT_VERSION=0.1.20",
    ),
    "ubuntu-apt-upgrade": ("UBUNTU_REAL_APT_020_TO_023_UPGRADE_AND_VERSION_VERIFIED=PASS",),
    "ubuntu-installed-chrome-023": ("UBUNTU_24_04_APT_023_MULTINET_BATCH_CHROME=PASS",),
    "ubuntu-apt-upgrade-remove-023": ("EXACT_023_REAL_UBUNTU_24_04_UPGRADE_REMOVE=PASS",),
}
FIXED_TIMESTAMP = (2023, 11, 15, 1, 13, 20)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create(dist: Path, qa: Path) -> Path:
    dist, qa = dist.resolve(), qa.resolve()
    package = dist / PKG_NAME
    statement = dist / PKG_NAME.replace(".deb", ".sha256")
    if not package.is_file() or package.is_symlink() or not statement.is_file() or statement.is_symlink():
        raise ValueError("Expected exact 0.1.23 Debian package and checked SHA file")
    data = package.read_bytes()
    digest = sha256(data)
    if statement.read_text(encoding="ascii").strip() != f"{digest}  {PKG_NAME}":
        raise ValueError("Package checksum is mismatched")
    fields = subprocess.run(
        ["dpkg-deb", "-f", str(package), "Version", "Package"],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout
    if "0.1.23" not in fields or "zaptrace-review-studio" not in fields:
        raise ValueError("Installed metadata or version is inconsistent")
    reproducible = dist / "repro-023" / PKG_NAME
    if not reproducible.is_file() or sha256(reproducible.read_bytes()) != digest:
        raise ValueError("A reproducible second exact 0.1.23 build must exist")
    validation: dict[str, dict] = {}
    for name, markers in REQUIRED.items():
        log = qa / f"{name}.log"
        exit_file = qa / f"{name}.exit"
        if not log.is_file() or not exit_file.is_file() or exit_file.read_text().strip() != "0":
            raise ValueError(f"Missing completed successful QA gate: {name}")
        text = log.read_text(encoding="utf-8")
        if not all(marker in text for marker in markers):
            raise ValueError(f"Required QA assertions missing: {name}")
        if name not in {"nine-stage-023", "ubuntu-apt-baseline-verified"} and (f"PACKAGE_SHA256={digest}" not in text):
            raise ValueError(f"Package SHA proof missing: {name}")
        validation[name] = {"pass": True, "log_sha256": sha256(log.read_bytes())}
    status = qa / "model-availability-023.json"
    if not status.is_file() or status.is_symlink():
        raise ValueError("Source-bound KiCad 3D asset status required")
    asset = json.loads(status.read_text(encoding="utf-8"))
    models = asset.get("model_assets", {})
    canonical = (
        Path(__file__).resolve().parents[1] / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    )
    if not canonical.is_file() or sha256(canonical.read_bytes()) != asset.get("source_sha256"):
        raise ValueError("3D model inventory is not bound to the original KiCad source PCB")
    if not (
        len(asset.get("source_sha256", "")) == 64
        and models.get("model_geometry_approved") is False
        and models.get("declared_references") >= models.get("present_files", -1)
    ):
        raise ValueError("Model asset report must not falsely certify mechanical geometry")
    visual_proof = qa / "native-3d-model-diagnostics-390.png"
    if (
        not visual_proof.is_file()
        or visual_proof.is_symlink()
        or not visual_proof.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    ):
        raise ValueError("Exact installed-package mobile Chrome visual proof is missing")
    visual_bytes = visual_proof.read_bytes()
    if (
        len(visual_bytes) < 100
        or int.from_bytes(visual_bytes[16:20], "big") != 390
        or int.from_bytes(visual_bytes[20:24], "big") < 800
    ):
        raise ValueError("Chrome QA must capture the requested real 390px mobile viewport")
    visual_sha = sha256(visual_bytes)
    viewer_log = (qa / "viewer-modes-023.log").read_text(encoding="utf-8")
    if f"MOBILE_3D_PROOF_SHA256={visual_sha}" not in viewer_log:
        raise ValueError("3D model visual evidence SHA is not bound to tested Chrome output")
    narrow_proof = qa / "native-3d-model-diagnostics-320.png"
    if not narrow_proof.is_file() or narrow_proof.is_symlink():
        raise ValueError("320px Chrome screen proof unavailable")
    narrow_bytes = narrow_proof.read_bytes()
    if (
        not narrow_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        or len(narrow_bytes) < 100
        or int.from_bytes(narrow_bytes[16:20], "big") != 320
        or int.from_bytes(narrow_bytes[20:24], "big") < 700
    ):
        raise ValueError("320px Chrome visual proof is malformed or not the target viewport")
    narrow_sha = sha256(narrow_bytes)
    if f"MOBILE_3D_320_PROOF_SHA256={narrow_sha}" not in viewer_log:
        raise ValueError("320px model screen hash not tied to QA Chrome execution")
    schematic_proofs = {}
    for width in (320, 390):
        p = qa / f"native-multisheet-child-{width}.png"
        if not p.is_file() or p.is_symlink():
            raise ValueError(f"{width}px schematic Chrome screenshot is missing")
        schematic_png = p.read_bytes()
        if (
            not schematic_png.startswith(b"\x89PNG\r\n\x1a\n")
            or len(schematic_png) < 100
            or int.from_bytes(schematic_png[16:20], "big") != width
            or int.from_bytes(schematic_png[20:24], "big") != 844
        ):
            raise ValueError(f"{width}px schematic Chrome screenshot is invalid")
        schematic_digest = sha256(schematic_png)
        if f"MOBILE_SCHEMATIC_{width}_SHA256={schematic_digest}" not in viewer_log:
            raise ValueError(f"{width}px schematic Chrome screenshot SHA is not bound to the tested viewer")
        schematic_proofs[str(width)] = schematic_digest
    triage_proofs = {}
    for width in (320, 390):
        p = qa / f"triage-{width}.png"
        if not p.is_file() or p.is_symlink():
            raise ValueError(f"{width}px source-bound review note screenshot missing")
        raw = p.read_bytes()
        if (
            not raw.startswith(b"\x89PNG\r\n\x1a\n")
            or len(raw) < 100
            or int.from_bytes(raw[16:20], "big") != width
            or int.from_bytes(raw[20:24], "big") != 844
        ):
            raise ValueError(f"{width}px triage screenshot has invalid dimensions or PNG header")
        triage_sha = sha256(raw)
        if f"TRIAGE_SCREEN_{width}_SHA256={triage_sha}" not in viewer_log:
            raise ValueError(f"{width}px review note screenshot SHA does not match exact packaged Chrome test")
        triage_proofs[str(width)] = triage_sha
    camera_proofs = {}
    for width in (320, 390, 1440):
        picture = qa / f"mobile-camera-{width}.png"
        if not picture.is_file() or picture.is_symlink():
            raise ValueError(f"{width}px mobile KiCad camera proof missing")
        image_bytes = picture.read_bytes()
        if (
            not image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or len(image_bytes) < 100
            or int.from_bytes(image_bytes[16:20], "big") != width
            or int.from_bytes(image_bytes[20:24], "big") != 844
        ):
            raise ValueError(f"{width}px native camera image malformed or wrong viewport")
        camera_digest = sha256(image_bytes)
        if f"MOBILE_3D_CAMERA_{width}_SHA256={camera_digest}" not in viewer_log:
            raise ValueError(f"{width}px mobile KiCad camera screenshot SHA not tied to actual Chrome run")
        camera_proofs[str(width)] = camera_digest
    summary = (
        "# Review Studio 0.1.23 — unsigned local EDA engineering candidate\n\n"
        f"Exact package SHA-256: `{digest}`. Historical 0.1.12/0.1.13 artifacts remain frozen.\n\n"
        "Native KiCad PCB/schematic/3D source, DRC/continuity, project comparison, keyboard and mobile interaction, "
        "3D per-footprint file diagnostics, ECO, guarded copper multinet, ZIP backup/delete/restore, "
        "Ubuntu 24.04 APT install/upgrade/remove were exercised against verified package bytes.\n\n"
        "**NOT PUBLIC GA. UNSIGNED. NONCOMMERCIAL. NOT FABRICATION-APPROVED.**\n\n"
        "Existing native physical DRC violations and incomplete copper routing remain. "
        "3D file presence is not geometry/placement/electrical or assembly clearance qualification. "
        "Full bidirectional schematic-PCB synchronization and independent physical clean-host acceptance not proven.\n"
    )
    manifest = {
        "version": VERSION,
        "status": "unsigned-local-review-candidate; NOT public GA",
        "package": {"name": PKG_NAME, "sha256": digest, "bytes": len(data)},
        "mobile_3d_diagnostics_screenshot_sha256": visual_sha,
        "mobile_3d_320_screenshot_sha256": narrow_sha,
        "mobile_native_schematic_screenshots_sha256": schematic_proofs,
        "mobile_triage_screenshots_sha256": triage_proofs,
        "mobile_native_camera_screenshots_sha256": camera_proofs,
        "target": {"ubuntu": "24.04", "native_kicad": "10.0.7"},
        "validation": validation,
        "code_signed": False,
        "public_release": False,
        "fabrication_approved": False,
        "three_d_model_geometry_approved": False,
        "full_bi_directional_schematic_pcb_sync_proven": False,
        "independent_clean_physical_host_tested": False,
    }
    contents = {
        PKG_NAME: data,
        statement.name: statement.read_bytes(),
        "ACCEPTANCE_023.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        "MODEL_AVAILABILITY_023.json": status.read_bytes(),
        "LOCAL_QA_AND_LIMITATIONS.md": summary.encode(),
    }
    output = dist / ZIP_NAME
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipfile_obj:
        for name in sorted(contents):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.external_attr = 0o100644 << 16
            zipfile_obj.writestr(info, contents[name])
    (dist / "ACCEPTANCE_023.json").write_bytes(contents["ACCEPTANCE_023.json"])
    zip_digest = sha256(output.read_bytes())
    (dist / f"{ZIP_NAME}.sha256").write_text(f"{zip_digest}  {ZIP_NAME}\n", encoding="ascii")
    print(f"PACKAGE_SHA256={digest}")
    print(f"KIT_SHA256={zip_digest}")
    print(f"LOCAL_023_UNSIGNED_SHA_BOUND_ACCEPTANCE_KIT=PASS {output}")
    return output


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    create(root / "build/distribution", root / "build/qa-023-release-20261013")
