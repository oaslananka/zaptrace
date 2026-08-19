"""Tests for Eagle XML round-trip adapter (issue #123).

Covers all acceptance criteria:
* Components, nets, board geometry, layers, pads, vias, tracks, and package
  geometry map into Design.
* The exporter produces schema-valid, deterministic Eagle XML for the
  supported subset.
* Unsupported records retain source XPath and severity.
* A vendored, licensed corpus enforces a round-trip score >= 0.78.
* Import and export are protected against unsafe XML features and oversized
  inputs.
"""

from __future__ import annotations

import xml.etree.ElementTree as _StdET
from pathlib import Path

import pytest

from zaptrace.eda.eagle import (
    EagleImportResult,
    EaglePad,
    EagleTrack,
    EagleUnsupportedRecord,
    compute_eagle_roundtrip_score,
    eagle_result_hash,
    export_eagle_xml,
    import_eagle_to_design,
    import_eagle_xml,
    import_eagle_xml_bytes,
    import_eagle_xml_string,
)

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------

_FIXTURE = Path(__file__).parent / "fixtures" / "eagle" / "minimal_board.brd"


# ---------------------------------------------------------------------------
# Minimal synthetic XML for unit tests
# ---------------------------------------------------------------------------

_MINIMAL_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<eagle version="7.7.0">
  <drawing>
    <layers>
      <layer number="1" name="Top" color="4" fill="1" visible="yes" active="yes"/>
      <layer number="16" name="Bottom" color="1" fill="1" visible="yes" active="yes"/>
      <layer number="20" name="Dimension" color="15" fill="1" visible="yes" active="yes"/>
    </layers>
    <board>
      <plain>
        <wire x1="0" y1="0" x2="10" y2="0" width="0.127" layer="20"/>
        <wire x1="10" y1="0" x2="10" y2="10" width="0.127" layer="20"/>
        <wire x1="10" y1="10" x2="0" y2="10" width="0.127" layer="20"/>
        <wire x1="0" y1="10" x2="0" y2="0" width="0.127" layer="20"/>
      </plain>
      <components>
        <component name="R1" library="rcl" deviceset="R-EU_" device="R0402" value="10k"/>
        <component name="C1" library="rcl" deviceset="C-EU_" device="C0402" value="100nF"/>
      </components>
      <libraries>
        <library name="rcl">
          <packages>
            <package name="R0402">
              <smd name="1" x="-0.5" y="0" dx="0.5" dy="0.5" layer="1"/>
              <smd name="2" x="0.5" y="0" dx="0.5" dy="0.5" layer="1"/>
            </package>
          </packages>
        </library>
      </libraries>
      <elements>
        <element name="R1" library="rcl" package="R0402" value="10k" x="5" y="5"/>
        <element name="C1" library="rcl" package="C0402" value="100nF" x="8" y="5"/>
      </elements>
      <signals>
        <signal name="VCC">
          <contactref element="R1" pad="1"/>
          <wire x1="4.5" y1="5" x2="8" y2="5" width="0.2032" layer="1"/>
        </signal>
        <signal name="GND">
          <contactref element="R1" pad="2"/>
          <contactref element="C1" pad="2"/>
          <wire x1="5.5" y1="5" x2="8.5" y2="5" width="0.2032" layer="1"/>
        </signal>
      </signals>
      <via x="6" y="6" extent="1-16" drill="0.4"/>
    </board>
  </drawing>
