"""Regression coverage for golden KiCad fixture suffix classification."""

from pathlib import Path

from zaptrace.benchmark.kicad_fixtures import build_golden_kicad_fixture, compare_golden_kicad_fixture


def test_golden_fixture_discovers_and_classifies_supported_kicad_suffixes(tmp_path: Path) -> None:
    expected = {
        "board.kicad_pcb": "pcb",
        "project.kicad_pro": "project",
        "symbols.kicad_sym": "symbol-lib",
        "top.kicad_sch": "schematic",
    }
    for filename in expected:
        (tmp_path / filename).write_text(filename, encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("not a KiCad fixture", encoding="utf-8")

    fixture = build_golden_kicad_fixture(tmp_path, fixture_id="suffixes", family_id="regression")

    assert {record.path: record.kind for record in fixture.files} == expected
    assert compare_golden_kicad_fixture(fixture, tmp_path).passed is True
