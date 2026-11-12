"""Outside-in: review one native KiCad netclass edit without touching the project."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from zaptrace.cli.main import cli


@pytest.fixture
def original_mitayi(tmp_path: Path) -> tuple[Path, bytes, bytes]:
    source_dir = Path(__file__).parents[1] / "benchmarks/external/mitayi-pico-d1/source"
    original_sch = next(source_dir.glob("*.kicad_sch"))
    original_pro = next(source_dir.glob("*.kicad_pro"))
    owned = tmp_path / "original"
    owned.mkdir()
    schematic = owned / original_sch.name
    project = owned / original_pro.name
    sch_bytes = original_sch.read_bytes()
    pro_bytes = original_pro.read_bytes()
    schematic.write_bytes(sch_bytes)
    project.write_bytes(pro_bytes)
    return schematic, sch_bytes, pro_bytes


def _run(*args: str):
    return CliRunner().invoke(cli, ["kicad", "netclass-preview", *args])


def test_cli_help_explains_review_not_hardware_signoff() -> None:
    result = _run("--help")
    assert result.exit_code == 0, result.output
    assert "--from-class" in result.output
    assert "--to-class" in result.output
    assert "--output-dir" in result.output
    assert "preview" in result.output.lower()


def test_native_kicad_preview_creates_safe_separate_review_folder(
    tmp_path: Path, original_mitayi: tuple[Path, bytes, bytes]
) -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI")
    schematic, original_source, original_project = original_mitayi
    output = tmp_path / "review"
    result = _run(
        str(schematic),
        "--from-class",
        "VBUS",
        "--to-class",
        "GND",
        "--output-dir",
        str(output),
        "--json",
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["net_name"] == "VBUS"
    assert report["before_class"] == "VBUS"
    assert report["after_class"] == "GND"
    assert report["native_net_count"] == 64
    assert report["native_pin_node_count"] == 231
    assert report["erc_findings_unchanged"] is True
    assert report["pcb_drc_verified"] is False
    assert report["source_was_modified"] is False
    assert report["draft_directory"] == str(output)
    assert (output / "review.kicad_pro").read_bytes() == original_project
    edited = (output / "review.kicad_sch").read_bytes()
    assert edited == original_source.replace(b'(property "Netclass" "VBUS"', b'(property "Netclass" "GND"', 1)
    assert schematic.read_bytes() == original_source
    assert schematic.with_suffix(".kicad_pro").read_bytes() == original_project
    assert not list(output.glob("*.kicad_pcb"))


def test_native_preview_defaults_to_read_only_json(original_mitayi: tuple[Path, bytes, bytes]) -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI")
    schematic, sch_before, pro_before = original_mitayi
    result = _run(str(schematic), "--from-class", "VBUS", "--to-class", "3V3", "--json")
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["after_class"] == "3V3"
    assert "draft_directory" not in report
    assert schematic.read_bytes() == sch_before
    assert schematic.with_suffix(".kicad_pro").read_bytes() == pro_before
    assert (
        sorted(p.name for p in schematic.parent.iterdir()) == [schematic.name, schematic.with_suffix(".kicad_pro").name]
        or len(list(schematic.parent.iterdir())) == 2
    )


def test_existing_output_directory_is_rejected_without_overwrite(
    tmp_path: Path, original_mitayi: tuple[Path, bytes, bytes]
) -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI")
    schematic, original_source, original_project = original_mitayi
    target = tmp_path / "existing"
    target.mkdir()
    marker = target / "review.kicad_sch"
    marker.write_text("KEEP THIS ORIGINAL", encoding="utf-8")
    result = _run(
        str(schematic),
        "--from-class",
        "VBUS",
        "--to-class",
        "GND",
        "--output-dir",
        str(target),
        "--json",
    )
    assert result.exit_code != 0
    assert "already exists" in result.output.lower()
    assert marker.read_text() == "KEEP THIS ORIGINAL"
    assert schematic.read_bytes() == original_source
    assert schematic.with_suffix(".kicad_pro").read_bytes() == original_project


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("WRONG_CLASS", "GND", "no"),
        ("VBUS", "UNKNOWN", "defined"),
        ("VBUS", "VBUS", "unchanged"),
    ],
)
def test_invalid_class_is_refused_without_creating_any_draft(
    tmp_path: Path, original_mitayi: tuple[Path, bytes, bytes], old: str, new: str, expected: str
) -> None:
    schematic, original_source, _ = original_mitayi
    output = tmp_path / "never-created"
    result = _run(str(schematic), "--from-class", old, "--to-class", new, "--output-dir", str(output), "--json")
    assert result.exit_code != 0
    assert expected in result.output.lower(), result.output
    assert not output.exists()
    assert schematic.read_bytes() == original_source


def test_cli_requires_explicit_target_and_exit_code() -> None:
    result = _run("--from-class", "VBUS", "--to-class", "GND")
    assert result.exit_code != 0
    assert "Missing argument" in result.output


def test_ambiguous_class_requires_explicit_uuid(original_mitayi: tuple[Path, bytes, bytes], tmp_path: Path) -> None:
    schematic, original_source, _ = original_mitayi
    assert original_source.count(b'(property "Netclass" "1V1"') == 1
    modified = original_source.replace(b'(property "Netclass" "1V1"', b'(property "Netclass" "VBUS"', 1)
    schematic.write_bytes(modified)
    target = tmp_path / "must-not-exist"
    result = _run(
        str(schematic),
        "--from-class",
        "VBUS",
        "--to-class",
        "GND",
        "--output-dir",
        str(target),
        "--json",
    )
    assert result.exit_code != 0
    assert "Multiple netclass directives" in result.output
    assert "--flag-uuid" in result.output
    assert not target.exists()


def test_missing_project_cannot_create_draft(tmp_path: Path, original_mitayi: tuple[Path, bytes, bytes]) -> None:
    schematic, _, _ = original_mitayi
    schematic.with_suffix(".kicad_pro").unlink()
    destination = tmp_path / "must-not-exist"
    result = _run(
        str(schematic),
        "--from-class",
        "VBUS",
        "--to-class",
        "GND",
        "--output-dir",
        str(destination),
    )
    assert result.exit_code != 0
    assert ".kicad_pro" in result.output
    assert not destination.exists()


def test_invalid_review_parent_rejected_before_running_native_cli(
    tmp_path: Path, original_mitayi: tuple[Path, bytes, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    schematic, original_source, _ = original_mitayi
    target = tmp_path / "nonexistent-parent" / "review"

    def forbid_verification(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("native verification must not run when output parent is missing")

    monkeypatch.setattr(
        "zaptrace.cli.netclass_preview.preview_native_netclass_reassignment",
        forbid_verification,
    )
    result = _run(
        str(schematic),
        "--from-class",
        "VBUS",
        "--to-class",
        "GND",
        "--output-dir",
        str(target),
    )
    assert result.exit_code != 0
    assert "parent" in result.output.lower()
    assert not target.parent.exists()
    assert schematic.read_bytes() == original_source
