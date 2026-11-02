#!/usr/bin/env python3
"""Version-bound source and evidence acceptance for local Review Studio builds."""

from __future__ import annotations

from pathlib import Path

from review_studio_assurance_kit_shared import create as _create

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


def create(dist: Path, qa: Path) -> Path:
    return _create(dist, qa, version=VERSION, required=REQUIRED)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    create(root / "build/distribution", root / "build/qa-023-release-20261013")
