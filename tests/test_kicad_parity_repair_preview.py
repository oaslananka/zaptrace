"""Outside-in guarded KiCad reference/net alias repair: never manufacturing acceptance."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.kicad.parity_repair_preview import (
    preview_parity_repair,
    propose_source_bound_parity_board,
)

SOURCE = Path(__file__).parents[1] / "benchmarks/external/nitu-linear-regulator/source"
TESTPOINTS = [("VIN", "TP1"), ("VRAW", "TP2"), ("+5V", "TP3"), ("GND", "TP4")]
NET_RENAMES = [("Net-(D2-A)", "/LEDA")]


def _files() -> tuple[Path, Path, Path]:
    board = next(SOURCE.glob("*.kicad_pcb"))
    return board, board.with_suffix(".kicad_sch"), board.with_suffix(".kicad_pro")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _proposal(ref_map: list[tuple[str, str]] | None = None, net_map: list[tuple[str, str]] | None = None) -> bytes:
    board, schematic, _ = _files()
    return propose_source_bound_parity_board(
        board.read_bytes(),
        schematic.read_bytes(),
        reference_mappings=TESTPOINTS if ref_map is None else ref_map,
        net_mappings=NET_RENAMES if net_map is None else net_map,
        expected_sha256=_sha(board),
    )


def test_real_regulator_source_repair_matches_pinned_candidate_hash_and_keeps_original_unchanged() -> None:
    board, schematic, _ = _files()
    before = _sha(board)
    repaired = _proposal()
    assert hashlib.sha256(repaired).hexdigest() == "36dc782725714f671731c588da14a08169ffc9f5946eabecf5b8d2d944053aa9"
    assert _sha(board) == before
    assert _sha(schematic) == "8cdda7e28129ca132c29868b94d7d3339ac4d6846d7c6d51278fc40c4ede44d9"
    for alias, ref in TESTPOINTS:
        assert f'(property "Reference" "{ref}"'.encode() in repaired
        assert f'(property "Reference" "{alias}"'.encode() not in repaired
    assert repaired.count(b'(net "/LEDA")') == 3
    assert b'(net "Net-(D2-A)")' not in repaired


@pytest.mark.parametrize(
    "refs,nets,error",
    [
        ([("VIN", "TP2")], [], "schematic"),
        ([("VIN", "TP1"), ("VIN", "TP2")], [], "Duplicate"),
        ([], [("Net-(D2-A)", "GND")], "existing"),
        ([], [("unknown", "/LEDA")], "unused"),
        ([], [("Net-(D2-A)", "/unknown")], "schematic"),
        ([("D2", "TP1")], [], "test point"),
        ([], [], "mapping"),
    ],
)
def test_invalid_or_ambiguous_repair_is_rejected(
    refs: list[tuple[str, str]], nets: list[tuple[str, str]], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        _proposal(refs, nets)


def test_stale_hash_never_returns_repair_bytes() -> None:
    board, schematic, _ = _files()
    with pytest.raises(ValueError, match="SHA-256"):
        propose_source_bound_parity_board(
            board.read_bytes(),
            schematic.read_bytes(),
            reference_mappings=TESTPOINTS,
            net_mappings=NET_RENAMES,
            expected_sha256="0" * 64,
        )


@pytest.fixture
def native_kicad_10() -> str:
    binary = shutil.which("kicad-cli")
    if not binary:
        pytest.skip("Real KiCad 10 binary unavailable")
    probe = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
    if probe.returncode or not probe.stdout.startswith("10."):
        pytest.skip("Requires native KiCad 10")
    return binary


def test_real_native_kicad_parity_ten_to_zero_no_drc_erc_regression(tmp_path: Path, native_kicad_10: str) -> None:
    board, schematic, project = _files()
    before_hashes = {x.name: _sha(x) for x in (board, schematic, project)}
    output = tmp_path / "draft"
    report = preview_parity_repair(
        board,
        output,
        reference_mappings=TESTPOINTS,
        net_mappings=NET_RENAMES,
    )
    assert report["task_kind"] == "source-bound-testpoint-and-net-alias-parity-preview"
    assert report["attempt_status"] == "human-review-required"
    assert report["native_kicad_version"] == "10.0.8"
    assert report["g0_verified"] is False
    assert report["manufacturing_approved"] is False
    assert report["physical_silkscreen_review"] == "not_run"
    assert report["original_pcb_sha256"] == before_hashes[board.name]
    assert report["candidate_pcb_sha256"] == "36dc782725714f671731c588da14a08169ffc9f5946eabecf5b8d2d944053aa9"
    assert report["candidate_schematic_sha256"] == before_hashes[schematic.name]
    review = report["native_review"]
    assert review["baseline_violations"] == review["candidate_violations"] == 0
    assert review["baseline_unconnected_items"] == review["candidate_unconnected_items"] == 0
    assert review["no_review_regression"] is True
    electrical = review["electrical_review"]
    assert electrical["baseline_schematic_parity_issues"] == 10
    assert electrical["candidate_schematic_parity_issues"] == 0
    assert electrical["new_schematic_parity_issues"] == 0
    assert electrical["baseline_erc_violations"] == electrical["candidate_erc_violations"] == 0
    assert electrical["candidate_electrical_clean"] is True
    assert report["native_candidate_clean"] is True
    assert output.is_dir()
    assert _sha(output / board.name) == report["candidate_pcb_sha256"]
    assert _sha(output / schematic.name) == before_hashes[schematic.name]
    assert _sha(output / project.name) == before_hashes[project.name]
    assert json.loads((output / "parity-review.json").read_text()) == report
    assert all(_sha(x) == before_hashes[x.name] for x in (board, schematic, project))


def test_user_cli_prints_explicit_silkscreen_and_human_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    cli_module = importlib.import_module("zaptrace.cli.parity_repair_preview")
    monkeypatch.setattr(
        cli_module,
        "preview_parity_repair",
        lambda *_args, **_kwargs: {
            "native_kicad_version": "10.0.8",
            "native_review": {
                "electrical_review": {
                    "baseline_schematic_parity_issues": 10,
                    "candidate_schematic_parity_issues": 0,
                },
                "baseline_violations": 0,
                "candidate_violations": 0,
            },
        },
    )
    board, _, _ = _files()
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "parity-repair-preview",
            str(board),
            "--reference-map",
            "VIN=TP1",
            "--net-map",
            "Net-(D2-A)=/LEDA",
            "--output-dir",
            str(tmp_path / "draft"),
        ],
    )
    assert response.exit_code == 0, response.output
    assert "10" in response.output and "0" in response.output
    assert "silkscreen" in response.output.lower()
    assert "human" in response.output.lower()
    assert "NOT approved" in response.output
