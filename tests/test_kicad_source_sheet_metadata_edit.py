"""Outside-in: a single original KiCad sheet metadata change without schematic loss."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from zaptrace.io.sexp import parse
from zaptrace.kicad.schematic_importer import import_kicad_schematic_string
from zaptrace.kicad.sheet_metadata_edit import edit_kicad_sheet_metadata_source, preview_native_sheet_metadata

ORIGINAL = (
    "(kicad_sch\r\n"
    "  (version 20250114)\r\n"
    '  (paper "A3")\r\n'
    '  (title_block (title "Güç kartı") (rev "R1"))\r\n'
    '  (lib_symbols (symbol "sub" (property "title" "unchanged")))\r\n'
    '  (text "Graphic should remain")\r\n'
    ")\r\n"
)


def _source_snapshot(source: str = ORIGINAL):
    result = import_kicad_schematic_string(source)
    assert result.source_snapshot is not None
    return result.source_snapshot


@pytest.mark.parametrize(
    ("field", "old", "new", "before", "after"),
    [
        ("paper", "A3", "A4", '(paper "A3")', '(paper "A4")'),
        ("title", "Güç kartı", 'Revizyon "α"', '(title "Güç kartı")', '(title "Revizyon \\"α\\"")'),
        ("rev", "R1", "R2", '(rev "R1")', '(rev "R2")'),
    ],
)
def test_one_field_only_preserves_all_other_original_source_bytes(
    field: str, old: str, new: str, before: str, after: str
) -> None:
    snapshot = _source_snapshot()
    output = edit_kicad_sheet_metadata_source(snapshot, field, old, new, expected_sha256=snapshot.sha256)
    assert output == snapshot.raw_bytes.replace(before.encode(), after.encode(), 1)
    assert snapshot.raw_bytes == ORIGINAL.encode()
    expected_tree = parse(ORIGINAL)
    modified_tree = parse(output.decode())
    assert modified_tree != expected_tree
    assert b"\r\n" in output
    assert b"Graphic should remain" in output
    assert b'property "title" "unchanged"' in output
    original = import_kicad_schematic_string(ORIGINAL)
    edited = import_kicad_schematic_string(output.decode())
    assert edited.design.nets == original.design.nets
    assert edited.design.components == original.design.components


@pytest.mark.parametrize(
    ("field", "old", "new", "message"),
    [
        ("paper", "A3", "unsupported-format", "paper"),
        ("paper", "A3", "A3", "unchanged"),
        ("title", "Güç kartı", "Güç kartı", "unchanged"),
        ("rev", "WRONG", "R2", "expected"),
        ("title", "Güç kartı", "a\x00b", "control"),
        ("title", "Güç kartı", "x" * 300, "length"),
        ("foo", "A3", "A4", "field"),
    ],
)
def test_rejects_invalid_or_unchanged_source_metadata(field: str, old: str, new: str, message: str) -> None:
    snapshot = _source_snapshot()
    with pytest.raises(ValueError, match=message):
        edit_kicad_sheet_metadata_source(snapshot, field, old, new, expected_sha256=snapshot.sha256)


def test_rejects_stale_sha_missing_target_and_duplicate_fields() -> None:
    snapshot = _source_snapshot()
    with pytest.raises(ValueError, match="SHA"):
        edit_kicad_sheet_metadata_source(snapshot, "paper", "A3", "A4", expected_sha256="0" * 64)

    missing = _source_snapshot(ORIGINAL.replace('(paper "A3")', ""))
    with pytest.raises(ValueError, match="unique"):
        edit_kicad_sheet_metadata_source(missing, "paper", "A3", "A4", expected_sha256=missing.sha256)

    duplicated = _source_snapshot(ORIGINAL.replace('(paper "A3")', '(paper "A3") (paper "A3")'))
    with pytest.raises(ValueError, match="unique"):
        edit_kicad_sheet_metadata_source(duplicated, "paper", "A3", "A4", expected_sha256=duplicated.sha256)


def test_missing_title_must_not_be_inserted_by_guesswork() -> None:
    snapshot = _source_snapshot('(kicad_sch (paper "A4") (lib_symbols (symbol "x" (title "fake"))))')
    with pytest.raises(ValueError, match="unique"):
        edit_kicad_sheet_metadata_source(snapshot, "title", "Old", "New", expected_sha256=snapshot.sha256)


def test_native_kicad_original_sparkfun_page_change_has_identical_graph_and_erc() -> None:
    if shutil.which("kicad-cli") is None:
        pytest.skip("requires native KiCad 10 CLI for independent source/erc proof")
    source_dir = Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source"
    schematic = next(source_dir.glob("*.kicad_sch"))
    project = next(source_dir.glob("*.kicad_pro"))
    review = preview_native_sheet_metadata(
        schematic,
        "paper",
        "USLetter",
        "A4",
        expected_source_sha256=hashlib.sha256(schematic.read_bytes()).hexdigest(),
        expected_project_sha256=hashlib.sha256(project.read_bytes()).hexdigest(),
    )
    assert review.field == "paper"
    assert review.native_net_count == 32
    assert review.native_pin_node_count == 99
    assert review.erc_findings_unchanged
    assert review.edited_source_bytes != schematic.read_bytes()
    assert review.edited_source_bytes.count(b'(paper "A4")') == 1
