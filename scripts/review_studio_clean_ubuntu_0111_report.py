#!/usr/bin/python3
"""Fail-closed SHA-qualified Ubuntu 24.04 + actual Chrome release acceptance record.

Do not synthesize a successful release from historical version markers.
Requires auditable real test logs, the exact final .deb and prior gate.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def check(log: str, *required: str) -> None:
    absent = [item for item in required if item not in log]
    if absent:
        raise ValueError("Independent acceptance logs have not proved: " + "; ".join(absent))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    files = [package, gate, copper, older, installed, legacy, lifecycle, ubuntu_browser]
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("All exact-package and genuine Ubuntu logs must be readable regular files")
    if package.name != "zaptrace-review-studio_0.1.11_all.deb":
        raise ValueError("Native Review Studio release version must be 0.1.11")
    actual = sha(package)
    if package.with_suffix(".sha256").read_text().strip() != f"{actual}  {package.name}":
        raise ValueError("Debian package SHA manifest does not match exact tested bytes")
    content = [path.read_text(encoding="utf-8") for path in files[1:]]
    gate_log, copper_log, older_log, installed_log, legacy_log, lifecycle_log, ubuntu_browser_log = content
    check(
        gate_log,
        *(f"[{n}/9]" for n in range(1, 10)),
        "RELEASE GATE: PASS",
        "0 errors, 0 warnings, 0 informations",
    )
    check(
        copper_log,
        f"{package.name}: OK",
        "PASS native exact U1.2",
        "37 open, 16 physical, 0 parity",
        "Chrome displays two genuine native KiCad",
        "390px mobile Chrome native copper workflow has no horizontal overflow",
        "real Chrome downloaded authenticated private native-copper-project.zip",
        "real Chrome downloaded authenticated private EVIDENCE.json",
        "Chrome discard removes only the isolated native copper draft",
        "zero runtime Chrome JavaScript errors",
        "Exact package 0.1.11 Chrome guarded copper ZIP, SVG, discard: PASS",
        "EXACT_PACKAGE_0111_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS",
    )
    check(
        older_log,
        f"{package.name}: OK",
        "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
        "full Chrome native KiCad footprint R1 rotation 90",
        "full Chrome native KiCad footprint R1 (20,20) -> (21,20.5)",
        "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
        "NATIVE SCHEMATIC PCB PARITY CHROME: ALL PASSED",
        "Exact package 0.1.11 Chrome quarter-turn and private parity audit: PASS",
    )
    check(
        installed_log,
        "INSTALLED_KICAD_NATIVE_COPPER_VERIFIED=37->36,16->16,PARITY=0",
        "INSTALLED_KICAD_COPPER_PRIVATE_BUNDLE_DOWNLOAD_AND_DISCARD: PASS",
        "FIXED_FULL_NATIVE_ESP32_PIN_ANCHORS 47",
        "FIXED_FULL_NATIVE_ESP32_PIN_NUMBER_2 ('VCC', '2', 'VCC_3V3')",
        "FIXED_NATIVE_ESP32_3D_IMAGES 10",
        "Installed 0.1.11 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
        "Installed 0.1.11 native custom KiCad rules loader + independent default DRC verified: PASS",
    )
    check(
        legacy_log,
        "REAL_011_LEGACY_PRIVATE_ZIP_EXPORT_WITH_KICAD: PASS",
        "REAL_011_TO_0111_KICAD_REGENERATED_NATIVE_REVIEW: PASS",
        "Legacy 0.1.1 private ZIP restore: approved by source SHA",
    )
    check(
        lifecycle_log,
        f"PACKAGE_SHA256={actual}",
        "UBUNTU_BASE=Ubuntu 24.04.5 LTS",
        "SIGNED_KICAD_PACKAGE=10.0.7",
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0",
        "Real APT in-place upgrade to installed 0.1.11 passed",
        "OLD_PRIVATE_REVIEW_SHA256_VERIFIED=14",
        "Native localhost startup/shutdown after upgrade passed",
        "Actual APT remove 0.1.11 passed",
        "AFTER_REMOVE_OLD_PRIVATE_REVIEW_SHA256_VERIFIED=14",
        "FINAL_UBUNTU_BROWSER_INSTALLED_PACKAGE_APT_REMOVED=PASS",
        "FINAL_AFTER_BROWSER_OLD_PRIVATE_REVIEW_FILES_PRESERVED=14",
        "FINAL_SOURCE_SHA256_INPUTS_UNCHANGED=PASS",
    )
    check(
        ubuntu_browser_log,
        f"{package.name}: OK",
        "PASS native exact U1.2",
        "GUARDED NATIVE COPPER CHROME: ALL PASSED",
        "NATIVE KICAD PCB PLACEMENT ECO BROWSER: ALL PASSED",
        "REAL LOCALHOST NATIVE SCHEMATIC ECO EDITOR + CHROME: ALL PASSED",
        "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
        "UBUNTU_24_04_APT_0111_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS",
    )
    # Historical version QA or an earlier, superseded temporary .deb is never
    # enough; bind *all* check logs to the same final package digest.
    marker = f"PACKAGE_SHA256={actual}"
    for _name, log in (
        ("Chrome copper", copper_log),
        ("Chrome regressions", older_log),
        ("Ubuntu installed", installed_log),
        ("Legacy ZIP", legacy_log),
        ("APT lifecycle", lifecycle_log),
        ("Ubuntu installed browser", ubuntu_browser_log),
    ):
        # A substring match would accept OLD_PACKAGE_SHA256=<hash>, an
        # unrelated previous release marker, or explanatory free text.
        # Only an exact standalone hash assignment can bind a QA log.
        if marker not in log.splitlines():
            raise ValueError(f"{_name} proof not bound to the exact package SHA-256")
    lines = [
        "ZapTrace Review Studio 0.1.11 | unsigned local QA candidate; NOT public GA",
        marker,
        "SOURCE_GATE_SHA256=" + hashlib.sha256(gate_log.encode()).hexdigest(),
        "Target: disposable genuine Ubuntu 24.04.5 LTS, native KiCad 10.0.7, system pcbnew; no APT signature bypass",
        "APT-installed Ubuntu 24.04 server exercised through MSI host Chrome over real"
        " localhost Docker host networking; separately tested rootless .deb extraction."
        " No independent physical-host acceptance.",
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0",
        "Real APT in-place upgrade to installed 0.1.11 passed",
        "OLD_PRIVATE_REVIEW_SHA256_VERIFIED=14",
        "Installed 0.1.11 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS",
        "Installed 0.1.11 native custom KiCad rules loader + independent default DRC verified: PASS",
        "Installed 0.1.11 native browser ECO value copy-on-write with KiCad netlist/ERC and separate download: PASS",
        "Installed 0.1.11 native browser PCB footprint placement ECO, copper/DRC and separate download: PASS",
        "Installed 0.1.11 native PCB quarter-turn and KiCad DRC: PASS",
        "Installed 0.1.11 native schematic/PCB readonly comparison: PASS",
        "Exact package 0.1.11 Chrome quarter-turn and private parity audit: PASS",
        "Installed 0.1.11 guarded native copper route and SHA-bounded DRC proof: PASS",
        "Exact package 0.1.11 Chrome guarded copper ZIP, SVG, discard: PASS",
        "EXACT_PACKAGE_0111_CUSTOM_TWO_VIA_AND_LEGACY_FCU_CHROME: PASS",
        "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
        "UBUNTU_24_04_APT_0111_CUSTOM_DRC_AND_TWO_VIA_CHROME=PASS",
        "Legacy 0.1.1 private ZIP restore: approved by source SHA",
        "Native localhost startup/shutdown after upgrade passed",
        "Actual APT remove 0.1.11 passed",
        "AFTER_REMOVE_OLD_PRIVATE_REVIEW_SHA256_VERIFIED=14",
        "FINAL_UBUNTU_BROWSER_INSTALLED_PACKAGE_APT_REMOVED=PASS",
        "FINAL_AFTER_BROWSER_OLD_PRIVATE_REVIEW_FILES_PRESERVED=14",
        "FINAL_SOURCE_SHA256_INPUTS_UNCHANGED=PASS",
        "Native ESP32 review U1.2='VCC' on VCC_3V3; 47 numbered pin anchors, 69 mapped PCB pads",
        "Guarded F.Cu copper result: 37 -> 36 unconnected, 16 -> 16 existing physical DRC, zero new violations",
        "Not all copper nets routed. Sixteen existing DRC manufacturing violations remain.",
        "No PCB/schematic sync, zone/rip-up autorouting, independent fab/EMC acceptance,"
        " manufacturer provenance or commercial license assertion.",
        "No independent physical-host acceptance, no publisher signature or trusted GA release."
        " All source and user data protected.",
        "",
        "Log checksum inventory (logs not included in public release kit):",
    ]
    for key, file in zip(
        (
            "9-stage-gate",
            "chrome-copper",
            "chrome-existing",
            "ubuntu-native",
            "legacy-private-zip",
            "apt-upgrade-remove",
            "ubuntu-installed-chrome",
        ),
        files[1:],
        strict=True,
    ):
        lines.append(key + " sha256=" + sha(file))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    print("SHA_BOUND_REAL_UBUNTU_ACCEPTANCE_WRITTEN", output)
    print("PACKAGE_SHA256=" + actual)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("package", "gate", "copper", "older", "installed", "legacy", "lifecycle", "ubuntu_browser", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report(
        *(
            getattr(args, name)
            for name in (
                "package",
                "gate",
                "copper",
                "older",
                "installed",
                "legacy",
                "lifecycle",
                "ubuntu_browser",
                "output",
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
