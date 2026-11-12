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
    assert _hash(board) == original_hash
    assert _hash(project) == project_hash


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
    assert _hash(board) == original_hash
    assert _hash(project) == project_hash
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
    assert not added
    assert not removed
    added, removed = _delta_fingerprints(base, base + base)
    assert len(added) == 1
    assert not removed
    assert added[0]["type"] == "shorting_items"


def test_rejects_stale_source_or_candidate_or_project_digest(tmp_path: Path) -> None:
    board, project = _original()
    candidate = _candidate(tmp_path)
    for field in ("original", "candidate", "project"):
        with pytest.raises(ValueError, match="SHA-256"):
            review_native_pcb_drc_delta(
                board,
                candidate,
                expected_original_sha256="0" * 64 if field == "original" else _hash(board),
                expected_candidate_sha256="0" * 64 if field == "candidate" else _hash(candidate),
                expected_project_sha256="0" * 64 if field == "project" else _hash(project),
            )


def test_rejects_missing_original_project_or_non_board_source(tmp_path: Path) -> None:
    board, _ = _original()
    missing = tmp_path / "no-project.kicad_pcb"
    missing.write_bytes(board.read_bytes())
    source_digest = _hash(missing)
    with pytest.raises(ValueError, match="kicad_pro"):
        review_native_pcb_drc_delta(
            missing,
            missing,
            expected_original_sha256=source_digest,
            expected_candidate_sha256=source_digest,
            expected_project_sha256="0" * 64,
        )


def test_cli_help_exposes_single_command_original_candidate_and_json() -> None:
    result = CliRunner().invoke(cli, ["kicad", "pcb-drc-delta", "--help"])
    assert result.exit_code == 0, result.output
    assert "ORIGINAL" in result.output
    assert "CANDIDATE" in result.output
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
    assert _hash(board) == board_sha
    assert _hash(project) == project_sha


def test_no_native_kicad_binary_fails_closed_instead_of_guessing(tmp_path: Path, monkeypatch) -> None:
    from zaptrace.kicad import pcb_drc_review

    candidate = _candidate(tmp_path)
    board, project = _original()
    original_digest = _hash(board)
    candidate_digest = _hash(candidate)
    project_digest = _hash(project)
    from zaptrace.kicad.oracle import KiCadOracle

    monkeypatch.setattr(KiCadOracle, "_detect", lambda self: None)
    with pytest.raises(RuntimeError, match="Native KiCad 10 CLI is required"):
        pcb_drc_review.review_native_pcb_drc_delta(
            board,
            candidate,
            expected_original_sha256=original_digest,
            expected_candidate_sha256=candidate_digest,
            expected_project_sha256=project_digest,
        )


def test_non_kicad_candidate_is_rejected_before_any_native_process(tmp_path: Path) -> None:
    board, project = _original()
    wrong_extension = tmp_path / "candidate.txt"
    wrong_extension.write_bytes(board.read_bytes())
    original_digest = _hash(board)
    candidate_digest = _hash(wrong_extension)
    project_digest = _hash(project)
    with pytest.raises(ValueError, match="kicad_pcb"):
        review_native_pcb_drc_delta(
            board,
            wrong_extension,
            expected_original_sha256=original_digest,
            expected_candidate_sha256=candidate_digest,
            expected_project_sha256=project_digest,
        )


