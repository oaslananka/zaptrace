"""TDD: real native KiCad 10 must see every child sheet in a read-only AI review."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.kicad.pcb_drc_review import review_native_pcb_drc_delta

SOURCE = Path(__file__).parents[1] / "benchmarks/external/atomic14-basic-esp32s3-dev-board/source"
SHEET_UUID = "11111111-2222-4333-8444-555555555555"
ROOT_UUID = "cb9cde49-491c-4637-83a4-9a90127d65a1"
CHILD_NAME = "auxiliary.kicad_sch"
WIRE = (
    "(wire (pts (xy 35.56 48.26) (xy 45.72 48.26)) "
    "(stroke (width 0) (type default)) "
    '(uuid "33333333-4444-4555-8666-777777777777"))'
)


@pytest.fixture
def ki10():
    executable = shutil.which("kicad-cli")
    if executable is None:
        pytest.skip("native KiCad CLI 10 required")
    check = subprocess.run([executable, "version"], capture_output=True, text=True, timeout=15)
    if check.returncode or not check.stdout.startswith("10."):
        pytest.skip("native KiCad 10 required")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _setup(tmp_path: Path) -> tuple[Path, Path, Path, Path, str]:
    original = tmp_path / "original"
    original.mkdir()
    for extension in ("kicad_pcb", "kicad_pro", "kicad_sch"):
        source = next(SOURCE.glob("*." + extension))
        (original / source.name).write_bytes(source.read_bytes())
    board = original / "dev-board.kicad_pcb"
    root = original / "dev-board.kicad_sch"
    sub = original / CHILD_NAME
    sheet = (
        "(sheet (at 100 30) (size 60 30) "
        "(exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no) "
        "(stroke (width 0) (type default)) (fill (color 0 0 0 0.0000)) "
        f'(uuid "{SHEET_UUID}") '
        '(property "Sheetname" "Auxiliary" (at 100 29 0) '
        "(effects (font (size 1.27 1.27)) (justify left bottom))) "
        f'(property "Sheetfile" "{CHILD_NAME}" (at 100 61 0) '
        "(effects (font (size 1.27 1.27)) (justify left top))) "
        f'(instances (project "dev-board" (path "/{ROOT_UUID}" (page "2")))))'
    )
    root.write_text(root.read_text().replace("(sheet_instances", sheet + "\n(sheet_instances", 1))
    original_child = (
        '(kicad_sch (version 20250114) (generator "zaptrace") '
        '(uuid "22222222-3333-4444-8555-666666666666") '
        '(paper "A4") (lib_symbols) (embedded_fonts no))'
    )
    sub.write_text(original_child)
    return board, root, sub, board.with_suffix(".kicad_pro"), original_child


def _review(board: Path, root: Path, *, candidate_child: Path | None = None):
    candidate = board.parent.parent / "candidate.kicad_pcb"
    candidate.write_bytes(board.read_bytes())
    replacements = {CHILD_NAME: candidate_child} if candidate_child is not None else None
    checksums = {CHILD_NAME: _hash(candidate_child)} if candidate_child is not None else None
    return review_native_pcb_drc_delta(
        board,
        candidate,
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(candidate),
        expected_project_sha256=_hash(board.with_suffix(".kicad_pro")),
        include_electrical_checks=True,
        expected_original_schematic_sha256=_hash(root),
        candidate_child_sheets=replacements,
        expected_candidate_child_sha256=checksums,
    )


def test_real_native_original_child_is_included_in_erc_and_hash_manifest(tmp_path: Path, ki10) -> None:
    board, root, child, project, _ = _setup(tmp_path)
    hashes_before = {p: _hash(p) for p in (board, root, child, project)}
    review = _review(board, root)
    evidence = review.to_dict()["electrical_review"]
    assert review.native_kicad_version.startswith("10.")
    assert evidence["sheet_file_count"] == 2
    assert evidence["baseline_erc_violations"] == 76
    assert evidence["candidate_erc_violations"] == 76
    assert evidence["new_schematic_parity_issues"] == 0
    assert evidence["original_child_sha256"][CHILD_NAME] == _hash(child)
    assert evidence["candidate_child_sha256"][CHILD_NAME] == _hash(child)
    assert review.no_review_regression
    assert review.manufacturing_approved is False
    assert hashes_before == {p: _hash(p) for p in hashes_before}


def test_real_native_modified_child_only_is_rejected_by_erc_without_pcb_change(tmp_path: Path, ki10) -> None:
    board, root, child, project, original_child = _setup(tmp_path)
    hashes_before = {p: _hash(p) for p in (board, root, child, project)}
    modified = tmp_path / "proposed-child.kicad_sch"
    modified.write_text(original_child[:-1] + " " + WIRE + ")")
    review = _review(board, root, candidate_child=modified)
    evidence = review.to_dict()["electrical_review"]
    assert review.no_drc_regression
    assert not review.no_review_regression
    assert evidence["baseline_erc_violations"] == 76
    assert evidence["new_erc_violations"] >= 1
    assert evidence["original_child_sha256"][CHILD_NAME] == _hash(child)
    assert evidence["candidate_child_sha256"][CHILD_NAME] == _hash(modified)
    assert review.to_dict()["manufacturing_approved"] is False
    assert hashes_before == {p: _hash(p) for p in hashes_before}


def test_cli_modified_child_exits_two_and_returns_source_manifest(tmp_path: Path, ki10) -> None:
    board, root, child, project, original_child = _setup(tmp_path)
    candidate_board = tmp_path / "changed.kicad_pcb"
    candidate_board.write_bytes(board.read_bytes())
    modified = tmp_path / "proposed-child.kicad_sch"
    modified.write_text(original_child[:-1] + " " + WIRE + ")")
    answer = CliRunner().invoke(
        cli,
        [
            "kicad",
            "pcb-drc-delta",
            str(board),
            str(candidate_board),
            "--electrical-checks",
            "--candidate-child-sheet",
            f"{CHILD_NAME}={modified}",
            "--json",
        ],
    )
    assert answer.exit_code == 2, answer.output
    evidence = json.loads(answer.output)["electrical_review"]
    assert evidence["new_erc_violations"] >= 1
    assert evidence["sheet_file_count"] == 2


def test_missing_or_escape_child_is_rejected_before_any_partial_native_evidence(tmp_path: Path) -> None:
    board, root, child, _, _ = _setup(tmp_path)
    child.unlink()
    with pytest.raises(ValueError, match="Missing|missing"):
        _review(board, root)
    root.write_text(root.read_text().replace(CHILD_NAME, "../../outside.kicad_sch", 1))
    with pytest.raises(ValueError, match="sheet|Sheet|path"):
        _review(board, root)


def test_child_candidate_hash_and_sheet_topology_fail_closed(tmp_path: Path) -> None:
    board, root, child, project, original_child = _setup(tmp_path)
    changed = tmp_path / "replacement.kicad_sch"
    changed.write_text(original_child)
    candidate_board = tmp_path / "candidate.kicad_pcb"
    candidate_board.write_bytes(board.read_bytes())
    with pytest.raises(ValueError, match="SHA-256"):
        review_native_pcb_drc_delta(
            board,
            candidate_board,
            candidate_child_sheets={CHILD_NAME: changed},
            expected_candidate_child_sha256={CHILD_NAME: "0" * 64},
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(candidate_board),
            expected_project_sha256=_hash(project),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_hash(root),
        )
    with pytest.raises(ValueError, match="sheet|Sheet"):
        review_native_pcb_drc_delta(
            board,
            candidate_board,
            candidate_child_sheets={"unreferenced.kicad_sch": changed},
            expected_candidate_child_sha256={"unreferenced.kicad_sch": _hash(changed)},
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(candidate_board),
            expected_project_sha256=_hash(project),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_hash(root),
        )


def test_original_drc_only_has_no_new_child_requirement(tmp_path: Path, ki10) -> None:
    board, root, child, project, _ = _setup(tmp_path)
    candidate = tmp_path / "candidate.kicad_pcb"
    candidate.write_bytes(board.read_bytes())
    result = review_native_pcb_drc_delta(
        board,
        candidate,
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(candidate),
        expected_project_sha256=_hash(project),
    )
    assert result.no_drc_regression
    assert result.electrical_review is None


@pytest.mark.parametrize(
    "unsafe",
    [
        "../escape.kicad_sch",
        "sheets/../../escape.kicad_sch",
        "/absolute.kicad_sch",
        "C:/Windows/external.kicad_sch",
        r"outside\evil.kicad_sch",
        "./same.kicad_sch",
        "nested//child.kicad_sch",
        "not-schematic.txt",
    ],
)
def test_untrusted_hierarchy_paths_fail_closed(unsafe: str) -> None:
    from zaptrace.kicad.schematic_hierarchy import sheet_relative_path

    with pytest.raises(ValueError, match="sheet|Sheet|path"):
        sheet_relative_path(unsafe)


def test_symlinked_original_child_refused_before_native_erc(tmp_path: Path) -> None:
    board, root, child, _, _ = _setup(tmp_path)
    actual_child = tmp_path / "external.kicad_sch"
    actual_child.write_bytes(child.read_bytes())
    child.unlink()
    child.symlink_to(actual_child)
    with pytest.raises(ValueError, match="symlink"):
        _review(board, root)


def test_cycle_to_original_child_detected_before_native_erc(tmp_path: Path) -> None:
    board, root, child, _, content = _setup(tmp_path)
    source = content[:-1]
    source += (
        ' (sheet (uuid "44444444-5555-4666-8777-888888888888") '
        '(property "Sheetfile" "auxiliary.kicad_sch") '
        '(property "Sheetname" "Recurse")))'
    )
    child.write_text(source)
    with pytest.raises(ValueError, match="cycle"):
        _review(board, root)


def test_candidate_topology_mutation_is_explicitly_rejected(tmp_path: Path) -> None:
    board, root, child, project, _ = _setup(tmp_path)
    candidate_board = tmp_path / "new-board.kicad_pcb"
    candidate_board.write_bytes(board.read_bytes())
    changed_root = tmp_path / "new-root.kicad_sch"
    changed_root.write_text(root.read_text().replace(SHEET_UUID, "99999999-9999-4999-8999-999999999999", 1))
    with pytest.raises(ValueError, match="topology"):
        review_native_pcb_drc_delta(
            board,
            candidate_board,
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(candidate_board),
            expected_project_sha256=_hash(project),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_hash(root),
            candidate_schematic=changed_root,
            expected_candidate_schematic_sha256=_hash(changed_root),
        )


def test_one_shared_original_child_source_is_enumerated_once_for_repeated_sheet_instances(
    tmp_path: Path,
) -> None:
    from zaptrace.kicad.schematic_hierarchy import snapshot_source_hierarchy

    _, root, child, _, _ = _setup(tmp_path)
    raw = root.read_text()
    sheet2 = (
        '(sheet (uuid "44444444-5555-4666-8777-888888888888") '
        '(property "Sheetfile" "auxiliary.kicad_sch") '
        '(property "Sheetname" "Auxiliary Again"))'
    )
    root.write_text(raw.replace("(sheet_instances", sheet2 + "\n(sheet_instances", 1))
    snapshot = snapshot_source_hierarchy(root.read_bytes(), root.parent)
    assert snapshot.file_count == 2
    assert len(snapshot.topology["<root>"]) == 2
    assert snapshot.child_sha256[CHILD_NAME] == _hash(child)
