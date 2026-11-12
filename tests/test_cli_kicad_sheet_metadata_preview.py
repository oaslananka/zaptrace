"""User-visible single-command native KiCad sheet-title/page preview."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli


def _source() -> tuple[Path, bytes, bytes]:
    root = Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source"
    schematic = next(root.glob("*.kicad_sch"))
    project = next(root.glob("*.kicad_pro"))
    return schematic, schematic.read_bytes(), project.read_bytes()


def _run(*args: str):
    return CliRunner().invoke(cli, ["kicad", "sheet-metadata-preview", *args])


def test_command_has_unambiguous_user_help() -> None:
    result = _run("--help")
    assert result.exit_code == 0, result.output
    for expected in ("--field", "--expected-value", "--new-value", "--output-dir", "--json"):
        assert expected in result.output


def test_real_native_read_only_paper_review_preserves_original_bytes() -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI; no independent evidence on this runner")
    schematic, original_sch, original_pro = _source()
    result = _run(
        str(schematic),
        "--field",
        "paper",
        "--expected-value",
        "USLetter",
        "--new-value",
        "A4",
        "--json",
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["native_net_count"] == 32
    assert report["native_pin_node_count"] == 99
    assert report["erc_findings_unchanged"] is True
    assert report["source_was_modified"] is False
    assert report["pcb_drc_verified"] is False
    assert "draft_directory" not in report
    assert schematic.read_bytes() == original_sch
    assert schematic.with_suffix(".kicad_pro").read_bytes() == original_pro


def test_real_native_title_review_writes_only_new_isolated_source_copy(tmp_path: Path) -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI; no independent evidence on this runner")
    schematic, original_sch, original_pro = _source()
    output = tmp_path / "review"
    result = _run(
        str(schematic),
        "--field",
        "title",
        "--expected-value",
        "SparkFun Qwiic Navigation",
        "--new-value",
        "Review title — ölçüm",
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["field"] == "title"
    assert report["draft_directory"] == str(output)
    assert sorted(item.name for item in output.iterdir()) == ["review.kicad_pro", "review.kicad_sch"]
    assert (output / "review.kicad_pro").read_bytes() == original_pro
    expected_bytes = original_sch.replace(
        b'(title "SparkFun Qwiic Navigation")',
        '(title "Review title — ölçüm")'.encode(),
        1,
    )
    assert (output / "review.kicad_sch").read_bytes() == expected_bytes
    assert schematic.read_bytes() == original_sch


def test_existing_review_directory_is_never_overwritten(tmp_path: Path) -> None:
    schematic, original_sch, _ = _source()
    existing = tmp_path / "review"
    existing.mkdir()
    marker = existing / "review.kicad_sch"
    marker.write_text("MUST SURVIVE")
    result = _run(
        str(schematic),
        "--field",
        "paper",
        "--expected-value",
        "USLetter",
        "--new-value",
        "A4",
        "--output-dir",
        str(existing),
    )
    assert result.exit_code != 0
    assert "already exists" in result.output.lower()
    assert marker.read_text() == "MUST SURVIVE"
    assert schematic.read_bytes() == original_sch


def test_unmatched_original_fails_without_generating_draft(tmp_path: Path) -> None:
    schematic, original_sch, _ = _source()
    output = tmp_path / "review"
    result = _run(
        str(schematic),
        "--field",
        "paper",
        "--expected-value",
        "A3",
        "--new-value",
        "A4",
        "--output-dir",
        str(output),
    )
    assert result.exit_code != 0
    assert "expected" in result.output.lower()
    assert not output.exists()
    assert schematic.read_bytes() == original_sch
