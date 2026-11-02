"""Fail-closed immutable source and package QA gate for local 0.1.13 kit."""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from review_studio_013_assurance_kit import REQUIRED, create, digest  # noqa: E402
from review_studio_build_deb import build  # noqa: E402


@pytest.fixture
def synthetic_acceptance(tmp_path: Path) -> tuple[Path, Path]:
    distro = tmp_path / "distribution"
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    deb = build(SCRIPTS.parent, distro, version="0.1.13")
    reproduction = distro / "repro-013"
    reproduction.mkdir()
    (reproduction / deb.name).write_bytes(deb.read_bytes())
    package_sha = digest(deb.read_bytes())
    for name, required in REQUIRED.items():
        content = "\n".join(required) + f"\nPACKAGE_SHA256={package_sha}\n"
        if name == "nine-stage-source-013":
            content += "\n".join(f"[{i}/9] PASS" for i in range(1, 10))
            content += "\n0 errors, 0 warnings, 0 informations\n"
        (evidence / f"{name}.log").write_text(content)
        (evidence / f"{name}.exit").write_text("0\n")
    return distro, evidence


def test_013_candidate_local_kit_is_reproducible_unsigned_and_has_no_engineering_sources(
    synthetic_acceptance: tuple[Path, Path],
) -> None:
    distro, evidence = synthetic_acceptance
    kit = create(distro, evidence)
    previous = kit.read_bytes()
    assert create(distro, evidence).read_bytes() == previous
    with zipfile.ZipFile(kit) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 4
        assert not any(name.endswith((".kicad_pcb", ".kicad_sch", ".kicad_pro")) for name in archive.namelist())
        manifest = json.loads(archive.read("ACCEPTANCE_013.json"))
    assert manifest["fabrication_approved"] is False
    assert manifest["code_signed"] is False
    assert manifest["public_release"] is False
    assert manifest["independent_clean_physical_host_tested"] is False
    assert manifest["full_bi_directional_schematic_pcb_sync_proven"] is False
    assert all(value["result"] == "PASS" for value in manifest["validation"].values())


def test_013_candidate_rejects_missing_gate_and_mismatched_digest(
    synthetic_acceptance: tuple[Path, Path],
) -> None:
    distro, evidence = synthetic_acceptance
    (evidence / "eight-gate-exact-package.exit").write_text("1\n")
    with pytest.raises(ValueError, match="Missing successful"):
        create(distro, evidence)
    (evidence / "eight-gate-exact-package.exit").write_text("0\n")
    (distro / "zaptrace-review-studio_0.1.13_all.deb").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA"):
        create(distro, evidence)


def test_013_candidate_rejects_replay_of_earlier_release_evidence(
    synthetic_acceptance: tuple[Path, Path],
) -> None:
    distro, evidence = synthetic_acceptance
    prior = evidence / "ubuntu24-apt-upgrade-remove-013.log"
    prior.write_text(prior.read_text().replace("PACKAGE_SHA256=", "NOT_OUR_PACKAGE="))
    with pytest.raises(ValueError, match="exact candidate SHA"):
        create(distro, evidence)
