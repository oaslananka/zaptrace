from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from zaptrace.benchmark.kicad_fixtures import (
    build_golden_kicad_fixture,
    compare_golden_kicad_fixture,
    compute_kicad_file_record,
    load_golden_kicad_fixture,
)

FIXTURE_ROOT = Path("tests/fixtures/benchmarks/kicad-golden/minimal_project")


def test_committed_golden_kicad_fixture_manifest_loads_and_compares_clean() -> None:
    fixture = load_golden_kicad_fixture(FIXTURE_ROOT / "fixture.json")
    result = compare_golden_kicad_fixture(fixture, FIXTURE_ROOT, allow_unexpected=True)

    assert fixture.schema_version == "1.0"
    assert fixture.comparison_policy == "sha256-exact"
    assert {item.kind for item in fixture.files} == {"project", "schematic", "pcb"}
    assert result.passed is True
    assert result.checked_count == 3


def test_build_golden_kicad_fixture_computes_hash_evidence() -> None:
    fixture = build_golden_kicad_fixture(FIXTURE_ROOT, fixture_id="rebuilt", family_id="esp32_usb_sensor")

    assert len(fixture.files) == 3
    assert all(len(item.sha256) == 64 for item in fixture.files)
    assert all(item.size_bytes > 0 for item in fixture.files)


def test_compare_golden_kicad_fixture_detects_changed_file(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_ROOT, tmp_path / "golden")
    root = tmp_path / "golden"
    fixture = load_golden_kicad_fixture(root / "fixture.json")
    (root / "minimal.kicad_pcb").write_text("changed\n", encoding="utf-8")

    result = compare_golden_kicad_fixture(fixture, root, allow_unexpected=True)

    assert result.passed is False
    assert result.changed_files == ["minimal.kicad_pcb"]


def test_compare_golden_kicad_fixture_detects_missing_required_file(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_ROOT, tmp_path / "golden")
    root = tmp_path / "golden"
    fixture = load_golden_kicad_fixture(root / "fixture.json")
    (root / "minimal.kicad_sch").unlink()

    result = compare_golden_kicad_fixture(fixture, root, allow_unexpected=True)

    assert result.passed is False
    assert result.missing_files == ["minimal.kicad_sch"]


def test_compare_golden_kicad_fixture_detects_unexpected_kicad_file(tmp_path: Path) -> None:
    shutil.copytree(FIXTURE_ROOT, tmp_path / "golden")
    root = tmp_path / "golden"
    fixture = load_golden_kicad_fixture(root / "fixture.json")
    (root / "extra.kicad_sch").write_text("(kicad_sch)\n", encoding="utf-8")

    result = compare_golden_kicad_fixture(fixture, root)

    assert result.passed is False
    assert result.unexpected_files == ["extra.kicad_sch"]


def test_fixture_path_must_stay_inside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes root"):
        compute_kicad_file_record(tmp_path, "../outside.kicad_pcb")
