"""Outside-in: native KiCad 10 DRC delta prevents a newly shorted original PCB."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.kicad.pcb_drc_review import _delta_fingerprints, review_native_pcb_drc_delta

SOURCE = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"


def _original():
    board = next(SOURCE.glob("*.kicad_pcb"))
    return board, board.with_suffix(".kicad_pro")


def _candidate(tmp_path: Path, *, wrong_net: bool = False) -> Path:
    board, _ = _original()
    candidate = tmp_path / board.name
    raw = board.read_bytes()
    if wrong_net:
        source = raw.decode()
        start_ref = source.index('(property "Reference" "R4"')
        pad_start = source.index('(pad "2"', start_ref)
        original = '(net 45 "Net-(D1-A)")'
        pos = source.index(original, pad_start)
        source = source[:pos] + '(net 3 "+5V")' + source[pos + len(original) :]
        raw = source.encode()
    candidate.write_bytes(raw)
    return candidate


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _review(candidate: Path):
    board, project = _original()
    return review_native_pcb_drc_delta(
        board,
        candidate,
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(candidate),
        expected_project_sha256=_hash(project),
    )


@pytest.fixture
def native_kicad_10():
    cli_path = shutil.which("kicad-cli")
    if cli_path is None:
        pytest.skip("independent native KiCad 10 PCB DRC requires kicad-cli")
    version = subprocess.run([cli_path, "version"], capture_output=True, text=True, timeout=15)
    if version.returncode or not version.stdout.startswith("10."):
        pytest.skip("native KiCad 10 only")
    return cli_path


def test_same_original_real_board_reports_unchanged_drc_not_fabrication_approval(
    tmp_path: Path, native_kicad_10
) -> None:
    board, project = _original()
    original_hash, project_hash = _hash(board), _hash(project)
    candidate = _candidate(tmp_path)
    result = _review(candidate)
    assert result.native_kicad_version.startswith("10.")
    assert result.new_violations == 0
    assert result.new_unconnected_items == 0
    assert result.no_drc_regression
    assert result.baseline_violations == result.candidate_violations == 30
    assert result.baseline_unconnected_items == result.candidate_unconnected_items == 0
    assert result.baseline_drc_clean is False
    assert result.candidate_drc_clean is False
    assert result.manufacturing_approved is False
    assert result.to_dict()["original_files_modified"] is False
    assert board.read_bytes() == candidate.read_bytes()
    assert _hash(board) == original_hash and _hash(project) == project_hash


def test_real_wrong_copper_net_native_drc_detects_short_and_new_unconnected(tmp_path: Path, native_kicad_10) -> None:
    board, project = _original()
    original_hash, project_hash = _hash(board), _hash(project)
    changed = _candidate(tmp_path, wrong_net=True)
    candidate_hash = _hash(changed)
    result = _review(changed)
    assert result.native_kicad_version.startswith("10.")
    assert result.baseline_violations == 30
    assert result.candidate_violations == 34
    assert result.new_violations >= 4
    assert result.new_violation_types["shorting_items"] == 2
    assert result.new_violation_types["solder_mask_bridge"] == 2
    assert result.new_unconnected_items == 1
    assert not result.no_drc_regression
    assert not result.manufacturing_approved
    assert result.to_dict()["candidate_sha256"] == candidate_hash
    assert _hash(board) == original_hash and _hash(project) == project_hash
    assert _hash(changed) == candidate_hash


def test_fingerprints_ignore_date_order_but_keep_distinct_duplicate_native_findings() -> None:
    base = [
        {
            "type": "shorting_items",
            "severity": "error",
            "description": "Short",
            "items": [
                {"uuid": "aaa", "pos": {"x": 1.0, "y": 2.0}},
                {"uuid": "bbb", "pos": {"x": 3.0, "y": 4.0}},
            ],
        },
    ]
    same = [
        {
            "description": "Short",
            "severity": "error",
            "type": "shorting_items",
            "items": list(reversed(base[0]["items"])),
        }
    ]
    added, removed = _delta_fingerprints(base, same)
    assert not added and not removed
    added, removed = _delta_fingerprints(base, base + base)
    assert len(added) == 1 and not removed
    assert added[0]["type"] == "shorting_items"


def test_rejects_stale_source_or_candidate_or_project_digest(tmp_path: Path) -> None:
    board, project = _original()
    candidate = _candidate(tmp_path)
    arguments = dict(
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(candidate),
        expected_project_sha256=_hash(project),
    )
    for field in arguments:
        invalid = dict(arguments)
        invalid[field] = "0" * 64
        with pytest.raises(ValueError, match="SHA-256"):
            review_native_pcb_drc_delta(board, candidate, **invalid)


def test_rejects_missing_original_project_or_non_board_source(tmp_path: Path) -> None:
    board, _ = _original()
    missing = tmp_path / "no-project.kicad_pcb"
    missing.write_bytes(board.read_bytes())
    with pytest.raises(ValueError, match=".kicad_pro"):
        review_native_pcb_drc_delta(
            missing,
            missing,
            expected_original_sha256=_hash(missing),
            expected_candidate_sha256=_hash(missing),
            expected_project_sha256="0" * 64,
        )


def test_cli_help_exposes_single_command_original_candidate_and_json() -> None:
    result = CliRunner().invoke(cli, ["kicad", "pcb-drc-delta", "--help"])
    assert result.exit_code == 0, result.output
    assert "ORIGINAL" in result.output and "CANDIDATE" in result.output
    assert "--json" in result.output


def test_cli_native_bad_candidate_returns_machine_readable_failure_and_never_writes_source(
    tmp_path: Path, native_kicad_10
) -> None:
    board, project = _original()
    board_sha, project_sha = _hash(board), _hash(project)
    candidate = _candidate(tmp_path, wrong_net=True)
    output = CliRunner().invoke(cli, ["kicad", "pcb-drc-delta", str(board), str(candidate), "--json"])
    assert output.exit_code == 2, output.output
    report = json.loads(output.output)
    assert report["new_violation_types"]["shorting_items"] >= 1
    assert report["new_unconnected_items"] == 1
    assert report["no_drc_regression"] is False
    assert report["manufacturing_approved"] is False
    assert _hash(board) == board_sha and _hash(project) == project_sha


def test_no_native_kicad_binary_fails_closed_instead_of_guessing(tmp_path: Path, monkeypatch) -> None:
    from zaptrace.kicad import pcb_drc_review

    candidate = _candidate(tmp_path)
    board, project = _original()
    monkeypatch.setattr(pcb_drc_review.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="Native KiCad 10 CLI is required"):
        pcb_drc_review.review_native_pcb_drc_delta(
            board,
            candidate,
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(candidate),
            expected_project_sha256=_hash(project),
        )


def test_non_kicad_candidate_is_rejected_before_any_native_process(tmp_path: Path) -> None:
    board, project = _original()
    wrong_extension = tmp_path / "candidate.txt"
    wrong_extension.write_bytes(board.read_bytes())
    with pytest.raises(ValueError, match=".kicad_pcb"):
        review_native_pcb_drc_delta(
            board,
            wrong_extension,
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(wrong_extension),
            expected_project_sha256=_hash(project),
        )
