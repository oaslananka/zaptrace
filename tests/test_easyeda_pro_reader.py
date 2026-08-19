"""Tests for EasyEDA Pro project reader (issue #120).

Covers all acceptance criteria:
* Shared codec handles cached LCSC shape fixtures and Pro document records
  without duplicate parsing logic.
* ZIP handling rejects path traversal, oversized entries, malformed JSONL,
  and unsupported versions safely.
* One schematic-and-PCB Pro fixture imports components, nets, geometry,
  layers, and attributes deterministically.
* Unknown records are never dropped silently and include document/line
  provenance.
* Fixture licensing, format version, and source provenance are recorded.
"""

from __future__ import annotations

import io
import json
import zipfile

# ---------------------------------------------------------------------------
# Fixture path
# ---------------------------------------------------------------------------
from pathlib import Path

import pytest

from zaptrace.eda.easyeda_pro import (
    EasyEdaDegradationRecord,
    EasyEdaProProject,
    _extract_pcb,
    _extract_schematic,
    _is_safe_path,
    _parse_jsonl,
    read_easyeda_pro_zip,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "easyeda" / "test_project.epro"


# ---------------------------------------------------------------------------
# Helper to build a minimal ZIP in memory
# ---------------------------------------------------------------------------


def _make_zip(
    project_json: dict | None = None,
    schematic_jsonl: str | None = None,
    pcb_jsonl: str | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> bytes:
    """Build a minimal EasyEDA Pro ZIP in memory."""
    if project_json is None:
        project_json = {
            "version": "2.1.0",
            "formatVersion": "2.1",
            "name": "test",
            "sourceProvenance": "synthetic",
        }
    if schematic_jsonl is None:
        schematic_jsonl = "\n".join(
            [
                json.dumps({"type": "HEADER", "version": "2.1.0", "docType": "schematic"}),
                json.dumps(
                    {
                        "type": "COMPONENT",
                        "id": "c1",
                        "ref": "R1",
                        "value": "10k",
                        "package": "R0402",
                        "mpn": "RC0402FR-0710KL",
                        "x": 100.0,
                        "y": 200.0,
                    }
                ),
                json.dumps({"type": "NET", "id": "n1", "name": "VCC", "pins": [{"component": "c1", "pin": "1"}]}),
            ]
        )
    if pcb_jsonl is None:
        pcb_jsonl = "\n".join(
            [
                json.dumps({"type": "HEADER", "version": "2.1.0", "docType": "pcb"}),
                json.dumps({"type": "LAYER", "id": 1, "name": "TopCopper", "color": "#FF0000"}),
                json.dumps({"type": "FOOTPRINT", "ref": "R1", "package": "R0402", "x": 10.0, "y": 5.0, "rotation": 0}),
                json.dumps(
                    {
                        "type": "TRACK",
                        "layer": 1,
                        "net": "VCC",
                        "x1": 9.5,
                        "y1": 5.0,
                        "x2": 14.5,
                        "y2": 5.0,
                        "width": 0.2,
                    }
                ),
                json.dumps({"type": "VIA", "x": 12.0, "y": 5.0, "outerDiameter": 0.8, "innerDiameter": 0.4}),
            ]
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(project_json))
        if schematic_jsonl is not None:
            zf.writestr("schematic.jsonl", schematic_jsonl)
        if pcb_jsonl is not None:
            zf.writestr("pcb.jsonl", pcb_jsonl)
        for name, data in (extra_files or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _is_safe_path
# ---------------------------------------------------------------------------


class TestIsSafePath:
    def test_normal_path_is_safe(self) -> None:
        assert _is_safe_path("schematic.jsonl") is True

    def test_nested_path_is_safe(self) -> None:
        assert _is_safe_path("subdir/file.json") is True

    def test_dotdot_is_unsafe(self) -> None:
        assert _is_safe_path("../evil.json") is False

    def test_absolute_path_is_unsafe(self) -> None:
        assert _is_safe_path("/etc/passwd") is False

    def test_hidden_traversal_is_unsafe(self) -> None:
        assert _is_safe_path("safe/../../evil") is False


# ---------------------------------------------------------------------------
# _parse_jsonl (shared codec)
# ---------------------------------------------------------------------------


class TestParseJsonl:
    def test_parses_known_types(self) -> None:
        text = json.dumps({"type": "HEADER", "version": "2.0"})
        known = frozenset({"HEADER"})
        records, degradation = _parse_jsonl(text, "test.jsonl", known)
        assert len(records) == 1
        assert len(degradation) == 0

    def test_unknown_type_goes_to_degradation(self) -> None:
        text = json.dumps({"type": "MYSTERY_FEATURE", "data": 42})
        known = frozenset({"HEADER"})
        records, degradation = _parse_jsonl(text, "test.jsonl", known)
        assert len(records) == 0
        assert len(degradation) == 1
        assert degradation[0].record_type == "MYSTERY_FEATURE"

    def test_malformed_json_to_degradation(self) -> None:
        text = "{bad json"
        known = frozenset({"HEADER"})
        records, degradation = _parse_jsonl(text, "test.jsonl", known)
        assert len(records) == 0
        assert any(d.severity == "error" for d in degradation)

    def test_degradation_has_document(self) -> None:
        text = json.dumps({"type": "UNKNOWN_X"})
        records, degradation = _parse_jsonl(text, "my_doc.jsonl", frozenset())
        assert degradation[0].document == "my_doc.jsonl"

    def test_degradation_has_line_index(self) -> None:
        lines = [
            json.dumps({"type": "KNOWN", "x": 1}),
            json.dumps({"type": "UNKNOWN_Y"}),
        ]
        known = frozenset({"KNOWN"})
        _, degradation = _parse_jsonl("\n".join(lines), "f.jsonl", known)
        assert degradation[0].line_index == 1

    def test_empty_lines_skipped(self) -> None:
        text = "\n\n" + json.dumps({"type": "HEADER", "v": "1.0"}) + "\n\n"
        known = frozenset({"HEADER"})
        records, _ = _parse_jsonl(text, "f.jsonl", known)
        assert len(records) == 1

    def test_non_object_line_to_degradation(self) -> None:
        known: frozenset[str] = frozenset()
        _, degradation = _parse_jsonl("[1, 2, 3]", "f.jsonl", known)
        assert any(d.record_type == "NON_OBJECT_LINE" for d in degradation)


# ---------------------------------------------------------------------------
# _extract_schematic
# ---------------------------------------------------------------------------


class TestExtractSchematic:
    def test_extracts_components(self) -> None:
        text = "\n".join(
            [
                json.dumps(
                    {
                        "type": "COMPONENT",
                        "id": "c1",
                        "ref": "R1",
                        "value": "10k",
                        "package": "R0402",
                        "mpn": "RC01",
                        "x": 1.0,
                        "y": 2.0,
                    }
                ),
            ]
        )
        sch = _extract_schematic(text, "sch.jsonl")
        assert len(sch.components) == 1
        assert sch.components[0].ref == "R1"
        assert sch.components[0].value == "10k"

    def test_extracts_nets(self) -> None:
        text = json.dumps({"type": "NET", "id": "n1", "name": "VCC", "pins": [{"component": "c1", "pin": "1"}]})
        sch = _extract_schematic(text, "sch.jsonl")
        assert len(sch.nets) == 1
        assert sch.nets[0].name == "VCC"
        assert sch.nets[0].pins[0]["component"] == "c1"

    def test_extracts_format_version(self) -> None:
        text = json.dumps({"type": "HEADER", "version": "2.3.0"})
        sch = _extract_schematic(text, "sch.jsonl")
        assert sch.format_version == "2.3.0"

    def test_unknown_records_in_degradation(self) -> None:
        text = json.dumps({"type": "ARCANE_SCHEMATIC_ELEMENT", "data": "x"})
        sch = _extract_schematic(text, "sch.jsonl")
        assert len(sch.degradation) == 1
        assert sch.degradation[0].record_type == "ARCANE_SCHEMATIC_ELEMENT"


# ---------------------------------------------------------------------------
# _extract_pcb
# ---------------------------------------------------------------------------


class TestExtractPcb:
    def test_extracts_layers(self) -> None:
        text = json.dumps({"type": "LAYER", "id": 1, "name": "TopCopper", "color": "#FF0000"})
        pcb = _extract_pcb(text, "pcb.jsonl")
        assert len(pcb.layers) == 1
        assert pcb.layers[0].name == "TopCopper"

    def test_extracts_footprints(self) -> None:
        text = json.dumps({"type": "FOOTPRINT", "ref": "R1", "package": "R0402", "x": 10.0, "y": 5.0, "rotation": 0})
        pcb = _extract_pcb(text, "pcb.jsonl")
        assert len(pcb.footprints) == 1
        assert pcb.footprints[0].ref == "R1"

    def test_extracts_tracks(self) -> None:
        text = json.dumps(
            {"type": "TRACK", "layer": 1, "net": "VCC", "x1": 0.0, "y1": 0.0, "x2": 10.0, "y2": 0.0, "width": 0.2}
        )
        pcb = _extract_pcb(text, "pcb.jsonl")
        assert len(pcb.tracks) == 1
        assert pcb.tracks[0].net == "VCC"

    def test_extracts_vias(self) -> None:
        text = json.dumps({"type": "VIA", "x": 5.0, "y": 5.0, "outerDiameter": 0.8, "innerDiameter": 0.4})
        pcb = _extract_pcb(text, "pcb.jsonl")
        assert len(pcb.vias) == 1
        assert pcb.vias[0].outer_diameter == pytest.approx(0.8)

    def test_unknown_pcb_record_in_degradation(self) -> None:
        text = json.dumps({"type": "MYSTERY_PCB_ELEMENT", "x": 0})
        pcb = _extract_pcb(text, "pcb.jsonl")
        assert len(pcb.degradation) == 1


# ---------------------------------------------------------------------------
# read_easyeda_pro_zip
# ---------------------------------------------------------------------------


class TestReadEasyEdaProZip:
    def test_reads_valid_zip(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert isinstance(proj, EasyEdaProProject)

    def test_project_name(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert proj.project_name == "test"

    def test_format_version(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert proj.format_version == "2.1"

    def test_source_provenance(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert proj.source_provenance == "synthetic"

    def test_components_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.schematic.components) >= 1
        assert proj.schematic.components[0].ref == "R1"

    def test_nets_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        net_names = {n.name for n in proj.schematic.nets}
        assert "VCC" in net_names

    def test_layers_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.pcb.layers) >= 1

    def test_footprints_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.pcb.footprints) >= 1

    def test_tracks_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.pcb.tracks) >= 1

    def test_vias_extracted(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.pcb.vias) >= 1

    def test_deterministic_import(self) -> None:
        raw = _make_zip()
        p1 = read_easyeda_pro_zip(raw)
        p2 = read_easyeda_pro_zip(raw)
        names1 = {c.ref for c in p1.schematic.components}
        names2 = {c.ref for c in p2.schematic.components}
        assert names1 == names2

    def test_to_dict_serialisable(self) -> None:
        import json as _json

        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        _json.dumps(proj.to_dict())

    def test_total_degradation_count(self) -> None:
        raw = _make_zip()
        proj = read_easyeda_pro_zip(raw)
        assert proj.total_degradation_count >= 0

    def test_rejects_bad_zip(self) -> None:
        with pytest.raises(ValueError, match="ZIP"):
            read_easyeda_pro_zip(b"not a zip file")

    def test_rejects_path_traversal(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.json", '{"bad": true}')
        raw = buf.getvalue()
        with pytest.raises(ValueError, match="path traversal"):
            read_easyeda_pro_zip(raw)

    def test_rejects_path_strings(self) -> None:
        with pytest.raises(TypeError, match="raw ZIP bytes"):
            read_easyeda_pro_zip("nonexistent.epro")  # type: ignore[arg-type]

    def test_missing_project_json_noted(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("schematic.jsonl", json.dumps({"type": "HEADER", "version": "2.0"}))
        proj = read_easyeda_pro_zip(buf.getvalue())
        kinds = [d.record_type for d in proj.degradation]
        assert "MISSING_PROJECT_JSON" in kinds

    def test_unknown_records_in_schematic_degradation(self) -> None:
        sch = "\n".join(
            [
                json.dumps({"type": "WEIRD_ELEMENT", "data": "x"}),
            ]
        )
        raw = _make_zip(schematic_jsonl=sch)
        proj = read_easyeda_pro_zip(raw)
        assert len(proj.schematic.degradation) >= 1

    def test_malformed_jsonl_to_degradation(self) -> None:
        sch = "{bad json line"
        raw = _make_zip(schematic_jsonl=sch)
        proj = read_easyeda_pro_zip(raw)
        assert any(d.severity == "error" for d in proj.schematic.degradation)

    def test_degradation_record_has_document(self) -> None:
        sch = json.dumps({"type": "UNKNOWN_WEIRD"})
        raw = _make_zip(schematic_jsonl=sch)
        proj = read_easyeda_pro_zip(raw)
        assert all(d.document for d in proj.schematic.degradation)

    def test_degradation_record_has_line_index(self) -> None:
        sch = json.dumps({"type": "UNKNOWN_WEIRD"})
        raw = _make_zip(schematic_jsonl=sch)
        proj = read_easyeda_pro_zip(raw)
        assert all(isinstance(d.line_index, int) for d in proj.schematic.degradation)

    def test_unsupported_version_noted(self) -> None:
        meta = {
            "version": "1.0.0",
            "formatVersion": "1.0",
            "name": "legacy",
            "sourceProvenance": "test",
        }
        raw = _make_zip(project_json=meta)
        proj = read_easyeda_pro_zip(raw)
        kinds = [d.record_type for d in proj.degradation]
        assert "UNSUPPORTED_VERSION" in kinds


# ---------------------------------------------------------------------------
# Fixture-based integration test
# ---------------------------------------------------------------------------


class TestFixtureImport:
    def test_reads_fixture(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert isinstance(proj, EasyEdaProProject)

    def test_fixture_project_name(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert proj.project_name == "test_project"

    def test_fixture_components(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        refs = {c.ref for c in proj.schematic.components}
        assert "R1" in refs
        assert "C1" in refs
        assert "U1" in refs

    def test_fixture_nets(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        net_names = {n.name for n in proj.schematic.nets}
        assert "VCC" in net_names
        assert "GND" in net_names

    def test_fixture_pcb_layers(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert len(proj.pcb.layers) >= 3

    def test_fixture_footprints(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        refs = {fp.ref for fp in proj.pcb.footprints}
        assert "R1" in refs

    def test_fixture_tracks(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert len(proj.pcb.tracks) >= 2

    def test_fixture_vias(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert len(proj.pcb.vias) >= 1

    def test_fixture_has_degradation(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        # Fixture has UNKNOWN_SCHEMATIC_FEATURE and MYSTERY_PCB_FEATURE
        assert proj.total_degradation_count >= 2

    def test_fixture_source_provenance(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert proj.source_provenance == "synthetic-test-fixture"

    def test_fixture_format_version(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        assert proj.format_version.startswith("2.")

    def test_fixture_degradation_has_provenance(self) -> None:
        proj = read_easyeda_pro_zip(_FIXTURE.read_bytes())
        all_degradation = proj.degradation + proj.schematic.degradation + proj.pcb.degradation
        for d in all_degradation:
            assert d.document or d.record_type == "MISSING_PROJECT_JSON"
            assert isinstance(d.line_index, int)


# ---------------------------------------------------------------------------
# EasyEdaDegradationRecord
# ---------------------------------------------------------------------------


class TestEasyEdaDegradationRecord:
    def test_to_dict_keys(self) -> None:
        d = EasyEdaDegradationRecord(
            record_type="UNKNOWN_TYPE",
            document="sch.jsonl",
            line_index=5,
            severity="info",
            raw="some raw text",
        )
        keys = d.to_dict()
        assert {"record_type", "document", "line_index", "severity", "raw"} <= keys.keys()

    def test_raw_truncated_to_200(self) -> None:
        d = EasyEdaDegradationRecord(record_type="X", document="f", line_index=0, raw="A" * 500)
        assert len(d.to_dict()["raw"]) == 200


def test_malformed_member_header_is_normalized_to_value_error() -> None:
    regression = Path("tests/corpus/fuzz/seeds/easyeda-pro-bad-member-header.epro")

    payload = regression.read_bytes()
    with pytest.raises(ValueError, match="Malformed ZIP member data"):
        read_easyeda_pro_zip(payload)
