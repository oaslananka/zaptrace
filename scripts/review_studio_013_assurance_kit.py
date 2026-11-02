#!/usr/bin/env python3
"""Fail-closed, reproducible, unsigned 0.1.13 local EDA audit release kit.

Does not publish, sign, edit the immutable 0.1.12 release or include user
KiCad sources. Evidence is tied to the exact .deb SHA and individual logs.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

VERSION = "0.1.13"
PKG_NAME = f"zaptrace-review-studio_{VERSION}_all.deb"
ZIP_NAME = f"zaptrace-review-studio_{VERSION}_ubuntu24.04-local-RC.zip"
REQUIRED = {
    "nine-stage-source-013": ("RELEASE GATE: PASS", "[9/9]"),
    "eight-gate-exact-package": ("EXACT_013_INSTALLED_ROOTLESS_DEB_ALL_EIGHT_CHROME_KICAD_GATES=PASS", "[8/8]"),
    "viewer-modes-013": (
        "EXACT_013_INSTALLED_3D_MULTISHEET_GALLERY_PREFERENCES_ALL_FOUR_GATES=PASS",
        "[4/4]",
    ),
    "data-lifecycle-exact-package": (
        "EXACT_013_REAL_CHROME_IMPORT_BACKUP_DELETE_RESTORE_AND_SOURCE_IMMUTABLE=PASS",
        "NATIVE ZIP RESTORE WITH FRESH ERC/DRC: ALL CHROME TESTS PASSED",
    ),
    "ubuntu24-apt-013-verified": (
        "ACTUAL_UBUNTU_24_04_APT_0_1_13_INSTALLED=PASS",
        "SIGNED_KICAD_10_PPA_AND_OS_CA_CERTS=PASS",
    ),
    "ubuntu24-apt-chrome-013": (
        "UBUNTU_24_04_REAL_APT_INSTALLED_SERVER_PLUS_HOST_CHROME_NATIVE_COPPER_PCB_ROTATE_SCHEMATIC_ECO=PASS",
        "UBUNTU_24_04_APT_013_MULTINET_BATCH_CHROME=PASS",
    ),
    "ubuntu24-apt-upgrade-remove-013": (
        "UBUNTU_24_04_REAL_012_TO_013_UPGRADE_REMOVE_PRIVATE_PRESERVED=PASS",
        "REAL_013_APT_REMOVE_RETAINS_USER_DATA_AND_REMOVES_BINARIES=PASS",
    ),
}
TIME = (2023, 11, 15, 1, 13, 20)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create(distribution: Path, evidence: Path) -> Path:
    distribution = distribution.resolve()
    evidence = evidence.resolve()
    package = distribution / PKG_NAME
    checksum = distribution / PKG_NAME.replace(".deb", ".sha256")
    if not package.is_file() or not checksum.is_file() or package.is_symlink() or checksum.is_symlink():
        raise ValueError("Exact 0.1.13 Debian package or SHA manifest unavailable")
    raw = package.read_bytes()
    sha = digest(raw)
    if checksum.read_text(encoding="ascii").strip() != f"{sha}  {PKG_NAME}":
        raise ValueError("0.1.13 Debian archive SHA does not match the recorded manifest")
    fields = subprocess.run(
        ["dpkg-deb", "-f", str(package), "Version", "Package"],
        check=True,
        capture_output=True,
        text=True,
        timeout=12,
    ).stdout
    if not ("0.1.13" in fields and "zaptrace-review-studio" in fields):
        raise ValueError("Unexpected package metadata/version")
    checks: dict[str, dict[str, str]] = {}
    for name, markers in REQUIRED.items():
        log = evidence / f"{name}.log"
        status = evidence / f"{name}.exit"
        if not log.is_file() or not status.is_file() or status.read_text().strip() != "0":
            raise ValueError(f"Missing successful independent acceptance: {name}")
        data = log.read_text(encoding="utf-8")
        if any(marker not in data for marker in markers):
            raise ValueError(f"Acceptance markers incomplete for: {name}")
        if name not in {"ubuntu24-apt-013-verified", "nine-stage-source-013"} and f"PACKAGE_SHA256={sha}" not in data:
            raise ValueError(f"Acceptance was not bound to the exact candidate SHA: {name}")
        checks[name] = {"result": "PASS", "log_sha256": digest(log.read_bytes())}
    gate = (evidence / "nine-stage-source-013.log").read_text()
    if any(f"[{i}/9]" not in gate for i in range(1, 10)) or "0 errors, 0 warnings, 0 informations" not in gate:
        raise ValueError("Nine-stage gate or static analysis was incomplete")
    verified = (evidence / "ubuntu24-apt-013-verified.log").read_text()
    if f"PACKAGE_SHA256={sha}" not in verified:
        raise ValueError("Actual installed Ubuntu candidate differs from SHA-qualified package")
    repro = distribution / "repro-013" / PKG_NAME
    if not repro.is_file() or digest(repro.read_bytes()) != sha:
        raise ValueError("Independent bit-for-bit 0.1.13 reproducible build proof unavailable")
    summary = (
        "# ZapTrace Review Studio 0.1.13 — unsigned local engineering candidate\n\n"
        f"Exact .deb SHA-256: `{sha}`. The previous 0.1.12 release remains frozen.\n\n"
        "Passed: nine-stage source gate, installed-package browser PCB/schematic/3D, two-snapshot comparison, "
        "guarded copper multinet/through-via, schematic & PCB ECO, parity, local import/ZIP backup/delete/restore, "
        "real disposable Ubuntu 24.04 APT install, 0.1.12→0.1.13 upgrade, "
        "and APT removal with preserved private user data.\n\n"
        "**Not public GA, unsigned, noncommercial license, "
        "no independent clean physical machine acceptance or fabrication authorization.** "
        "Original example PCB retains 16 native physical DRC findings, incomplete connectivity, "
        "no validated full bidirectional EDA synchronization, and unverified 3D/assembly model coverage. "
        "Source 3D links for USB-C J1/ESP32 U1 reference obsolete .wrl assets: not mechanical signoff.\n"
    )
    manifest = {
        "version": VERSION,
        "status": "locally-qualified-unsigned-review-candidate; NOT public GA",
        "package": {"name": PKG_NAME, "sha256": sha, "bytes": len(raw)},
        "target": {"ubuntu": "24.04", "native_kicad": "10.0.7"},
        "validation": checks,
        "code_signed": False,
        "public_release": False,
        "fabrication_approved": False,
        "independent_clean_physical_host_tested": False,
        "full_bi_directional_schematic_pcb_sync_proven": False,
        "three_d_model_coverage_approved": False,
    }
    json_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    entries = {
        PKG_NAME: raw,
        PKG_NAME.replace(".deb", ".sha256"): checksum.read_bytes(),
        "ACCEPTANCE_013.json": json_bytes,
        "LOCAL_QA_AND_LIMITATIONS.md": summary.encode(),
    }
    output = distribution / ZIP_NAME
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, contents in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=TIME)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents, compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    (distribution / "ACCEPTANCE_013.json").write_bytes(json_bytes)
    zip_sha = digest(output.read_bytes())
    (distribution / f"{ZIP_NAME}.sha256").write_text(f"{zip_sha}  {ZIP_NAME}\n", encoding="ascii")
    print(f"VERSIONED_013_LOCAL_KIT={output}")
    print(f"PACKAGE_SHA256={sha}")
    print(f"KIT_SHA256={zip_sha}")
    print("LOCAL_UNSIGNED_013_REPRODUCIBLE_ACCEPTANCE_KIT=PASS")
    return output


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    create(root / "build/distribution", root / "build/qa-013-release-20261012")
