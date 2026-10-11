"""Real KiCad 10 PCB layout authoring: strict native geometry/DRC gate."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE / "scripts/review_studio_pcb_eco.py"
CLEAN = SOURCE / "tests/fixtures/review_studio_native_eco_placement.kicad_pcb"
COPPER = SOURCE / "build/source-reference-readonly/ESP32_actual_copper_review.kicad_pcb"


def run_eco(
    board: Path, folder: Path, ref: str = "R1", dx: str = "1", dy: str = "0.5"
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            str(SCRIPT),
            "--board",
            str(board),
            "--output",
            str(folder),
            "--ref",
            ref,
            f"--dx={dx}",
            f"--dy={dy}",
        ],
        text=True,
        capture_output=True,
        timeout=115,
        check=False,
    )


def test_actual_kicad_10_board_footprint_move_is_drc_clean_and_copy_only(tmp_path: Path) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 CLI needed")
    input_dir = tmp_path / "original"
    input_dir.mkdir()
    board = input_dir / "sensor.kicad_pcb"
    board.write_bytes(CLEAN.read_bytes())
    original_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    target = tmp_path / "eco-move"
    run = run_eco(board, target)
    assert run.returncode == 0, run.stderr[-1700:]
    evidence = json.loads((target / "ECO_EVIDENCE.json").read_text())
    assert evidence["ref"] == "R1"
    assert evidence["old_mm"] == [20.0, 20.0]
    assert evidence["new_mm"] == [21.0, 20.5]
    assert evidence["source_sha256"] == original_sha == hashlib.sha256(board.read_bytes()).hexdigest()
    assert evidence["working_sha256"] == hashlib.sha256((target / "source.kicad_pcb").read_bytes()).hexdigest()
    assert evidence["native_drc"] == {
        "before_rules": 0,
        "after_rules": 0,
        "before_open": 0,
        "after_open": 0,
        "new_drc_rules": 0,
        "active_rules_unchanged": True,
    }
    assert not evidence["fabApproved"] and not evidence["electricallyApproved"]
    preview = (target / "PREVIEW.html").read_text()
    assert preview.count("data:image/svg+xml;base64,") == 2
    assert "Native KiCad PCB" in preview and "NOT FABRICATION APPROVED" in preview
    assert "frameBefore" in preview and "frameAfter" in preview
    assert board.read_bytes() == CLEAN.read_bytes()
    again = run_eco(board, target, dx="-1")
    assert again.returncode == 2 and "PCB ECO BLOCKED" in again.stderr
    assert board.read_bytes() == CLEAN.read_bytes()


@pytest.mark.parametrize(
    "ref,dx,dy",
    [
        ("R0", "1", "0"),
        ("R99", "1", "0"),
        ("R1", "0", "0"),
        ("R1", "6", "0"),
        ("R1", "0.001", "0"),
        ("R1", "nan", "0"),
        ("R1", "0", "-inf"),
        ("R1", "-5.01", "1"),
        ("R1;echo", "1", "0"),
    ],
)
def test_invalid_footprint_edits_fail_closed(tmp_path: Path, ref: str, dx: str, dy: str) -> None:
    dest = tmp_path / "reject"
    result = run_eco(CLEAN, dest, ref, dx, dy)
    assert result.returncode == 2 and "PCB ECO BLOCKED" in result.stderr
    assert not dest.exists()


def test_existing_real_routed_sensor_footprint_move_is_rejected(tmp_path: Path) -> None:
    if not COPPER.exists():
        pytest.skip("Actual native copper fixture unavailable")
    before = hashlib.sha256(COPPER.read_bytes()).hexdigest()
    result = run_eco(COPPER, tmp_path / "bad-copper-move", ref="R1")
    assert result.returncode == 2
    assert "drag routing" in result.stderr
    assert not (tmp_path / "bad-copper-move").exists()
    assert hashlib.sha256(COPPER.read_bytes()).hexdigest() == before


def test_introduced_real_clearance_drc_error_never_writes_output(tmp_path: Path) -> None:
    if not shutil.which("kicad-cli"):
        pytest.skip("Native KiCad 10 CLI needed")
    # Move R1 +5 mm from 20mm into the R2 courtyard after selecting a closer
    # footprint, preserving independent KiCad project/part ownership.
    board = tmp_path / "original" / "candidate.kicad_pcb"
    board.parent.mkdir()
    make = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """
import pcbnew as p,sys
b=p.LoadBoard(sys.argv[1]);f=next(x for x in b.GetFootprints() if x.GetReference()=="R2")
f.SetPosition(p.VECTOR2I(p.FromMM(25),p.FromMM(20)))
p.SaveBoard(sys.argv[2],b)
""",
            str(CLEAN),
            str(board),
        ],
        check=True,
        capture_output=True,
        timeout=15,
    )
    assert make.returncode == 0
    sha = hashlib.sha256(board.read_bytes()).hexdigest()
    output = tmp_path / "must-block"
    run = run_eco(board, output, dx="5", dy="0")
    assert run.returncode == 2, run.stdout + run.stderr[-2000:]
    assert "DRC" in run.stderr
    assert not output.exists()
    assert hashlib.sha256(board.read_bytes()).hexdigest() == sha


def test_output_inside_original_directory_is_rejected(tmp_path: Path) -> None:
    board = tmp_path / "source.kicad_pcb"
    board.write_bytes(CLEAN.read_bytes())
    run = run_eco(board, tmp_path / "not-allowed-in-source")
    assert run.returncode == 2 and not (tmp_path / "not-allowed-in-source").exists()