def test_native_drc_scratch_path_is_fixed_even_for_untrusted_source_filename(
    tmp_path: Path, native_kicad_10, monkeypatch
) -> None:
    """A caller-supplied board name cannot choose a scratch write path."""
    from zaptrace.kicad.oracle import KiCadOracle

    board, project = _original()
    renamed_original = tmp_path / "--unexpected-board-name.kicad_pcb"
    renamed_project = renamed_original.with_suffix(".kicad_pro")
    candidate = tmp_path / "proposed-edit.kicad_pcb"
    renamed_original.write_bytes(board.read_bytes())
    renamed_project.write_bytes(project.read_bytes())
    candidate.write_bytes(board.read_bytes())

    seen: list[Path] = []
    genuine_drc = KiCadOracle.run_drc

    def inspect_drc_path(self, board_path, **kwargs):
        path = Path(board_path)
        seen.append(path)
        assert path.name == "review.kicad_pcb"
        assert path.with_suffix(".kicad_pro").is_file()
        assert path.parent.name in {"baseline", "candidate"}
        assert path.resolve().is_relative_to(tmp_path.resolve()) is False
        return genuine_drc(self, board_path, **kwargs)

    monkeypatch.setattr(KiCadOracle, "run_drc", inspect_drc_path)
    result = review_native_pcb_drc_delta(
        renamed_original,
        candidate,
        expected_original_sha256=_hash(renamed_original),
        expected_candidate_sha256=_hash(candidate),
        expected_project_sha256=_hash(renamed_project),
    )
    assert result.no_drc_regression
    assert len(seen) == 2


def _changed_r4_schematic(tmp_path: Path) -> Path:
    """Discardable user proposed root schematic; original stays immutable."""
    original = _original()[0].with_suffix(".kicad_sch")
    text = original.read_text()
    start = text.index('(property "Reference" "R4"')
    original_value = '(property "Value" "5.1K"'
    value_index = text.index(original_value, start)
    candidate = tmp_path / "candidate-schematic.kicad_sch"
    candidate.write_text(text[:value_index] + '(property "Value" "900K"' + text[value_index + len(original_value) :])
    return candidate


def test_native_electrical_review_preserves_preexisting_original_parity_and_erc(
    tmp_path: Path, native_kicad_10
) -> None:
    board, project = _original()
    schematic = board.with_suffix(".kicad_sch")
    original_sha = _hash(schematic)
    review = review_native_pcb_drc_delta(
        board,
        _candidate(tmp_path),
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(board),
        expected_project_sha256=_hash(project),
        include_electrical_checks=True,
        expected_original_schematic_sha256=original_sha,
    )
    report = review.to_dict()
    evidence = report["electrical_review"]
    assert evidence["baseline_schematic_parity_issues"] == 2
    assert evidence["candidate_schematic_parity_issues"] == 2
    assert evidence["new_schematic_parity_issues"] == 0
    assert evidence["baseline_erc_violations"] == 76
    assert evidence["candidate_erc_violations"] == 76
    assert evidence["new_erc_violations"] == 0
    assert evidence["no_electrical_regression"]
    assert evidence["baseline_electrical_clean"] is False
    assert report["no_review_regression"] is True
    assert report["manufacturing_approved"] is False
    assert _hash(schematic) == original_sha


def test_native_new_candidate_schematic_value_mismatch_is_an_explicit_review_failure(
    tmp_path: Path, native_kicad_10
) -> None:
    board, project = _original()
    original_schematic = board.with_suffix(".kicad_sch")
    candidate_schematic = _changed_r4_schematic(tmp_path)
    candidate_sha = _hash(candidate_schematic)
    result = review_native_pcb_drc_delta(
        board,
        _candidate(tmp_path),
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(board),
        expected_project_sha256=_hash(project),
        include_electrical_checks=True,
        expected_original_schematic_sha256=_hash(original_schematic),
        candidate_schematic=candidate_schematic,
        expected_candidate_schematic_sha256=candidate_sha,
    )
    report = result.to_dict()
    evidence = report["electrical_review"]
    assert result.no_drc_regression
    assert evidence["baseline_schematic_parity_issues"] == 2
    assert evidence["candidate_schematic_parity_issues"] == 3
    assert evidence["new_schematic_parity_issues"] == 1
    assert evidence["new_schematic_parity_types"]["footprint_symbol_mismatch"] == 1
    assert evidence["new_erc_violations"] >= 0
    assert report["no_review_regression"] is False
    assert report["manufacturing_approved"] is False
    assert _hash(candidate_schematic) == candidate_sha


