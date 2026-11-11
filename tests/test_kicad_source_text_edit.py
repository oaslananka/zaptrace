"""Source-backed annotation edits must not silently rewrite electrical or graphic data."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from zaptrace.io.sexp import parse
from zaptrace.kicad.schematic_importer import import_kicad_schematic, import_kicad_schematic_string
from zaptrace.kicad.source_edit import replace_kicad_source_text

FIRST = "11111111-1111-4111-8111-111111111111"
SECOND = "22222222-2222-4222-8222-222222222222"
FLAG = "33333333-3333-4333-8333-333333333333"

SOURCE = (
    "(kicad_sch\r\n"
    " (version 20250101)\r\n"
    ' (title_block (title "Güç devresi"))\r\n'
    f' (text "Original" (at 1 2 0) (uuid "{FIRST}"))\r\n'
    ' ;; A literal comment: (text "not editable")\r\n'
    f' (text "Original" (at 3 4 0) (uuid "{SECOND}"))\r\n'
    f' (netclass_flag "" (property "Netclass" "VBUS") (uuid "{FLAG}"))\r\n'
    " (polyline (pts (xy 0 0) (xy 5 5)))\r\n"
    ")\r\n"
)


def _snapshot(source: str = SOURCE):
    snapshot = import_kicad_schematic_string(source).source_snapshot
    assert snapshot is not None
    return snapshot


def test_edit_one_uuid_preserves_every_other_original_byte() -> None:
    snapshot = _snapshot()
    edited = replace_kicad_source_text(snapshot, FIRST, 'Yeni "başlık" \\ pro', expected_sha256=snapshot.sha256)

    assert snapshot.raw_bytes == SOURCE.encode("utf-8")
    assert edited == snapshot.raw_bytes.replace(
        b'"Original" (at 1 2 0)',
        '"Yeni \\"başlık\\" \\\\ pro" (at 1 2 0)'.encode(),
        1,
    )
    original = parse(snapshot.raw_bytes.decode("utf-8"))
    changed = parse(edited.decode("utf-8"))
    assert original != changed
    assert isinstance(original, list) and isinstance(changed, list)
    assert original[:4] != changed[:4]  # the first annotation is updated
    assert original[4:] == changed[4:]  # other annotation, netclass, polyline unchanged
    assert changed[3][1] == 'Yeni "başlık" \\ pro'


def test_edit_rejects_stale_source_missing_or_ambiguous_ids() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValueError, match="SHA-256"):
        replace_kicad_source_text(snapshot, FIRST, "Edited", expected_sha256="a" * 64)
    with pytest.raises(ValueError, match="unique"):
        replace_kicad_source_text(snapshot, FLAG, "edited", expected_sha256=snapshot.sha256)
    repeated = SOURCE.replace(SECOND, FIRST)
    repeated_snapshot = _snapshot(repeated)
    with pytest.raises(ValueError, match="unique"):
        replace_kicad_source_text(repeated_snapshot, FIRST, "edited", expected_sha256=repeated_snapshot.sha256)
    with pytest.raises(ValueError, match="control"):
        replace_kicad_source_text(snapshot, FIRST, "bad\x00value", expected_sha256=snapshot.sha256)


def test_real_kicad_source_annotation_edit_preserves_full_imported_nets() -> None:
    root = Path(__file__).parents[1] / "benchmarks/external/sparkfun-qwiic-navigation/source"
    reference = next(root.glob("*.kicad_sch"))
    original = import_kicad_schematic(reference)
    snapshot = original.source_snapshot
    assert snapshot is not None
    first = snapshot.nodes("text")[0]
    uuid_node = next(node for node in first if isinstance(node, list) and node and node[0] == "uuid")
    uuid = str(uuid_node[1])
    edited = replace_kicad_source_text(snapshot, uuid, "G0 review note", expected_sha256=snapshot.sha256)
    assert hashlib.sha256(snapshot.raw_bytes).hexdigest() == snapshot.sha256
    assert hashlib.sha256(edited).hexdigest() != snapshot.sha256
    after = import_kicad_schematic_string(edited.decode("utf-8"), source_path=reference)
    assert after.design.nets == original.design.nets
    assert after.design.components == original.design.components
    assert after.unsupported_count == original.unsupported_count
    assert after.source_snapshot is not None
    assert after.source_snapshot.nodes("netclass_flag") == snapshot.nodes("netclass_flag")
