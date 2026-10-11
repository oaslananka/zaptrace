"""Local release kit contains only exact QA-bound package and install guide."""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SOURCE))

from review_studio_build_deb import build  # noqa: E402
from review_studio_release_kit import VERSIONED_KIT, create  # noqa: E402
from review_studio_release_manifest import manifest, sha256  # noqa: E402


@pytest.fixture
def local_evidence(tmp_path: Path) -> tuple[Path, Path]:
    distribution = tmp_path / "dist"
    package = build(SOURCE.parent, distribution)
    gate = tmp_path / "gate.txt"
    gate.write_text(
        "\n".join(f"[{x}/9] PASS" for x in range(1, 10))
        + "\n0 errors, 0 warnings, 0 informations\nRELEASE GATE: PASS\n"
    )
    qa = distribution / "CLEAN_UBUNTU_2404_018_QA.txt"
    qa.write_text(
        "PACKAGE_SHA256=" + sha256(package) + "\n"
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0\n"
        "Real APT in-place upgrade to installed 0.1.8 passed\n"
        "Installed 0.1.8 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS\n"
        "Installed 0.1.8 native browser ECO value copy-on-write with KiCad netlist/ERC and separate download: PASS\n"
        "Installed 0.1.8 native browser PCB footprint placement ECO, copper/DRC and separate download: PASS\n"
        "Legacy 0.1.1 private ZIP restore: approved by source SHA\n"
        "Native localhost startup/shutdown after upgrade passed\n"
        "Actual APT remove 0.1.8 passed\n"
    )
    output = manifest(package, gate, qa)
    (distribution / "RELEASE_MANIFEST.json").write_text(json.dumps(output, indent=2) + "\n")
    return distribution, SOURCE / "REVIEW_STUDIO_INSTALL_QUICKSTART.md"


def test_release_kit_reproducible_and_never_contains_private_or_unverified_files(
    local_evidence: tuple[Path, Path],
) -> None:
    directory, guide = local_evidence
    package = directory / "zaptrace-review-studio_0.1.8_all.deb"
    kit = create(directory, guide)
    first = kit.read_bytes()
    assert kit.name == VERSIONED_KIT
    assert create(directory, guide).read_bytes() == first
    with zipfile.ZipFile(kit) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 5
        assert archive.read(package.name) == package.read_bytes()
        assert archive.read("RELEASE_MANIFEST.json") == (directory / "RELEASE_MANIFEST.json").read_bytes()
        assert b"unsigned" in archive.read("INSTALL_AND_RELEASE_NOTES.md")
        assert not any(
            name.endswith((".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_prl")) for name in archive.namelist()
        )
    actual = hashlib.sha256(first).hexdigest()
    assert kit.with_suffix(kit.suffix + ".sha256").read_text().strip() == f"{actual}  {kit.name}"


def test_release_kit_refuses_package_tampering_or_unqualified_manifest(local_evidence: tuple[Path, Path]) -> None:
    directory, guide = local_evidence
    target = directory / "zaptrace-review-studio_0.1.8_all.deb"
    target.write_bytes(target.read_bytes() + b"injected")
    with pytest.raises(ValueError, match="hash"):
        create(directory, guide)
    assert not (directory / VERSIONED_KIT).exists()
