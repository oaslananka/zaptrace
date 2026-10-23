"""Verified supplier artwork must survive KiCad PCB embedding unchanged."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from zaptrace.core.parser import parse_file
from zaptrace.export.kicad import export_kicad_pcb
from zaptrace.io.sexp import SexpNode, parse
from zaptrace.kicad.verified_vendor import verified_footprint_bytes

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "examples" / "esp32_i2c_sensor_node" / "design.yaml"


def _child(node: SexpNode, kind: str) -> list[SexpNode]:
    assert isinstance(node, list)
    return [part for part in node[1:] if isinstance(part, list) and part and part[0] == kind]


def _geometry(node: SexpNode) -> SexpNode:
    """Canonical fingerprint excluding instance-only UUID/net and field values."""
    if isinstance(node, str):
        return node
    if node and node[0] in {"uuid", "tstamp", "net"}:
        return []
    if node and node[0] == "fp_text" and len(node) > 1 and node[1] in {"value", "reference"}:
        return []
    if node and node[0] == "property":
        return []
    return [_geometry(part) for part in node if _geometry(part) != []]


def test_embedded_vendor_courtyard_antenna_keepout_and_3d_models_survive(tmp_path: Path) -> None:
    design = parse_file(_SOURCE)
    pcb_path = export_kicad_pcb(design, tmp_path)["pcb"]
    board = parse(pcb_path.read_text(encoding="utf-8"))
    footprints = _child(board, "footprint")
    assert len(footprints) == len(design.components)
    for comp in design.components.values():
        assert comp.footprint_asset is not None
        filename, raw_bytes = verified_footprint_bytes(comp.footprint_asset)
        library = parse(raw_bytes.decode("utf-8"))
        expected_id = "ZapTrace:" + filename.removesuffix(".kicad_mod")
        matching = [fp for fp in footprints if isinstance(fp, list) and len(fp) > 1 and fp[1] == expected_id]
        assert matching, comp.ref
        instance = next(
            fp
            for fp in matching
            if any(
                isinstance(prop, list) and prop[:3] == ["property", "Reference", comp.ref]
                for prop in _child(fp, "property")
            )
        )
        for kind in ("fp_line", "fp_rect", "fp_poly", "fp_circle", "fp_arc", "model"):
            # All supplier artwork/keepouts copied, with instance-unique IDs.
            assert [_geometry(item) for item in _child(instance, kind)] == [
                _geometry(item) for item in _child(library, kind)
            ], (comp.ref, kind)
        # Native KiCad stores footprint rule-area polygons in board-absolute
        # coordinates and restricts them to the installed copper layers.
        library_zones = _child(library, "zone")
        instance_zones = _child(instance, "zone")
        assert len(library_zones) == len(instance_zones)
        assert design.placement is not None
        for original, placed in zip(library_zones, instance_zones, strict=True):
            source_points = _child(_child(original, "polygon")[0], "pts")[0]
            board_points = _child(_child(placed, "polygon")[0], "pts")[0]
            cx, cy = design.placement[comp.id]
            for source_point, placed_point in zip(source_points[1:], board_points[1:], strict=True):
                assert isinstance(source_point, list) and isinstance(placed_point, list)
                expected = (float(str(source_point[1])) + cx, float(str(source_point[2])) + cy)
                actual = (float(str(placed_point[1])), float(str(placed_point[2])))
                assert actual == pytest.approx(expected)
            assert _child(placed, "layers") == [["layers", "F.Cu", "B.Cu"]]
        assert len(_child(instance, "pad")) == len(_child(library, "pad"))
        assert [_geometry(x) for x in _child(instance, "pad")] == [_geometry(x) for x in _child(library, "pad")], (
            comp.ref
        )


def test_repeated_resistor_footprints_have_distinct_object_identifiers(tmp_path: Path) -> None:
    design = parse_file(_SOURCE)
    board = parse(export_kicad_pcb(design, tmp_path)["pcb"].read_text(encoding="utf-8"))
    ids: list[str] = []

    def collect(node: SexpNode) -> None:
        if isinstance(node, str):
            return
        if node and node[0] == "uuid" and len(node) > 1:
            ids.append(str(node[1]))
        for child in node:
            collect(child)

    collect(board)
    counts = Counter(ids)
    assert all(value == 1 for value in counts.values())
    assert len(ids) > 100


def test_vendor_legacy_reference_becomes_real_board_reference_property(tmp_path: Path) -> None:
    design = parse_file(_SOURCE)
    board = parse(export_kicad_pcb(design, tmp_path)["pcb"].read_text(encoding="utf-8"))
    j1 = next(
        fp
        for fp in _child(board, "footprint")
        if any(
            isinstance(prop, list) and prop[:3] == ["property", "Reference", "J1"] for prop in _child(fp, "property")
        )
    )
    assert len(_child(j1, "pad")) == 22
    assert len(_child(j1, "fp_rect")) == 2
    assert any(isinstance(pad, list) and pad[1] == "S1" and _child(pad, "drill") for pad in _child(j1, "pad"))


def test_heatsink_pad_enum_is_unquoted_for_native_kicad_parser(tmp_path: Path) -> None:
    """KiCad 10 drops quoted pad enums silently, even if generic ASTs match."""
    design = parse_file(_SOURCE)
    board_text = export_kicad_pcb(design, tmp_path)["pcb"].read_text(encoding="utf-8")
    _name, source = verified_footprint_bytes("esp32-wroom-32")
    vendor_count = source.count(b"(property pad_prop_heatsink)")
    assert vendor_count > 0
    assert board_text.count("(property pad_prop_heatsink)") == vendor_count
    assert '(property "pad_prop_heatsink")' not in board_text
    assert board_text.count('(property "Reference" "U1"') == 1
    assert board_text.count('(property "Value" "ESP32-WROOM-32"') == 1
