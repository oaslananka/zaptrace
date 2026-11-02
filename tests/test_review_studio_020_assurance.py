"""Deterministic 0.1.20 package- and source-hash-bound non-release QA kit."""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from review_studio_020_assurance_kit import REQUIRED, ZIP_NAME, create  # noqa: E402
from review_studio_build_deb import build  # noqa: E402


def synthetic_mobile_png(width: int = 390, height: int = 844) -> bytes:
    def chunk(name: bytes, contents: bytes) -> bytes:
        return struct.pack(">I", len(contents)) + name + contents + struct.pack(">I", zlib.crc32(name + contents))

    raw = b"".join(b"\x00" + b"\x13\x36\x59" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def acceptance(tmp_path: Path) -> tuple[Path, Path]:
    dest = tmp_path / "distribution"
    evidence = tmp_path / "acceptance"
    evidence.mkdir()
    package = build(ROOT, dest, version="0.1.20")
    reproduction = dest / "repro-020"
    reproduction.mkdir()
    (reproduction / package.name).write_bytes(package.read_bytes())
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    visual = synthetic_mobile_png()
    (evidence / "native-3d-model-diagnostics-390.png").write_bytes(visual)
    visual_sha = hashlib.sha256(visual).hexdigest()
    narrow = synthetic_mobile_png(320, 780)
    (evidence / "native-3d-model-diagnostics-320.png").write_bytes(narrow)
    narrow_sha = hashlib.sha256(narrow).hexdigest()
    for width, height in ((320, 844), (390, 844)):
        asset = synthetic_mobile_png(width, height)
        (evidence / f"native-multisheet-child-{width}.png").write_bytes(asset)
        (evidence / f"triage-{width}.png").write_bytes(asset)
    for name, markers in REQUIRED.items():
        text = "\n".join(markers)
        if name == "viewer-modes-020":
            text += f"\nMOBILE_3D_PROOF_SHA256={visual_sha}"
            text += f"\nMOBILE_3D_320_PROOF_SHA256={narrow_sha}"
            for width in (320, 390):
                asset = (evidence / f"native-multisheet-child-{width}.png").read_bytes()
                text += f"\nMOBILE_SCHEMATIC_{width}_SHA256={hashlib.sha256(asset).hexdigest()}"
                text += f"\nTRIAGE_SCREEN_{width}_SHA256={hashlib.sha256(asset).hexdigest()}"
        text += f"\nPACKAGE_SHA256={digest}\n"
        (evidence / f"{name}.log").write_text(text)
        (evidence / f"{name}.exit").write_text("0\n")
    canonical = ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    models = {
        "source_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
        "model_assets": {"model_geometry_approved": False, "present_files": 10, "declared_references": 12},
    }
    (evidence / "model-availability-020.json").write_text(json.dumps(models))
    return dest, evidence


def test_020_kit_is_deterministic_source_bound_and_never_certifies_hardware(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    output = create(dist, qa)
    original = output.read_bytes()
    assert create(dist, qa).read_bytes() == original
    assert output.name == ZIP_NAME
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 5
        assert not any(name.endswith((".kicad_sch", ".kicad_pcb", ".kicad_pro")) for name in archive.namelist())
        manifest = json.loads(archive.read("ACCEPTANCE_020.json"))
        assert manifest["version"] == "0.1.20"
        assert set(manifest["mobile_triage_screenshots_sha256"]) == {"320", "390"}
        expected_package_sha256 = hashlib.sha256(archive.read("zaptrace-review-studio_0.1.20_all.deb")).hexdigest()
        assert (
            archive.read("zaptrace-review-studio_0.1.20_all.deb")
            == (dist / "zaptrace-review-studio_0.1.20_all.deb").read_bytes()
        )
        assert manifest["package"]["sha256"] == expected_package_sha256
        assert manifest["package"]["sha256"] != manifest["mobile_native_schematic_screenshots_sha256"]["390"]
        assert expected_package_sha256 in archive.read("LOCAL_QA_AND_LIMITATIONS.md").decode("utf-8")
        assert all(value["pass"] for value in manifest["validation"].values())
        for status in (
            "public_release",
            "fabrication_approved",
            "code_signed",
            "three_d_model_geometry_approved",
            "full_bi_directional_schematic_pcb_sync_proven",
            "independent_clean_physical_host_tested",
        ):
            assert manifest[status] is False


def test_020_kit_rejects_unchecked_qas_and_tampered_source_or_deb(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    (qa / "viewer-modes-020.exit").write_text("1\n")
    with pytest.raises(ValueError, match="Missing completed"):
        create(dist, qa)
    (qa / "viewer-modes-020.exit").write_text("0\n")
    report = qa / "model-availability-020.json"
    model = json.loads(report.read_text())
    model["source_sha256"] = "0" * 64
    report.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="original KiCad"):
        create(dist, qa)
    model["source_sha256"] = hashlib.sha256(
        (ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb").read_bytes()
    ).hexdigest()
    report.write_text(json.dumps(model))
    package = dist / "zaptrace-review-studio_0.1.20_all.deb"
    package.write_bytes(package.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        create(dist, qa)


def test_020_kit_rejects_replaced_mobile_screenshot(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    p = qa / "native-3d-model-diagnostics-390.png"
    replacement = bytearray(p.read_bytes())
    replacement[-15] ^= 1
    p.write_bytes(replacement)
    with pytest.raises(ValueError, match="visual evidence SHA"):
        create(dist, qa)


def test_020_kit_rejects_unbound_narrow_screen(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    path = qa / "native-3d-model-diagnostics-320.png"
    path.write_bytes(synthetic_mobile_png(330, 780))
    with pytest.raises(ValueError, match="320px Chrome visual proof"):
        create(dist, qa)


def test_020_kit_refuses_success_replay_from_a_different_deb(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    log = qa / "ubuntu-installed-chrome-020.log"
    log.write_text(log.read_text().replace("PACKAGE_SHA256=", "HISTORIC_SHA256="))
    with pytest.raises(ValueError, match="Package SHA proof missing"):
        create(dist, qa)


def test_020_kit_rejects_swapped_native_schematic_capture(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    p = qa / "native-multisheet-child-320.png"
    p.write_bytes(synthetic_mobile_png(321, 844))
    with pytest.raises(ValueError, match="schematic Chrome screenshot"):
        create(dist, qa)


def test_020_kit_rejects_tampered_real_triage_png(acceptance: tuple[Path, Path]) -> None:
    dest, qa = acceptance
    screenshot = qa / "triage-320.png"
    raw = bytearray(screenshot.read_bytes())
    raw[-17] ^= 1
    screenshot.write_bytes(raw)
    with pytest.raises(ValueError, match="review note screenshot SHA"):
        create(dest, qa)
