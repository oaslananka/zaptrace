"""Release candidate audit manifest: real bundled bytes and honest GA blockers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from review_studio_build_deb import build  # noqa: E402
from review_studio_release_manifest import manifest, sha256  # noqa: E402


@pytest.fixture(scope="module")
def release_artifact(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build(SCRIPTS.parent, tmp_path_factory.mktemp("review-audit-packages"))


def gate_log(tmp_path: Path) -> Path:
    path = tmp_path / "release.log"
    path.write_text(
        "\n".join([f"[{i}/9] verified" for i in range(1, 10)])
        + "\n0 errors, 0 warnings, 0 informations\nRELEASE GATE: PASS (local unsigned)\n"
    )
    return path


def test_audit_lists_real_files_and_always_discloses_unsigned_and_not_ga(
    release_artifact: Path,
    tmp_path: Path,
) -> None:
    report = manifest(release_artifact, gate_log(tmp_path))
    assert report["version"] == "0.1.5"
    assert report["package"]["sha256"] == sha256(release_artifact)
    assert report["target"]["native_kicad"] == "10.x"
    assert report["validation"]["nine_stage_release_gate"]
    assert report["validation"]["code_signed"] is False
    assert report["validation"]["independent_clean_machine_real_apt_install"] is False
    assert report["validation"]["fabrication_approved"] is False
    assert "NOT public GA" in report["status"]
    assert len(report["bundled_files"]) >= 12
    assert any(item["path"].endswith("review_studio_library.py") for item in report["bundled_files"])
    assert not any(item["path"].endswith(".kicad_pcb") for item in report["bundled_files"])
    assert not any("/home/" in item["path"] for item in report["bundled_files"])


def test_audit_blocks_mismatched_sha_or_incomplete_release_gate(
    release_artifact: Path,
    tmp_path: Path,
) -> None:
    log = tmp_path / "bad.log"
    log.write_text("RELEASE GATE: PASS\n0 errors, 0 warnings, 0 informations")
    with pytest.raises(ValueError, match="nine-stage"):
        manifest(release_artifact, log)
    proper = gate_log(tmp_path)
    clone = tmp_path / release_artifact.name
    clone.write_bytes(release_artifact.read_bytes())
    clone.with_suffix(".sha256").write_text("0" * 64 + "  " + clone.name + "\n")
    with pytest.raises(ValueError, match="checksum"):
        manifest(clone, proper)


def test_clean_container_qa_is_accepted_only_for_identical_tested_package(
    release_artifact: Path,
    tmp_path: Path,
) -> None:
    log = gate_log(tmp_path)
    qa = tmp_path / "clean-ubuntu-qa.txt"
    accepted = (
        "PACKAGE_SHA256=" + sha256(release_artifact) + "\n"
        "Actual APT update=0; apt-get install zaptrace-review-studio 0.1.1 = 0\n"
        "Real APT in-place upgrade to installed 0.1.5 passed\n"
        "Installed 0.1.5 native KiCad 8 orbit and 2 fixed OpenGL camera views: PASS\n"
        "Legacy 0.1.1 private ZIP restore: approved by source SHA\n"
        "Native localhost startup/shutdown after upgrade passed\n"
        "Actual APT remove 0.1.5 passed\n"
    )
    qa.write_text(accepted)
    good = manifest(release_artifact, log, qa)
    assert good["validation"]["clean_ubuntu_disposable_container_real_apt_install"] is True
    assert good["validation"]["clean_ubuntu_container_native_erc_drc"] is True
    assert good["validation"]["clean_ubuntu_container_native_3d_isometric_and_top"] is True
    assert good["validation"]["clean_ubuntu_container_native_3d_eight_camera_orbit_frames"] is True
    assert good["validation"]["native_3d_model_coverage_independently_verified"] is False
    assert good["validation"]["clean_ubuntu_container_apt_remove_preserves_user_data"] is True
    assert good["validation"]["clean_ubuntu_container_inplace_011_to_015_upgrade"] is True
    assert good["validation"]["clean_ubuntu_container_legacy_zip_restored_using_fresh_kicad"] is True
    assert good["validation"]["independent_clean_machine_real_apt_install"] is False
    assert good["validation"]["code_signed"] is False
    assert good["validation"]["fabrication_approved"] is False
    qa.write_text(accepted.replace(sha256(release_artifact), "0" * 64))
    with pytest.raises(ValueError, match="Container|QA"):
        manifest(release_artifact, log, qa)
