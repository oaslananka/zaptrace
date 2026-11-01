"""Fail-closed tests for SHA-linked clean Ubuntu 0.1.12 candidate evidence."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_studio_clean_ubuntu_0112_report import report

from tests.review_studio_clean_ubuntu_contract_shared import (
    assert_missing_proof_rejected,
    assert_modified_package_and_symlink_rejected,
    assert_old_sha_rejected,
    assert_sha_bound_report,
)


def acceptance_fixture(tmp_path: Path) -> tuple[Path, ...]:
    package = tmp_path / "zaptrace-review-studio_0.1.12_all.deb"
    package.write_bytes(b"hypothetical unit-test-only versioned package")
    sha = hashlib.sha256(package.read_bytes()).hexdigest()
    package.with_suffix(".sha256").write_text(f"{sha}  {package.name}\n")
    marker = f"PACKAGE_SHA256={sha}\n"
    files = [
        tmp_path / name
        for name in (
            "gate.log",
            "copper.log",
            "old-chrome.log",
            "installed.log",
            "legacy.log",
            "apt.log",
            "ubuntu-chrome.log",
        )
    ]
    files[0].write_text(
        " ".join(f"[{i}/9]" for i in range(1, 10)) + "\nRELEASE GATE: PASS\n0 errors, 0 warnings, 0 informations\n"
    )
    files[1].write_text(
        marker
        + f"{package.name}: OK\n"
        + "\n".join(
            (
                "PASS native exact U1.2",
                "37 open, 16 physical, 0 parity",
                "Chrome displays two genuine native KiCad",
                "390px mobile Chrome native copper workflow has no horizontal overflow",
                "real Chrome downloaded authenticated private native-copper-project.zip",
                "real Chrome downloaded authenticated private EVIDENCE.json",
                "Chrome discard removes only the isolated native copper draft",
                "zero runtime Chrome JavaScript errors",
                "Exact package 0.1.12 Chrome guarded copper ZIP, SVG, discard: PASS",
                "EXACT_PACKAGE_0112_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS",
                "EXACT_PACKAGE_0112_NATIVE_TWO_NET_PROJECT_AND_SHA_EVIDENCE=PASS",
                "EXACT_PACKAGE_0112_CUSTOM_THROUGH_VIAS_MULTINET_AND_LEGACY_CHROME: PASS",
            )
        )
    )
    files[2].write_text(
        marker
        + f"{package.name}: OK\n"
        + "\n".join(
            (
                "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
                "full Chrome native KiCad footprint R1 rotation 90",
                "full Chrome native KiCad footprint R1 (20,20) -> (21,20.5)",
                "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
                "NATIVE SCHEMATIC PCB PARITY CHROME: ALL PASSED",
                "Exact package 0.1.12 Chrome quarter-turn and private parity audit: PASS",
            )
        )
    )
    files[3].write_text(
        marker
        + "\n".join(
            (
                "INSTALLED_KICAD_NATIVE_COPPER_VERIFIED=37->36,16->16,PARITY=0",
                "INSTALLED_KICAD_COPPER_PRIVATE_BUNDLE_DOWNLOAD_AND_DISCARD: PASS",
                "FIXED_FULL_NATIVE_ESP32_PIN_ANCHORS 47",
                "FIXED_FULL_NATIVE_ESP32_PIN_NUMBER_2 ('VCC', '2', 'VCC_3V3')",
                "FIXED_NATIVE_ESP32_3D_IMAGES 10",
                "Installed 0.1.12 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
                "Installed 0.1.12 native custom KiCad rules loader + independent default DRC verified: PASS",
                "INSTALLED_0112_NATIVE_MULTINET_37_TO_35_AND_16_TO_16=PASS",
            )
        )
    )
    files[4].write_text(
        marker
        + "REAL_011_LEGACY_PRIVATE_ZIP_EXPORT_WITH_KICAD: PASS\n"
        + "REAL_011_TO_0112_KICAD_REGENERATED_NATIVE_REVIEW: PASS\n"
        + "Legacy 0.1.1 private ZIP restore: approved by source SHA\n"
    )
    files[5].write_text(
        marker
        + "\n".join(
            (
                "UBUNTU_BASE=Ubuntu 24.04.5 LTS",
                "SIGNED_KICAD_PACKAGE=10.0.7",
                "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.11 = 0",
                "Real APT in-place upgrade to installed 0.1.12 passed",
                "OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
                "Native localhost startup/shutdown after upgrade passed",
                "Actual APT remove 0.1.12 passed",
                "AFTER_REMOVE_OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
                "FINAL_SOURCE_SHA256_INPUTS_UNCHANGED=PASS",
                "FINAL_UBUNTU_BROWSER_INSTALLED_PACKAGE_APT_REMOVED=PASS",
                "FINAL_AFTER_BROWSER_OLD_PRIVATE_REVIEW_FILES_PRESERVED=24",
            )
        )
    )
    files[6].write_text(
        marker
        + f"{package.name}: OK\n"
        + "\n".join(
            (
                "PASS native exact U1.2",
                "GUARDED NATIVE COPPER CHROME: ALL PASSED",
                "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
                "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
                "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
                "UBUNTU_24_04_APT_0112_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS",
                "UBUNTU_24_04_APT_0112_MULTINET_BATCH_CHROME=PASS",
            )
        )
    )
    return (package, *files, tmp_path / "result.txt")


def test_sha_bound_0112_acceptance_report_requires_all_independent_logs(tmp_path: Path) -> None:
    assert_sha_bound_report(report, acceptance_fixture(tmp_path))


@pytest.mark.parametrize(
    "log_index,omitted",
    [
        (2, "Exact package 0.1.12 Chrome guarded copper ZIP, SVG, discard: PASS"),
        (3, "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED"),
        (4, "FIXED_FULL_NATIVE_ESP32_PIN_ANCHORS 47"),
        (5, "REAL_011_TO_0112_KICAD_REGENERATED_NATIVE_REVIEW: PASS"),
        (6, "Actual APT remove 0.1.12 passed"),
        (7, "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS"),
        (2, "EXACT_PACKAGE_0112_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS"),
        (4, "Installed 0.1.12 native custom KiCad rules loader + independent default DRC verified: PASS"),
        (7, "UBUNTU_24_04_APT_0112_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS"),
        (2, "EXACT_PACKAGE_0112_NATIVE_TWO_NET_PROJECT_AND_SHA_EVIDENCE=PASS"),
        (2, "EXACT_PACKAGE_0112_CUSTOM_THROUGH_VIAS_MULTINET_AND_LEGACY_CHROME: PASS"),
        (4, "INSTALLED_0112_NATIVE_MULTINET_37_TO_35_AND_16_TO_16=PASS"),
        (7, "UBUNTU_24_04_APT_0112_MULTINET_BATCH_CHROME=PASS"),
    ],
)
def test_missing_required_native_or_lifecycle_proof_blocks_manifest(
    tmp_path: Path, log_index: int, omitted: str
) -> None:
    assert_missing_proof_rejected(report, acceptance_fixture(tmp_path), log_index, omitted)


def test_wrong_exact_deb_sha_cannot_reuse_old_acceptance(tmp_path: Path) -> None:
    assert_old_sha_rejected(report, acceptance_fixture(tmp_path))


def test_mismatched_manifest_and_symlink_gate_are_rejected(tmp_path: Path) -> None:
    assert_modified_package_and_symlink_rejected(report, acceptance_fixture(tmp_path))