def test_electrical_review_cli_json_exits_two_for_source_schematic_parity_regression(
    tmp_path: Path, native_kicad_10
) -> None:
    board, _ = _original()
    candidate_board = _candidate(tmp_path)
    candidate_schematic = _changed_r4_schematic(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "kicad",
            "pcb-drc-delta",
            str(board),
            str(candidate_board),
            "--electrical-checks",
            "--candidate-schematic",
            str(candidate_schematic),
            "--json",
        ],
    )
    assert result.exit_code == 2, result.output
    response = json.loads(result.output)
    assert response["no_drc_regression"] is True
    assert response["no_review_regression"] is False
    assert response["electrical_review"]["new_schematic_parity_issues"] == 1


def test_electrical_review_rejects_unpinned_candidate_schematic_without_native_run(
    tmp_path: Path,
) -> None:
    board, project = _original()
    candidate = _changed_r4_schematic(tmp_path)
    original_schematic = board.with_suffix(".kicad_sch")
    with pytest.raises(ValueError, match="SHA-256"):
        review_native_pcb_drc_delta(
            board,
            _candidate(tmp_path),
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(board),
            expected_project_sha256=_hash(project),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_hash(original_schematic),
            candidate_schematic=candidate,
            expected_candidate_schematic_sha256="0" * 64,
        )


def test_malformed_candidate_sheet_reference_fails_closed_instead_of_claiming_partial_erc(
    tmp_path: Path,
) -> None:
    board, project = _original()
    original_sch = board.with_suffix(".kicad_sch")
    candidate = tmp_path / "proposed.kicad_sch"
    source = original_sch.read_text()
    assert source.startswith("(kicad_sch")
    sheet = '\n\t(sheet (property "Sheet name" "child") (property "Sheet file" "child.kicad_sch"))\n'
    candidate.write_text(source[: source.rfind(")")] + sheet + ")")
    with pytest.raises(ValueError, match="sheet must have exactly one filename and UUID"):
        review_native_pcb_drc_delta(
            board,
            _candidate(tmp_path),
            expected_original_sha256=_hash(board),
            expected_candidate_sha256=_hash(board),
            expected_project_sha256=_hash(project),
            include_electrical_checks=True,
            expected_original_schematic_sha256=_hash(original_sch),
            candidate_schematic=candidate,
            expected_candidate_schematic_sha256=_hash(candidate),
        )


def test_real_original_schematic_new_unconnected_pin_is_rejected_by_native_erc(tmp_path: Path, native_kicad_10) -> None:
    board, project = _original()
    original_sch = board.with_suffix(".kicad_sch")
    before_hash = _hash(original_sch)
    source = original_sch.read_text()
    marker = '\t(no_connect\n\t\t(at 44.45 151.13)\n\t\t(uuid "89323bf6-e107-4ef5-b287-4b29c50059e6")\n\t)\n'
    assert source.count(marker) == 1
    changed = tmp_path / "user-proposed.kicad_sch"
    changed.write_text(source.replace(marker, "", 1))
    changed_sha = _hash(changed)
    result = review_native_pcb_drc_delta(
        board,
        _candidate(tmp_path),
        expected_original_sha256=_hash(board),
        expected_candidate_sha256=_hash(board),
        expected_project_sha256=_hash(project),
        include_electrical_checks=True,
        expected_original_schematic_sha256=before_hash,
        candidate_schematic=changed,
        expected_candidate_schematic_sha256=changed_sha,
    )
    assert result.no_drc_regression
    assert not result.no_review_regression
    evidence = result.to_dict()["electrical_review"]
    assert evidence["baseline_erc_violations"] == 76
    assert evidence["candidate_erc_violations"] == 77
    assert evidence["new_erc_violations"] == 1
    assert evidence["new_erc_violation_types"]["pin_not_connected"] == 1
    assert result.manufacturing_approved is False
    assert _hash(original_sch) == before_hash
    assert _hash(changed) == changed_sha


def test_cli_candidate_schematic_requires_electrical_checks(tmp_path: Path) -> None:
    board, _ = _original()
    candidate_board = _candidate(tmp_path)
    candidate_schematic = _changed_r4_schematic(tmp_path)
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "pcb-drc-delta",
            str(board),
            str(candidate_board),
            "--candidate-schematic",
            str(candidate_schematic),
        ],
    )
    assert response.exit_code != 0
    assert "requires --electrical-checks" in response.output
