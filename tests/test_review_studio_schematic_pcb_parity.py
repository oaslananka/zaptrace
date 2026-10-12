"""Real KiCad 10 source-only schematic-to-PCB association review; never F8."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/review_studio_schematic_pcb_parity.py"
SCH = SOURCE / "build/source-reference-readonly/ESP32_I2C_Sensor_Board.kicad_sch"
PCB = SOURCE / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def invoke(schematic: Path, board: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(SCRIPT),
            "--schematic",
            str(schematic),
            "--board",
            str(board),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=115,
        check=False,
    )


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad 10 real project fixture")
def test_actual_esp32_source_identity_differences_are_reported_not_silently_synced(tmp_path: Path) -> None:
    original = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (SCH, PCB)}
    report = tmp_path / "project-audit.json"
    run = invoke(SCH, PCB, report)
    assert run.returncode == 0, run.stderr
    finding = json.loads(report.read_text())
    assert finding["source_sha256"] == {"schematic": original[SCH], "pcb": original[PCB]}
    assert finding["component_counts"] == {"schematic": 14, "pcb": 14, "shared_references": 14}
    assert finding["schematic_net_count"] == 7
    issues = [(x["reference"], x["field"]) for x in finding["component_field_discrepancies"]]
    assert issues == [(ref, "value") for ref in ("J1", "TP1", "TP2", "U2", "U3")]
    assert finding["component_fields_match"] is False
    assert finding["repeated_pcb_pad_numbers"] is True
    assert finding["pin_net_correspondence"].startswith("not_verified_")
    assert finding["linkage_uuid_verified"] is False
    assert finding["automatic_sync_authorized"] is False
    assert finding["electricallyApproved"] is False
    assert finding["fabApproved"] is False
    assert finding["source_files_modified"] is False
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == value for p, value in original.items())
    assert report.stat().st_mode & 0o777 == 0o600
    again = invoke(SCH, PCB, report)
    assert again.returncode == 2
    assert report.read_text() == json.dumps(finding, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.skipif(not shutil.which("kicad-cli") or not PCB.exists(), reason="Native KiCad 10 real project fixture")
def test_actual_esp32_modified_pcb_value_is_reported_and_originals_protected(tmp_path: Path) -> None:
    copied = tmp_path / "source.kicad_pcb"
    original = PCB.read_bytes()
    native = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            "import pcbnew as p,sys; b=p.LoadBoard(sys.argv[1]);"
            "b.FindFootprintByReference('R1').SetValue('DANGEROUS_DIFFERENCE');p.SaveBoard(sys.argv[2],b)",
            str(PCB),
            str(copied),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    report = tmp_path / "detected.json"
    result = invoke(SCH, copied, report)
    assert result.returncode == 0, result.stderr
    findings = json.loads(report.read_text())["component_field_discrepancies"]
    assert any(
        x["reference"] == "R1" and x["field"] == "value" and x["pcb"] == "DANGEROUS_DIFFERENCE" for x in findings
    )
    assert PCB.read_bytes() == original


@pytest.mark.parametrize("invalid", ["not-a-board.kicad_pcb", "wrong-extension.txt"])
def test_invalid_native_source_fails_without_publishing(tmp_path: Path, invalid: str) -> None:
    source = tmp_path / invalid
    source.write_text("not a KiCad board" * 15)
    report = tmp_path / "must-not-exist.json"
    run = invoke(SCH, source, report)
    assert run.returncode != 0
    assert not report.exists()
