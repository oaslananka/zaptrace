#!/usr/bin/python3
"""Version 0112: exact SHA-bound Ubuntu installation acceptance requirements."""

from __future__ import annotations

import hashlib
from pathlib import Path

from review_studio_clean_ubuntu_report_shared import main_with_report, render_report


def _requirements(package: Path, actual: str) -> dict[str, tuple[str, ...]]:
    return {
        "gate": (
            *(f"[{n}/9]" for n in range(1, 10)),
            "RELEASE GATE: PASS",
            "0 errors, 0 warnings, 0 informations",
        ),
        "copper": (
            f"{package.name}: OK",
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
        ),
        "older": (
            f"{package.name}: OK",
            "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
            "full Chrome native KiCad footprint R1 rotation 90",
            "full Chrome native KiCad footprint R1 (20,20) -> (21,20.5)",
            "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
            "NATIVE SCHEMATIC PCB PARITY CHROME: ALL PASSED",
            "Exact package 0.1.12 Chrome quarter-turn and private parity audit: PASS",
        ),
        "installed": (
            "INSTALLED_KICAD_NATIVE_COPPER_VERIFIED=37->36,16->16,PARITY=0",
            "INSTALLED_KICAD_COPPER_PRIVATE_BUNDLE_DOWNLOAD_AND_DISCARD: PASS",
            "FIXED_FULL_NATIVE_ESP32_PIN_ANCHORS 47",
            "FIXED_FULL_NATIVE_ESP32_PIN_NUMBER_2 ('VCC', '2', 'VCC_3V3')",
            "FIXED_NATIVE_ESP32_3D_IMAGES 10",
            "Installed 0.1.12 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
            "Installed 0.1.12 native custom KiCad rules loader + independent default DRC verified: PASS",
            "INSTALLED_0112_NATIVE_MULTINET_37_TO_35_AND_16_TO_16=PASS",
        ),
        "legacy": (
            "REAL_011_LEGACY_PRIVATE_ZIP_EXPORT_WITH_KICAD: PASS",
            "REAL_011_TO_0112_KICAD_REGENERATED_NATIVE_REVIEW: PASS",
            "Legacy 0.1.1 private ZIP restore: approved by source SHA",
        ),
        "lifecycle": (
            f"PACKAGE_SHA256={actual}",
            "UBUNTU_BASE=Ubuntu 24.04.5 LTS",
            "SIGNED_KICAD_PACKAGE=10.0.7",
            "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.11 = 0",
            "Real APT in-place upgrade to installed 0.1.12 passed",
            "OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
            "Native localhost startup/shutdown after upgrade passed",
            "Actual APT remove 0.1.12 passed",
            "AFTER_REMOVE_OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
            "FINAL_UBUNTU_BROWSER_INSTALLED_PACKAGE_APT_REMOVED=PASS",
            "FINAL_AFTER_BROWSER_OLD_PRIVATE_REVIEW_FILES_PRESERVED=24",
            "FINAL_SOURCE_SHA256_INPUTS_UNCHANGED=PASS",
        ),
        "ubuntu_browser": (
            f"{package.name}: OK",
            "PASS native exact U1.2",
            "GUARDED NATIVE COPPER CHROME: ALL PASSED",
            "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
            "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
            "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
            "UBUNTU_24_04_APT_0112_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS",
            "UBUNTU_24_04_APT_0112_MULTINET_BATCH_CHROME=PASS",
        ),
    }


def _report_lines(marker: str, gate_log: str) -> list[str]:
    return [
        "ZapTrace Review Studio 0.1.12 | unsigned local QA candidate; NOT public GA",
        marker,
        "SOURCE_GATE_SHA256=" + hashlib.sha256(gate_log.encode()).hexdigest(),
        ("Target: disposable genuine Ubuntu 24.04.5 LTS, native KiCad 10.0.7, system pcbnew; no APT signature bypass"),
        (
            "APT-installed Ubuntu 24.04 server exercised through MSI host Chrom"
            "e over real localhost Docker host networking; separately tested ro"
            "otless .deb extraction. No independent physical-host acceptance."
        ),
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.11 = 0",
        "Real APT in-place upgrade to installed 0.1.12 passed",
        "OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
        "Installed 0.1.12 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
        "Installed 0.1.12 native custom KiCad rules loader + independent default DRC verified: PASS",
        "INSTALLED_0112_NATIVE_MULTINET_37_TO_35_AND_16_TO_16=PASS",
        ("Installed 0.1.12 native browser ECO value copy-on-write with KiCad netlist/ERC and separate download: PASS"),
        "Installed 0.1.12 native browser PCB footprint placement ECO, copper/DRC and separate download: PASS",
        "Installed 0.1.12 native PCB quarter-turn and KiCad DRC: PASS",
        "Installed 0.1.12 native schematic/PCB readonly comparison: PASS",
        "Exact package 0.1.12 Chrome quarter-turn and private parity audit: PASS",
        "Installed 0.1.12 guarded native copper route and SHA-bounded DRC proof: PASS",
        "Exact package 0.1.12 Chrome guarded copper ZIP, SVG, discard: PASS",
        "EXACT_PACKAGE_0112_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS",
        "EXACT_PACKAGE_0112_NATIVE_TWO_NET_PROJECT_AND_SHA_EVIDENCE=PASS",
        "EXACT_PACKAGE_0112_CUSTOM_THROUGH_VIAS_MULTINET_AND_LEGACY_CHROME: PASS",
        "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
        "UBUNTU_24_04_APT_0112_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS",
        "UBUNTU_24_04_APT_0112_MULTINET_BATCH_CHROME=PASS",
        "Legacy 0.1.1 private ZIP restore: approved by source SHA",
        "Native localhost startup/shutdown after upgrade passed",
        "Actual APT remove 0.1.12 passed",
        "AFTER_REMOVE_OLD_PRIVATE_REVIEW_SHA256_VERIFIED=24",
        "FINAL_UBUNTU_BROWSER_INSTALLED_PACKAGE_APT_REMOVED=PASS",
        "FINAL_AFTER_BROWSER_OLD_PRIVATE_REVIEW_FILES_PRESERVED=24",
        "FINAL_SOURCE_SHA256_INPUTS_UNCHANGED=PASS",
        "Native ESP32 review U1.2='VCC' on VCC_3V3; 47 numbered pin anchors, 69 mapped PCB pads",
        ("Guarded F.Cu copper result: 37 -> 36 unconnected, 16 -> 16 existing physical DRC, zero new violations"),
        "Not all copper nets routed. Sixteen existing DRC manufacturing violations remain.",
        (
            "No PCB/schematic sync, zone/rip-up autorouting, independent fab/EM"
            "C acceptance, manufacturer provenance or commercial license assert"
            "ion."
        ),
        (
            "No independent physical-host acceptance, no publisher signature or"
            " trusted GA release. All source and user data protected."
        ),
        "",
        "Log checksum inventory (logs not included in public release kit):",
    ]


def report(
    package: Path,
    gate: Path,
    copper: Path,
    older: Path,
    installed: Path,
    legacy: Path,
    lifecycle: Path,
    ubuntu_browser: Path,
    output: Path,
) -> Path:
    return render_report(
        package,
        gate,
        copper,
        older,
        installed,
        legacy,
        lifecycle,
        ubuntu_browser,
        output,
        version="0.1.12",
        requirements=_requirements,
        build_lines=_report_lines,
    )


def main() -> int:
    return main_with_report(report, __doc__ or "Ubuntu installed-package acceptance")


if __name__ == "__main__":
    raise SystemExit(main())
