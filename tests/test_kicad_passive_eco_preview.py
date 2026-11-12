"""A human-facing, source-backed passive ECO must remain a reviewed draft."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli
from zaptrace.io.sexp import parse
from zaptrace.kicad.pcb_source_edit import replace_kicad_pcb_footprint_value

SOURCE = Path(__file__).parents[1] / "benchmarks/external/nitu-555-blinker/source"


def _project() -> tuple[Path, Path, Path]:
    return (
        next(SOURCE.glob("*.kicad_pcb")),
        next(SOURCE.glob("*.kicad_sch")),
        next(SOURCE.glob("*.kicad_pro")),
    )


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def native_kicad_10() -> str:
    binary = shutil.which("kicad-cli")
    if binary is None:
        pytest.skip("native KiCad 10 CLI required: independent ECO not run")
    probe = subprocess.run([binary, "version"], capture_output=True, text=True, timeout=15)
    if probe.returncode or not probe.stdout.startswith("10."):
        pytest.skip("native KiCad 10 CLI required")
    return binary


def test_real_first_original_board_and_schematic_eco_runs_native_checks_and_writes_reviewable_drafts(
    tmp_path: Path, native_kicad_10: str
) -> None:
    board, schematic, project = _project()
    original_hashes = {p: _hash(p.read_bytes()) for p in (board, schematic, project)}
    destination = tmp_path / "eco-draft"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(destination),
            "--json",
        ],
    )
    assert response.exit_code == 0, response.output
    report = json.loads(response.output)
    assert report["task_kind"] == "human-directed-passive-value-edit"
    assert report["attempt_status"] == "human-review-required"
    assert report["g0_verified"] is False
    assert report["manufacturing_approved"] is False
    assert report["reference"] == "R1"
    assert report["old_value"] == "4.7k"
    assert report["new_value"] == "5.1k"
    assert report["canonical_nets_preserved"] is True
    assert report["native_kicad_version"].startswith("10.")
    assert report["elapsed_seconds"] > 0
    review = report["native_review"]
    assert review["no_review_regression"] is True
    assert review["baseline_violations"] == review["candidate_violations"] == 0
    assert review["electrical_review"]["new_schematic_parity_issues"] == 0
    assert review["electrical_review"]["new_erc_violations"] == 0
    assert review["baseline_drc_clean"] is True
    assert review["candidate_drc_clean"] is True

    candidate_board = destination / board.name
    candidate_schematic = destination / schematic.name
    candidate_project = destination / project.name
    artifact = json.loads((destination / "eco-review.json").read_text())
    assert artifact == report
    assert candidate_board.is_file() and candidate_schematic.is_file() and candidate_project.is_file()
    assert _hash(candidate_board.read_bytes()) == report["candidate_pcb_sha256"]
    assert _hash(candidate_schematic.read_bytes()) == report["candidate_schematic_sha256"]
    assert _hash(candidate_project.read_bytes()) == original_hashes[project]
    assert b'(property "Value" "5.1k"' in candidate_board.read_bytes()
    assert b'(property "Value" "5.1k"' in candidate_schematic.read_bytes()
    assert all(_hash(p.read_bytes()) == expected for p, expected in original_hashes.items())


def test_board_value_patch_changes_only_one_reference_value_and_not_pad_or_net_metadata() -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    original_tree = parse(raw.decode())
    changed = replace_kicad_pcb_footprint_value(raw, "R1", "4.7k", "5.1k", expected_sha256=_hash(raw))
    candidate_tree = parse(changed.decode())
    assert changed != raw
    assert isinstance(original_tree, list) and isinstance(candidate_tree, list)
    assert len(original_tree) == len(candidate_tree)
    changed_footprint_indices = [i for i in range(len(original_tree)) if original_tree[i] != candidate_tree[i]]
    assert len(changed_footprint_indices) == 1
    old_footprint = original_tree[changed_footprint_indices[0]]
    new_footprint = candidate_tree[changed_footprint_indices[0]]
    old_fields = [node for node in old_footprint if isinstance(node, list) and node[:2] == ["property", "Value"]]
    new_fields = [node for node in new_footprint if isinstance(node, list) and node[:2] == ["property", "Value"]]
    assert len(old_fields) == len(new_fields) == 1
    assert old_fields[0][2] == "4.7k" and new_fields[0][2] == "5.1k"
    assert len(old_footprint) == len(new_footprint)


@pytest.mark.parametrize(
    ("reference", "old_value", "new_value", "expected"),
    [
        ("R1", "47k", "5.1k", "value"),
        ("R1", "4.7k", "4.7k", "unchanged"),
        ("R9", "4.7k", "5.1k", "unique|reference"),
        ("U1", "NE555", "LM555", "R/C"),
    ],
)
def test_board_patch_refuses_nonmatching_or_unsupported_values(
    reference: str, old_value: str, new_value: str, expected: str
) -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    with pytest.raises(ValueError, match=expected):
        replace_kicad_pcb_footprint_value(raw, reference, old_value, new_value, expected_sha256=_hash(raw))
    assert board.read_bytes() == raw


def test_board_patch_refuses_stale_source_hash() -> None:
    board, _, _ = _project()
    with pytest.raises(ValueError, match="SHA-256"):
        replace_kicad_pcb_footprint_value(board.read_bytes(), "R1", "4.7k", "5.1k", expected_sha256="0" * 64)


def test_user_output_directory_must_not_exist_or_overlap_original(tmp_path: Path) -> None:
    board, _, _ = _project()
    output = tmp_path / "existing"
    output.mkdir()
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(output),
        ],
    )
    assert response.exit_code != 0
    assert "already exists" in response.output
    assert list(output.iterdir()) == []


def test_cli_help_exposes_one_command_without_uuid_or_manual_hashes() -> None:
    response = CliRunner().invoke(cli, ["kicad", "passive-eco-preview", "--help"])
    assert response.exit_code == 0, response.output
    for field in ("--reference", "--from-value", "--to-value", "--output-dir", "--json"):
        assert field in response.output


def test_schematic_old_value_mismatch_wont_create_output(tmp_path: Path) -> None:
    board, _, _ = _project()
    destination = tmp_path / "wrong-old"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "47k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(destination),
            "--json",
        ],
    )
    assert response.exit_code != 0
    assert "source value" in response.output.lower() or "expected" in response.output.lower()
    assert not destination.exists()


def test_reject_original_source_tree_as_output_location_without_any_writes() -> None:
    board, schematic, project = _project()
    hashes = {p: _hash(p.read_bytes()) for p in (board, schematic, project)}
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(board.parent / "eco-proposal"),
        ],
    )
    assert response.exit_code != 0
    assert "inside the original source project" in response.output
    assert all(_hash(path.read_bytes()) == digest for path, digest in hashes.items())
    assert not (board.parent / "eco-proposal").exists()


def test_reject_vendor_fixed_value_schematic_without_artifact_write(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source"
    board = next(source.glob("*.kicad_pcb"))
    destination = tmp_path / "invalid-vendor"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R14",
            "--from-value",
            "2.2k",
            "--to-value",
            "4.7k",
            "--output-dir",
            str(destination),
        ],
    )
    assert response.exit_code != 0
    assert "generic R/C" in response.output or "library" in response.output
    assert not destination.exists()


def test_board_duplicate_passive_reference_is_rejected_without_guessing() -> None:
    board, _, _ = _project()
    raw = board.read_bytes()
    assert b'(property "Reference" "R2"' in raw
    duplicated = raw.replace(b'(property "Reference" "R2"', b'(property "Reference" "R1"', 1)
    with pytest.raises(ValueError, match="unique"):
        replace_kicad_pcb_footprint_value(duplicated, "R1", "4.7k", "5.1k", expected_sha256=_hash(duplicated))


def test_existing_symlink_output_does_not_get_overwritten(tmp_path: Path) -> None:
    board, _, _ = _project()
    target = tmp_path / "existing-real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(board),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(alias),
        ],
    )
    assert response.exit_code != 0
    assert "already exists" in response.output
    assert list(target.iterdir()) == []


def test_multisheet_eco_preview_fails_closed_without_incomplete_output(tmp_path: Path) -> None:
    board, schematic, project = _project()
    source = tmp_path / "source"
    source.mkdir()
    for original in (board, schematic, project):
        (source / original.name).write_bytes(original.read_bytes())
    proposed_root = source / schematic.name
    insert = (
        '(sheet (uuid "44444444-5555-4666-8777-888888888888") '
        '(property "Sheetfile" "auxiliary.kicad_sch") '
        '(property "Sheetname" "Auxiliary"))\n'
    )
    proposed_root.write_text(proposed_root.read_text().replace("(sheet_instances", insert + "(sheet_instances", 1))
    (source / "auxiliary.kicad_sch").write_text(
        '(kicad_sch (version 20250114) (uuid "33333333-3333-4333-8333-333333333333") (paper "A4") (lib_symbols))'
    )
    output_dir = tmp_path / "proposal"
    response = CliRunner().invoke(
        cli,
        [
            "kicad",
            "passive-eco-preview",
            str(source / board.name),
            "--reference",
            "R1",
            "--from-value",
            "4.7k",
            "--to-value",
            "5.1k",
            "--output-dir",
            str(output_dir),
        ],
    )
    assert response.exit_code != 0
    assert "single-sheet" in response.output
    assert not output_dir.exists()
