"""Real KiCad 10 PCB experiment: four grounded S1 pads require physical copper."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ai_native_candidate_pilot import write_local_candidate

INTENT = "USB-C powered STM32 MCU board, 3.3V rail at 100 mA, I2C temperature sensor"
NATIVE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ai_native_pilot_shield_pcb_oracle.py"


@pytest.mark.skipif(
    not (Path("/usr/bin/python3").exists() and shutil.which("kicad-cli")),
    reason="Native KiCad 10 Python and CLI are required",
)
def test_native_s1_same_net_is_unrouted_and_explicit_test_copper_is_not_fab_approved(tmp_path: Path) -> None:
    source = tmp_path / "candidate"
    write_local_candidate(INTENT, source)
    target = tmp_path / "native-test"
    result = subprocess.run(
        ["/usr/bin/python3", "-B", str(NATIVE_SCRIPT), "--candidate-dir", str(source), "--output-dir", str(target)],
        capture_output=True,
        text=True,
        timeout=150,
        check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    report = json.loads((target / "evidence.json").read_text())
    assert report["source_candidate_pcb_layout_present"] is False
    assert report["candidate_board_s1_copper_verified"] is False
    assert report["fabrication_approved"] is False
    before = report["demonstrated"]["same_net_without_tracks"]
    after = report["demonstrated"]["isolated_test_tracks_not_fabrication_layout"]
    assert before["native_unconnected_count"] == before["native_drc"]["unconnected_items"] == 3
    assert after["native_unconnected_count"] == after["native_drc"]["unconnected_items"] == 0
    assert before["tracks"] == 0 and after["tracks"] == 3
    assert before["zones"] == after["zones"] == 0
    assert before["s1_positions_mm"] == after["s1_positions_mm"]
    assert len(before["physical_s1_uuids"]) == len(set(before["physical_s1_uuids"])) == 4
    assert len(after["physical_s1_uuids"]) == len(set(after["physical_s1_uuids"])) == 4
    assert before["physical_s1_uuids"] != after["physical_s1_uuids"]
    assert before["native_drc"]["other_rule_violations"] > 0
    assert after["native_drc"]["other_rule_violations"] > 0
    assert report["physical_fixture_drc"] == "blocked"
    for name, expected in report["source_sha256"].items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == expected
    assert (target / "test-track/J1-tracks.kicad_pcb").is_file()
    assert (target / "unrouted/J1-unrouted.kicad_pcb").is_file()


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="Native Python unavailable")
def test_native_shield_oracle_never_overwrites_existing_output_or_uses_modified_source(tmp_path: Path) -> None:
    source = tmp_path / "candidate"
    write_local_candidate(INTENT, source)
    target = tmp_path / "existing"
    target.mkdir()
    (target / "important").write_text("KEEP")
    command = [
        "/usr/bin/python3",
        "-B",
        str(NATIVE_SCRIPT),
        "--candidate-dir",
        str(source),
        "--output-dir",
        str(target),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert (target / "important").read_text() == "KEEP"
    (source / "design.json").write_text('{"tampered":true}')
    result = subprocess.run(
        command[:-1] + [str(tmp_path / "never-created")], capture_output=True, text=True, timeout=30, check=False
    )
    assert result.returncode != 0
    assert not (tmp_path / "never-created").exists()


@pytest.mark.skipif(not Path("/usr/bin/python3").exists(), reason="Native Python unavailable")
def test_native_fixture_rejects_reshaped_source_even_if_attacker_rewrites_manifest(tmp_path: Path) -> None:
    source = tmp_path / "candidate"
    write_local_candidate(INTENT, source)
    design = json.loads((source / "design.json").read_text())
    s1 = next(pad for pad in design["components"]["J1"]["footprint_def"]["pads"] if pad["id"] == "S1")
    s1["position"][0] += 1.5
    new_bytes = (json.dumps(design, sort_keys=True) + "\n").encode()
    (source / "design.json").write_bytes(new_bytes)
    manifest = json.loads((source / "manifest.json").read_text())
    manifest["files_sha256"]["design.json"] = hashlib.sha256(new_bytes).hexdigest()
    (source / "manifest.json").write_text(json.dumps(manifest))
    destination = tmp_path / "not-created"
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(NATIVE_SCRIPT),
            "--candidate-dir",
            str(source),
            "--output-dir",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    assert result.returncode != 0
    assert "differs from pinned native GCT" in result.stderr
    assert not destination.exists()
