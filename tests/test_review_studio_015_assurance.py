"""Deterministic 0.1.15 package- and source-hash-bound non-release QA kit."""

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
from review_studio_015_assurance_kit import REQUIRED, ZIP_NAME, create  # noqa: E402
from review_studio_build_deb import build  # noqa: E402


def synthetic_mobile_png() -> bytes:
    def chunk(name: bytes, contents: bytes) -> bytes:
        return struct.pack(">I", len(contents)) + name + contents + struct.pack(">I", zlib.crc32(name + contents))

    raw = b"".join(b"\x00" + b"\x13\x36\x59" * 390 for _ in range(844))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 390, 844, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def acceptance(tmp_path: Path) -> tuple[Path, Path]:
    dest = tmp_path / "distribution"
    evidence = tmp_path / "acceptance"
    evidence.mkdir()
    package = build(ROOT, dest, version="0.1.15")
    reproduction = dest / "repro-015"
    reproduction.mkdir()
    (reproduction / package.name).write_bytes(package.read_bytes())
    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    visual = synthetic_mobile_png()
    (evidence / "native-3d-model-diagnostics-390.png").write_bytes(visual)
    visual_sha = hashlib.sha256(visual).hexdigest()
    for name, markers in REQUIRED.items():
        text = "\n".join(markers)
        if name == "viewer-modes-015":
            text += f"\nMOBILE_3D_PROOF_SHA256={visual_sha}"
        text += f"\nPACKAGE_SHA256={digest}\n"
        (evidence / f"{name}.log").write_text(text)
        (evidence / f"{name}.exit").write_text("0\n")
    canonical = ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"
    models = {
        "source_sha256": hashlib.sha256(canonical.read_bytes()).hexdigest(),
        "model_assets": {"model_geometry_approved": False, "present_files": 10, "declared_references": 12},
    }
    (evidence / "model-availability-015.json").write_text(json.dumps(models))
    return dest, evidence


def test_015_kit_is_deterministic_source_bound_and_never_certifies_hardware(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    output = create(dist, qa)
    original = output.read_bytes()
    assert create(dist, qa).read_bytes() == original
    assert output.name == ZIP_NAME
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist()) == 5
        assert not any(name.endswith((".kicad_sch", ".kicad_pcb", ".kicad_pro")) for name in archive.namelist())
        manifest = json.loads(archive.read("ACCEPTANCE_015.json"))
        assert manifest["version"] == "0.1.15"
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


def test_015_kit_rejects_unchecked_qas_and_tampered_source_or_deb(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    (qa / "viewer-modes-015.exit").write_text("1\n")
    with pytest.raises(ValueError, match="Missing completed"):
        create(dist, qa)
    (qa / "viewer-modes-015.exit").write_text("0\n")
    report = qa / "model-availability-015.json"
    model = json.loads(report.read_text())
    model["source_sha256"] = "0" * 64
    report.write_text(json.dumps(model))
    with pytest.raises(ValueError, match="original KiCad"):
        create(dist, qa)
    model["source_sha256"] = hashlib.sha256(
        (ROOT / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb").read_bytes()
    ).hexdigest()
    report.write_text(json.dumps(model))
    package = dist / "zaptrace-review-studio_0.1.15_all.deb"
    package.write_bytes(package.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        create(dist, qa)


def test_015_kit_rejects_replaced_mobile_screenshot(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    p = qa / "native-3d-model-diagnostics-390.png"
    replacement = bytearray(p.read_bytes())
    replacement[-15] ^= 1
    p.write_bytes(replacement)
    with pytest.raises(ValueError, match="visual evidence SHA"):
        create(dist, qa)


def test_015_kit_refuses_success_replay_from_a_different_deb(acceptance: tuple[Path, Path]) -> None:
    dist, qa = acceptance
    log = qa / "ubuntu-installed-chrome-015.log"
    log.write_text(log.read_text().replace("PACKAGE_SHA256=", "HISTORIC_SHA256="))
    with pytest.raises(ValueError, match="Package SHA proof missing"):
        create(dist, qa)
