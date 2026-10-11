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


@pytest.mark.parametrize(
    "copper_kind,x_mm",
    [
        ("segment", "19.175"),  # Pad 1 at source; both track endpoints outside the pad.
        ("segment", "21.825"),  # Pad 2 at destination; source pads have no overlap.
        ("arc", "19.175"),  # Native arc intersects the source pad, not its endpoints.
        ("via", "21.825"),  # Native via at destination can create a new electrical join.
    ],
)
def test_existing_copper_overlaps_source_or_destination_pad_are_blocked(
    tmp_path: Path, copper_kind: str, x_mm: str
) -> None:
    """Native KiCad geometry guards contact, not only endpoint-in-pad cases."""
    board = tmp_path / "original" / "native-copper.kicad_pcb"
    board.parent.mkdir()
    script = """
import pcbnew as p
import sys
board = p.LoadBoard(sys.argv[1])
kind = sys.argv[3]
x = p.FromMM(float(sys.argv[4]))
pos = lambda y: p.VECTOR2I(x, p.FromMM(y))
if kind == "via":
    item = p.PCB_VIA(board)
    item.SetPosition(pos(20.5))
    item.SetWidth(p.FromMM(0.6))
    item.SetDrill(p.FromMM(0.3))
    item.SetLayerPair(p.F_Cu, p.B_Cu)
else:
    item = p.PCB_ARC(board) if kind == "arc" else p.PCB_TRACK(board)
    item.SetStart(pos(18))
    item.SetEnd(pos(22))
    if kind == "arc":
        item.SetMid(p.VECTOR2I(x + p.FromMM(0.5), p.FromMM(20)))
    item.SetWidth(p.FromMM(0.25))
    item.SetLayer(p.F_Cu)
board.Add(item)
p.SaveBoard(sys.argv[2], board)
"""
    native = subprocess.run(
        ["/usr/bin/python3", "-B", "-c", script, str(CLEAN), str(board), copper_kind, x_mm],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert native.returncode == 0, native.stderr
    original_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    output = tmp_path / "must-block-pad-copper"
    result = run_eco(board, output)
    assert result.returncode == 2, result.stderr + result.stdout
    assert "pad-adjacent copper" in result.stderr
    assert not output.exists()
    assert hashlib.sha256(board.read_bytes()).hexdigest() == original_sha


def test_project_drc_sidecar_is_preserved_and_hashed(tmp_path: Path) -> None:
    """Matching KiCad .pro settings must survive BOTH native DRC runs."""
    source = tmp_path / "input"
    source.mkdir()
    pcb = source / "native.kicad_pcb"
    pcb.write_bytes(CLEAN.read_bytes())
    project = pcb.with_suffix(".kicad_pro")
    project.write_bytes((SOURCE / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes())
    original = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (pcb, project)}
    result = run_eco(pcb, tmp_path / "context-preserved")
    assert result.returncode == 0, result.stderr + result.stdout
    output = tmp_path / "context-preserved"
    evidence = json.loads((output / "ECO_EVIDENCE.json").read_text())
    assert evidence["rule_context"] == {
        "mode": "project",
        "project_sha256": original[project],
        "custom_rules_sha256": None,
        "effective_rules_independently_verified": False,
    }
    for path in (pcb, project):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original[path]
    assert (output / "source.kicad_pro").read_bytes() == project.read_bytes()


def test_custom_drc_rules_without_matching_project_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    pcb = source / "native.kicad_pcb"
    pcb.write_bytes(CLEAN.read_bytes())
    rules = pcb.with_suffix(".kicad_dru")
    rules.write_text("(version 1)\n")
    result = run_eco(pcb, tmp_path / "must-block-unpaired-rules")
    assert result.returncode == 2 and "without their project context" in result.stderr
    assert not (tmp_path / "must-block-unpaired-rules").exists()
    assert pcb.read_bytes() == CLEAN.read_bytes()


def test_symlinked_kicad_project_context_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    pcb = source / "native.kicad_pcb"
    pcb.write_bytes(CLEAN.read_bytes())
    pcb.with_suffix(".kicad_pro").symlink_to(SOURCE / "tests/fixtures/kicad_project/top.kicad_pro")
    result = run_eco(pcb, tmp_path / "must-block-external-rule-link")
    assert result.returncode == 2 and "sidecar is not a regular file" in result.stderr
    assert not (tmp_path / "must-block-external-rule-link").exists()


def test_kicad_rejects_invalid_custom_rules_instead_of_defaulting(tmp_path: Path) -> None:
    source = tmp_path / "input"
    source.mkdir()
    pcb = source / "native.kicad_pcb"
    pcb.write_bytes(CLEAN.read_bytes())
    pcb.with_suffix(".kicad_pro").write_bytes((SOURCE / "tests/fixtures/kicad_project/top.kicad_pro").read_bytes())
    pcb.with_suffix(".kicad_dru").write_text("(version 1)\n(rule broken (constraint clearance (min INVALID)))\n")
    result = run_eco(pcb, tmp_path / "no-silent-rule-fallback")
    assert result.returncode == 2, result.stderr + result.stdout
    assert "KiCad" in result.stderr
    assert not (tmp_path / "no-silent-rule-fallback").exists()


def test_unrelated_copper_arc_outside_footprint_still_allows_evidence(tmp_path: Path) -> None:
    """The guard is localized: harmless copper elsewhere is not banned globally."""
    original = tmp_path / "input"
    original.mkdir()
    pcb = original / "unrelated-arc.kicad_pcb"
    make = subprocess.run(
        [
            "/usr/bin/python3",
            "-B",
            "-c",
            """
import pcbnew as p,sys
b=p.LoadBoard(sys.argv[1])
a=p.PCB_ARC(b)
a.SetStart(p.VECTOR2I(p.FromMM(28),p.FromMM(17)))
a.SetMid(p.VECTOR2I(p.FromMM(29),p.FromMM(20)))
a.SetEnd(p.VECTOR2I(p.FromMM(28),p.FromMM(23)))
a.SetWidth(p.FromMM(.25))
a.SetLayer(p.F_Cu)
b.Add(a)
p.SaveBoard(sys.argv[2],b)
""",
            str(CLEAN),
            str(pcb),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert make.returncode == 0, make.stderr
    sha_before = hashlib.sha256(pcb.read_bytes()).hexdigest()
    target = tmp_path / "safe-unrelated-arc"
    result = run_eco(pcb, target)
    assert result.returncode == 0, result.stderr + result.stdout
    assert (target / "source.kicad_pcb").is_file()
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == sha_before