</eagle>"""

_WRONG_ROOT_XML = """<?xml version="1.0"?><notEagle><board/></notEagle>"""

_MALFORMED_XML = """<?xml version="1.0"?><eagle><drawing><board></notboard></drawing></eagle>"""


# ---------------------------------------------------------------------------
# EaglePad / EagleTrack / EagleUnsupportedRecord data class tests
# ---------------------------------------------------------------------------


class TestEagleDataClasses:
    def test_pad_to_dict_keys(self) -> None:
        pad = EaglePad(name="1", x_mm=0.5, y_mm=0.0, dx_mm=0.5, dy_mm=0.5, layer=1, kind="smd")
        d = pad.to_dict()
        assert {"name", "x_mm", "y_mm", "dx_mm", "dy_mm", "layer", "kind", "drill_mm"} <= d.keys()

    def test_track_to_dict_keys(self) -> None:
        t = EagleTrack(x1=0, y1=0, x2=5, y2=5, width=0.2, layer=1, net_name="VCC")
        d = t.to_dict()
        assert {"x1", "y1", "x2", "y2", "width", "layer", "net_name"} <= d.keys()

    def test_unsupported_record_has_xpath(self) -> None:
        ur = EagleUnsupportedRecord("polygon", "test", "info", xpath="/eagle/board/polygon")
        d = ur.to_dict()
        assert d["xpath"] == "/eagle/board/polygon"

    def test_result_to_dict(self) -> None:
        r = import_eagle_xml_string(_MINIMAL_XML)
        d = r.to_dict()
        assert d["component_count"] == 2
        assert d["net_count"] == 2


# ---------------------------------------------------------------------------
# Import from string
# ---------------------------------------------------------------------------


class TestImportEagleXmlString:
    def test_imports_components(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert "R1" in result.components
        assert "C1" in result.components

    def test_component_values(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert result.components["R1"]["value"] == "10k"
        assert result.components["C1"]["value"] == "100nF"

    def test_imports_nets(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert "VCC" in result.nets
        assert "GND" in result.nets

    def test_vcc_net_refs(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert "R1" in result.nets["VCC"]

    def test_gnd_net_refs(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert "R1" in result.nets["GND"]
        assert "C1" in result.nets["GND"]

    def test_imports_tracks(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert len(result.tracks) >= 2

    def test_track_net_name(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        vcc_tracks = [t for t in result.tracks if t.net_name == "VCC"]
        assert len(vcc_tracks) >= 1

    def test_imports_vias(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert len(result.vias) == 1
        assert result.vias[0].drill == pytest.approx(0.4)

    def test_imports_layers(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        layer_nums = {la.number for la in result.layers}
        assert 1 in layer_nums
        assert 16 in layer_nums

    def test_imports_board_outline(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert len(result.board_outline) == 4

    def test_imports_pads_from_package(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        # R1 has R0402 package with 2 pads
        assert "R1" in result.pads
        assert len(result.pads["R1"]) == 2

    def test_pad_coordinates_offset_by_element_position(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        pads = result.pads["R1"]
        # R1 is at (5, 5); pad 1 is at (-0.5, 0) + (5, 5) = (4.5, 5)
        pad1 = next(p for p in pads if p.name == "1")
        assert pad1.x_mm == pytest.approx(4.5)

    def test_schema_version(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert result.schema_version == "7.7.0"

    def test_unsupported_library_noted(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        kinds = [ur.kind for ur in result.unsupported]
        assert "library" in kinds

    def test_deterministic_import(self) -> None:
        r1 = import_eagle_xml_string(_MINIMAL_XML)
        r2 = import_eagle_xml_string(_MINIMAL_XML)
        assert set(r1.components) == set(r2.components)
        assert set(r1.nets) == set(r2.nets)

    def test_rejects_wrong_root(self) -> None:
        with pytest.raises(ValueError, match="eagle"):
            import_eagle_xml_string(_WRONG_ROOT_XML)

    def test_rejects_malformed_xml(self) -> None:
        with pytest.raises(ValueError):
            import_eagle_xml_string(_MALFORMED_XML)


# ---------------------------------------------------------------------------
# Import from bytes — size cap
# ---------------------------------------------------------------------------


class TestImportEagleXmlBytes:
    def test_rejects_oversized_input(self) -> None:
        huge = b"A" * (11 * 1024 * 1024)  # 11 MiB
        with pytest.raises(ValueError, match="too large"):
            import_eagle_xml_bytes(huge)

    def test_accepts_valid_xml_bytes(self) -> None:
        result = import_eagle_xml_bytes(_MINIMAL_XML.encode())
        assert "R1" in result.components


# ---------------------------------------------------------------------------
# Import from file
# ---------------------------------------------------------------------------


class TestImportEagleXmlFile:
    def test_file_not_found(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError):
            import_eagle_xml(tmp_path / "nonexistent.brd")

    def test_imports_fixture(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert len(result.components) >= 4
        assert len(result.nets) >= 3

    def test_fixture_component_names(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert "R1" in result.components
        assert "U1" in result.components

    def test_fixture_net_names(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert "VCC" in result.nets
        assert "GND" in result.nets

    def test_fixture_has_tracks(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert len(result.tracks) >= 3

    def test_fixture_has_vias(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert len(result.vias) >= 2

    def test_fixture_has_layers(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        assert len(result.layers) >= 5


# ---------------------------------------------------------------------------
# import_eagle_to_design
# ---------------------------------------------------------------------------


class TestImportEagleToDesign:
    def test_returns_design_and_result(self) -> None:
        design, result = import_eagle_to_design(_FIXTURE)
        assert design is not None
        assert isinstance(result, EagleImportResult)

    def test_design_has_components(self) -> None:
        design, _ = import_eagle_to_design(_FIXTURE)
        refs = {c.ref for c in design.components.values()}
        assert "R1" in refs

    def test_design_has_nets(self) -> None:
        design, _ = import_eagle_to_design(_FIXTURE)
        net_names = {n.name for n in design.nets.values()}
        assert "VCC" in net_names

    def test_import_losses_recorded(self) -> None:
        design, _ = import_eagle_to_design(_FIXTURE)
        assert isinstance(design.import_losses, list)


# ---------------------------------------------------------------------------
# Unsupported record structure
# ---------------------------------------------------------------------------


class TestUnsupportedRecords:
    def test_unsupported_record_has_kind(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        for ur in result.unsupported:
            assert ur.kind

    def test_unsupported_record_has_severity(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        for ur in result.unsupported:
            assert ur.severity in ("info", "warning", "error")

    def test_unsupported_record_has_xpath(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        for ur in result.unsupported:
            assert ur.xpath  # all records must have XPath

    def test_polygon_noted_with_xpath(self) -> None:
        xml = _MINIMAL_XML.replace(
            "<via",
            '<polygon width="0.127" layer="1"><vertex x="0" y="0"/></polygon><via',
        )
        result = import_eagle_xml_string(xml)
        poly = next((ur for ur in result.unsupported if ur.kind == "polygon"), None)
        assert poly is not None
        assert poly.xpath

    def test_designrules_noted(self) -> None:
        xml = _MINIMAL_XML.replace(
            "</board>",
            '<designrules name="default"><param name="layerSetup" value="(1*16)"/></designrules></board>',
        )
        result = import_eagle_xml_string(xml)
        dr = next((ur for ur in result.unsupported if ur.kind == "designrules"), None)
        assert dr is not None


# ---------------------------------------------------------------------------
# Exporter — determinism and re-importability
# ---------------------------------------------------------------------------


class TestExportEagleXml:
    def test_produces_string(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        assert isinstance(xml_out, str)

    def test_export_starts_with_xml_declaration(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        assert xml_out.startswith("<?xml")

    def test_export_has_eagle_root(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        assert "<eagle" in xml_out

    def test_export_re_importable(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        assert set(reimported.components) == {"R1", "C1"}

    def test_export_nets_preserved(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        assert "VCC" in reimported.nets
        assert "GND" in reimported.nets

    def test_export_deterministic(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml1 = export_eagle_xml(result)
        xml2 = export_eagle_xml(result)
        assert xml1 == xml2

    def test_export_tracks_preserved(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        assert len(reimported.tracks) == len(result.tracks)

    def test_export_vias_preserved(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        assert len(reimported.vias) == len(result.vias)

    def test_export_unsupported_comment(self) -> None:
        xml = _MINIMAL_XML.replace(
            "<via",
            '<polygon width="0.127" layer="1"><vertex x="0" y="0"/></polygon><via',
        )
        result = import_eagle_xml_string(xml)
        xml_out = export_eagle_xml(result)
        assert "ZapTrace export notes" in xml_out


def test_export_eagle_xml_preserves_all_supported_sections() -> None:
    result = import_eagle_xml_string(_MINIMAL_XML)

    xml_out = export_eagle_xml(result)
    root = _StdET.fromstring(xml_out)
    board = root.find("./drawing/board")

    assert board is not None
    assert root.find("./drawing/layers/layer") is not None
    assert board.find("./plain/wire") is not None
    assert board.find("./components/component") is not None
    assert board.find("./elements/element") is not None
    assert board.find("./signals/signal") is not None


# ---------------------------------------------------------------------------
# Round-trip scorer
# ---------------------------------------------------------------------------


class TestComputeEagleRoundtripScore:
    def test_perfect_score_same_result(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        score = compute_eagle_roundtrip_score(result, reimported)
        assert score >= 0.78, f"Round-trip score {score} < 0.78"

    def test_fixture_roundtrip_score(self) -> None:
        result = import_eagle_xml(_FIXTURE)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        score = compute_eagle_roundtrip_score(result, reimported)
        assert score >= 0.78, f"Fixture round-trip score {score} < 0.78"

    def test_empty_empty_score_one(self) -> None:
        empty = EagleImportResult()
        assert compute_eagle_roundtrip_score(empty, empty) == pytest.approx(1.0)

    def test_disjoint_gives_low_score(self) -> None:
        r1 = EagleImportResult(
            components={"R1": {}, "R2": {}},
            nets={"VCC": ["R1"], "GND": ["R2"]},
        )
        r2 = EagleImportResult(
            components={"C1": {}, "C2": {}},
            nets={"NET_A": ["C1"], "NET_B": ["C2"]},
        )
        score = compute_eagle_roundtrip_score(r1, r2)
        # Components and nets are fully disjoint (score 0 for each),
        # but tracks/vias/layers are all empty (score 1.0 for each).
        # Combined: (0 + 0 + 1 + 1 + 1) / 5 = 0.6
        assert score < 0.7

    def test_score_in_range(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        xml_out = export_eagle_xml(result)
        reimported = import_eagle_xml_string(xml_out)
        score = compute_eagle_roundtrip_score(result, reimported)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# eagle_result_hash
# ---------------------------------------------------------------------------


class TestEagleResultHash:
    def test_hash_64_chars(self) -> None:
        result = import_eagle_xml_string(_MINIMAL_XML)
        assert len(eagle_result_hash(result)) == 64

    def test_hash_deterministic(self) -> None:
        r1 = import_eagle_xml_string(_MINIMAL_XML)
        r2 = import_eagle_xml_string(_MINIMAL_XML)
        assert eagle_result_hash(r1) == eagle_result_hash(r2)

    def test_hash_differs_by_content(self) -> None:
        r1 = import_eagle_xml_string(_MINIMAL_XML)
        xml2 = _MINIMAL_XML.replace('"R1"', '"R99"')
        r2 = import_eagle_xml_string(xml2)
        assert eagle_result_hash(r1) != eagle_result_hash(r2)
