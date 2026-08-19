"""Tests for EasyEDA Standard format reader/writer (issue #134).

Covers all acceptance criteria:
* Reader handles minimal schematics, degradation recording, malformed input.
* Writer is deterministic, produces valid JSON, and is round-trip importable.
* Fidelity computation returns valid Jaccard scores.
* Security guards reject oversized input.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.core.models import Component, Design, DesignMeta, Net, NetNode
from zaptrace.eda.easyeda_std import (
    MAX_JSON_BYTES,
    EasyEdaStdComponent,
    EasyEdaStdDegradationRecord,
    EasyEdaStdNet,
    EasyEdaStdProject,
    EasyEdaStdWriteReport,
    _decode_source,
    _extract_section,
    _jaccard,
    _parse_component,
    _parse_net,
    _populate_project_section,
    compute_easyeda_std_fidelity,
    easyeda_std_project_to_design,
    read_easyeda_std_json,
    write_easyeda_std_json,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "easyeda_std"
_MINIMAL_FIXTURE = _FIXTURE_DIR / "minimal_schematic.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_doc() -> dict:
    """Return the canonical minimal document dict."""
    return {
        "head": {
            "docType": "1",
            "editorVersion": "6.5.40",
            "c_para": {"sourceProvenance": "CC0-1.0"},
        },
        "schematic": {
            "components": [
                {"id": "gge001", "ref": "R1", "value": "10k", "packageName": "R_0402", "x": 100.0, "y": 200.0},
                {"id": "gge002", "ref": "C1", "value": "100nF", "packageName": "C_0402", "x": 150.0, "y": 200.0},
                {"id": "gge003", "ref": "D1", "value": "1N4148", "packageName": "SOD-323", "x": 200.0, "y": 200.0},
            ],
            "nets": [
                {"id": "net001", "name": "VCC", "pins": [{"componentId": "gge001", "pinNumber": "1"}]},
                {"id": "net002", "name": "GND", "pins": [{"componentId": "gge001", "pinNumber": "2"}]},
            ],
            "wires": [{"id": "wire001", "strokeColor": "#000", "points": [[100.0, 180.0], [150.0, 180.0]]}],
            "shapes": [{"type": "~RECT~10~10~90~90~", "data": "~RECT~10~10~90~90~"}],
        },
    }


def _make_design(
    comp_ids: list[str] | None = None,
    net_ids: list[str] | None = None,
) -> Design:
    """Build a minimal Design with optional component/net IDs."""
    comp_ids = comp_ids or ["c1", "c2"]
    net_ids = net_ids or ["n1"]
    components = {
        cid: Component(id=cid, ref=cid.upper(), type="component", value="1k", footprint="R_0402") for cid in comp_ids
    }
    nets = {
        nid: Net(
            id=nid,
            name=nid.upper(),
            nodes=[NetNode(component_ref=comp_ids[0], pin_name="1")],
        )
        for nid in net_ids
    }
    return Design(meta=DesignMeta(name="test"), components=components, nets=nets)


# ---------------------------------------------------------------------------
# Fixture tests
# ---------------------------------------------------------------------------


def test_fixture_file_exists():
    assert _MINIMAL_FIXTURE.exists(), f"Fixture not found: {_MINIMAL_FIXTURE}"


def test_fixture_is_valid_json():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert isinstance(data, dict)


def test_fixture_has_head():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert "head" in data
    assert "editorVersion" in data["head"]


def test_fixture_has_three_components():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert len(data["schematic"]["components"]) == 3


def test_fixture_has_two_nets():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert len(data["schematic"]["nets"]) == 2


def test_fixture_has_wire():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert len(data["schematic"]["wires"]) >= 1


def test_fixture_has_tilde_shape():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    shapes = data["schematic"]["shapes"]
    assert len(shapes) >= 1
    # At least one shape has a tilde-prefixed type
    assert any("~" in str(s.get("type", "")) for s in shapes)


def test_fixture_provenance_cc0():
    data = json.loads(_MINIMAL_FIXTURE.read_text())
    assert data["head"]["c_para"]["sourceProvenance"] == "CC0-1.0"


# ---------------------------------------------------------------------------
# Reader — minimal schematic
# ---------------------------------------------------------------------------


def test_read_minimal_fixture():
    project = read_easyeda_std_json(_MINIMAL_FIXTURE.read_text())
    assert isinstance(project, EasyEdaStdProject)
    assert len(project.components) == 3
    assert len(project.nets) == 2


def test_read_format_version():
    project = read_easyeda_std_json(_minimal_doc())
    assert project.format_version == "6.5.40"


def test_read_component_fields():
    project = read_easyeda_std_json(_minimal_doc())
    r1 = next(c for c in project.components if c.ref == "R1")
    assert r1.id == "gge001"
    assert r1.value == "10k"
    assert r1.package == "R_0402"
    assert r1.x == pytest.approx(100.0)
    assert r1.y == pytest.approx(200.0)


def test_read_net_fields():
    project = read_easyeda_std_json(_minimal_doc())
    vcc = next(n for n in project.nets if n.name == "VCC")
    assert vcc.id == "net001"
    assert len(vcc.pins) == 1
    assert vcc.pins[0]["componentId"] == "gge001"
    assert vcc.pins[0]["pinNumber"] == "1"


def test_read_wire_creates_degradation():
    project = read_easyeda_std_json(_minimal_doc())
    wire_records = [d for d in project.degradation if d.record_type == "WIRE"]
    assert len(wire_records) == 1


def test_read_shape_creates_degradation():
    project = read_easyeda_std_json(_minimal_doc())
    shape_records = [d for d in project.degradation if "SHAPE" in d.record_type or "~" in d.record_type]
    assert len(shape_records) >= 1


def test_read_from_bytes():
    raw = json.dumps(_minimal_doc()).encode("utf-8")
    project = read_easyeda_std_json(raw)
    assert len(project.components) == 3


def test_read_from_dict():
    project = read_easyeda_std_json(_minimal_doc())
    assert len(project.components) == 3


def test_read_pcb_key_alias():
    doc = {
        "head": {"editorVersion": "6.5.40", "c_para": {}},
        "PCB": {
            "components": [{"id": "fp1", "ref": "U1", "value": "MCU", "packageName": "QFN", "x": 0.0, "y": 0.0}],
            "nets": [],
        },
    }
    project = read_easyeda_std_json(doc)
    assert len(project.components) == 1


def test_read_tilde_shape_string():
    doc = {
        "head": {"editorVersion": "6.5.40", "c_para": {}},
        "schematic": {
            "components": [],
            "nets": [],
            "wires": [],
            "shapes": ["~WIRE~100~200~150~200"],
        },
    }
    project = read_easyeda_std_json(doc)
    tilde = [d for d in project.degradation if d.record_type == "TILDE_SHAPE"]
    assert len(tilde) == 1


def test_read_multiple_nets_and_pins():
    doc = _minimal_doc()
    doc["schematic"]["nets"] = [
        {
            "id": "n1",
            "name": "VCC",
            "pins": [
                {"componentId": "gge001", "pinNumber": "1"},
                {"componentId": "gge002", "pinNumber": "1"},
            ],
        }
    ]
    project = read_easyeda_std_json(doc)
    assert len(project.nets[0].pins) == 2


def test_populate_project_section_preserves_record_order():
    project = EasyEdaStdProject()
    section = {
        "components": [
            {"id": "c1", "ref": "R1"},
            {"ref": "missing-id"},
        ],
        "nets": [
            {"id": "n1", "name": "VCC"},
            {"id": "missing-name"},
        ],
        "wires": ["wire-record"],
        "shapes": ["~WIRE~0~0~1~1", 7],
    }

    _populate_project_section(project, section)

    assert [component.id for component in project.components] == ["c1"]
    assert [net.id for net in project.nets] == ["n1"]
    assert [record.record_type for record in project.degradation] == [
        "COMPONENT_MISSING_ID",
        "NET_MISSING_FIELD",
        "WIRE",
        "TILDE_SHAPE",
        "UNKNOWN_SHAPE",
    ]


def test_json_array_root_creates_degradation():
    project = read_easyeda_std_json("[1, 2, 3]")

    assert [record.record_type for record in project.degradation] == ["NON_OBJECT_ROOT"]


# ---------------------------------------------------------------------------
# Reader — degradation recording
# ---------------------------------------------------------------------------


def test_degradation_on_missing_section():
    doc = {"head": {"editorVersion": "6.5.40", "c_para": {}}}
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "MISSING_SECTION" in types


def test_degradation_on_unsupported_version():
    doc = _minimal_doc()
    doc["head"]["editorVersion"] = "99.0.0"
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "UNSUPPORTED_VERSION" in types


def test_degradation_on_malformed_head():
    doc = _minimal_doc()
    doc["head"] = "not-a-dict"
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "MALFORMED_HEAD" in types


def test_degradation_on_component_missing_id():
    doc = _minimal_doc()
    doc["schematic"]["components"] = [{"ref": "R1", "value": "10k"}]
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "COMPONENT_MISSING_ID" in types
    assert len(project.components) == 0


def test_degradation_on_non_object_component():
    doc = _minimal_doc()
    doc["schematic"]["components"] = ["not-a-dict"]
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "NON_OBJECT_COMPONENT" in types


def test_degradation_on_net_missing_field():
    doc = _minimal_doc()
    doc["schematic"]["nets"] = [{"id": "n1"}]  # missing name
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "NET_MISSING_FIELD" in types


def test_degradation_on_non_object_net():
    doc = _minimal_doc()
    doc["schematic"]["nets"] = [42]
    project = read_easyeda_std_json(doc)
    types = {d.record_type for d in project.degradation}
    assert "NON_OBJECT_NET" in types


def test_degradation_record_has_document():
    doc = _minimal_doc()
    doc["schematic"]["components"] = [{"ref": "R1"}]
    project = read_easyeda_std_json(doc)
    err = next(d for d in project.degradation if d.record_type == "COMPONENT_MISSING_ID")
    assert err.document == "schematic.components"


def test_degradation_record_has_severity():
    doc = _minimal_doc()
    doc["head"]["editorVersion"] = "99.0.0"
    project = read_easyeda_std_json(doc)
    ver_rec = next(d for d in project.degradation if d.record_type == "UNSUPPORTED_VERSION")
    assert ver_rec.severity == "info"


def test_degradation_to_dict():
    rec = EasyEdaStdDegradationRecord(record_type="TEST", document="doc", severity="info", raw="raw")
    d = rec.to_dict()
    assert d["record_type"] == "TEST"
    assert d["document"] == "doc"
    assert d["severity"] == "info"
    assert d["raw"] == "raw"


# ---------------------------------------------------------------------------
# Reader — security guards
# ---------------------------------------------------------------------------


def test_reject_oversized_bytes():
    oversized = b"x" * (MAX_JSON_BYTES + 1)
    with pytest.raises(ValueError, match="size limit"):
        read_easyeda_std_json(oversized)


def test_reject_oversized_str():
    oversized = "x" * (MAX_JSON_BYTES + 1)
    with pytest.raises(ValueError, match="size limit"):
        read_easyeda_std_json(oversized)


def test_reject_malformed_json_string():
    with pytest.raises(ValueError, match="malformed JSON"):
        read_easyeda_std_json("{not valid json}")


def test_reject_malformed_json_bytes():
    with pytest.raises(ValueError, match="malformed JSON"):
        read_easyeda_std_json(b"{bad}")


def test_reject_wrong_source_type():
    with pytest.raises(TypeError):
        read_easyeda_std_json(12345)  # type: ignore[arg-type]


def test_non_object_root_creates_degradation():
    """A JSON array at root level produces a degradation record, not a crash."""
    project = read_easyeda_std_json([1, 2, 3])  # type: ignore[arg-type]
    types = {d.record_type for d in project.degradation}
    assert "NON_OBJECT_ROOT" in types


# ---------------------------------------------------------------------------
# Writer — structure and determinism
# ---------------------------------------------------------------------------


def test_writer_returns_tuple():
    design = _make_design()
    result = write_easyeda_std_json(design)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_writer_returns_str_and_report():
    design = _make_design()
    json_str, report = write_easyeda_std_json(design)
    assert isinstance(json_str, str)
    assert isinstance(report, EasyEdaStdWriteReport)


def test_writer_output_is_valid_json():
    design = _make_design()
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    assert isinstance(doc, dict)


def test_writer_has_head():
    design = _make_design()
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    assert "head" in doc
    assert "editorVersion" in doc["head"]


def test_writer_has_schematic_section():
    design = _make_design()
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    assert "schematic" in doc


def test_writer_embeds_project_name():
    design = _make_design()
    json_str, _ = write_easyeda_std_json(design, project_name="MyBoard")
    doc = json.loads(json_str)
    assert doc["head"]["c_para"]["name"] == "MyBoard"


def test_writer_embeds_provenance():
    design = _make_design()
    json_str, _ = write_easyeda_std_json(design, source_provenance="CC0-1.0")
    doc = json.loads(json_str)
    assert doc["head"]["c_para"]["sourceProvenance"] == "CC0-1.0"


def test_writer_component_order_deterministic():
    """Same design → same component order on repeated calls."""
    design = _make_design(comp_ids=["z_comp", "a_comp", "m_comp"])
    out1, _ = write_easyeda_std_json(design)
    out2, _ = write_easyeda_std_json(design)
    assert out1 == out2


def test_writer_components_sorted_by_id():
    design = _make_design(comp_ids=["z_comp", "a_comp", "m_comp"])
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    ids = [c["id"] for c in doc["schematic"]["components"]]
    assert ids == sorted(ids)


def test_writer_nets_sorted_by_id():
    design = _make_design(comp_ids=["c1"], net_ids=["z_net", "a_net", "m_net"])
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    ids = [n["id"] for n in doc["schematic"]["nets"]]
    assert ids == sorted(ids)


def test_writer_accepted_when_no_unsupported():
    design = _make_design()
    _, report = write_easyeda_std_json(design)
    assert report.accepted is True
    assert report.unsupported_count == 0


def test_writer_component_fields():
    design = _make_design(comp_ids=["c1"])
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    comp = doc["schematic"]["components"][0]
    assert comp["id"] == "c1"
    assert comp["ref"] == "C1"
    assert "packageName" in comp


def test_writer_net_pins_present():
    design = _make_design(comp_ids=["c1", "c2"], net_ids=["n1"])
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    assert len(doc["schematic"]["nets"]) == 1
    assert len(doc["schematic"]["nets"][0]["pins"]) >= 1


def test_write_report_to_dict():
    report = EasyEdaStdWriteReport(unsupported_count=3)
    d = report.to_dict()
    assert d["unsupported_count"] == 3
    assert d["accepted"] is False


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_round_trip_components():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    json_str, _ = write_easyeda_std_json(design)
    rt_project = read_easyeda_std_json(json_str)
    orig_refs = {c.ref for c in project.components}
    rt_refs = {c.ref for c in rt_project.components}
    assert orig_refs == rt_refs


def test_round_trip_nets():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    json_str, _ = write_easyeda_std_json(design)
    rt_project = read_easyeda_std_json(json_str)
    orig_names = {n.name for n in project.nets}
    rt_names = {n.name for n in rt_project.nets}
    assert orig_names == rt_names


def test_round_trip_is_valid_json():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    json_str, _ = write_easyeda_std_json(design)
    doc = json.loads(json_str)
    assert "head" in doc
    assert "schematic" in doc


# ---------------------------------------------------------------------------
# easyeda_std_project_to_design
# ---------------------------------------------------------------------------


def test_project_to_design_returns_design():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    assert isinstance(design, Design)


def test_project_to_design_component_count():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    assert len(design.components) == 3


def test_project_to_design_net_count():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    assert len(design.nets) == 2


def test_project_to_design_custom_name():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project, name="my_board")
    assert design.meta.name == "my_board"


def test_project_to_design_position_preserved():
    project = read_easyeda_std_json(_minimal_doc())
    design = easyeda_std_project_to_design(project)
    r1 = design.components["gge001"]
    assert r1.position == pytest.approx((100.0, 200.0))


# ---------------------------------------------------------------------------
# Fidelity
# ---------------------------------------------------------------------------


def test_compute_fidelity_returns_dict():
    design = _make_design()
    result = compute_easyeda_std_fidelity(design)
    assert isinstance(result, dict)


def test_compute_fidelity_keys():
    design = _make_design()
    result = compute_easyeda_std_fidelity(design)
    assert "component_jaccard" in result
    assert "net_jaccard" in result
    assert "overall_score" in result
    assert "degradation_report" in result


def test_compute_fidelity_perfect_score():
    """A design with only supported constructs should round-trip perfectly."""
    design = _make_design()
    result = compute_easyeda_std_fidelity(design)
    assert result["component_jaccard"] == pytest.approx(1.0)
    assert result["net_jaccard"] == pytest.approx(1.0)
    assert result["overall_score"] == pytest.approx(1.0)


def test_compute_fidelity_score_range():
    design = _make_design()
    result = compute_easyeda_std_fidelity(design)
    assert 0.0 <= result["component_jaccard"] <= 1.0
    assert 0.0 <= result["net_jaccard"] <= 1.0
    assert 0.0 <= result["overall_score"] <= 1.0


def test_compute_fidelity_degradation_report_is_list():
    design = _make_design()
    result = compute_easyeda_std_fidelity(design)
    assert isinstance(result["degradation_report"], list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def test_jaccard_identical():
    assert _jaccard({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)


def test_jaccard_disjoint():
    assert _jaccard({"a"}, {"b"}) == pytest.approx(0.0)


def test_jaccard_partial():
    assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_jaccard_both_empty():
    assert _jaccard(set(), set()) == pytest.approx(1.0)


def test_extract_section_schematic_key():
    doc = {"schematic": {"components": []}}
    assert _extract_section(doc) == {"components": []}


def test_extract_section_pcb_key():
    doc = {"PCB": {"components": []}}
    assert _extract_section(doc) == {"components": []}


def test_extract_section_missing():
    doc = {"head": {}}
    assert _extract_section(doc) == {}


def test_decode_source_dict_passthrough():
    d = {"key": "val"}
    assert _decode_source(d) == d


def test_decode_source_bytes():
    raw = b'{"a": 1}'
    assert _decode_source(raw) == {"a": 1}


def test_decode_source_str():
    assert _decode_source('{"a": 1}') == {"a": 1}


def test_parse_component_valid():
    raw = {"id": "c1", "ref": "R1", "value": "10k", "packageName": "R_0402", "x": 1.0, "y": 2.0}
    comp, err = _parse_component(raw, "test")
    assert comp is not None
    assert err is None
    assert comp.id == "c1"


def test_parse_component_missing_id():
    raw = {"ref": "R1", "value": "10k"}
    comp, err = _parse_component(raw, "test")
    assert comp is None
    assert err is not None
    assert err.record_type == "COMPONENT_MISSING_ID"


def test_parse_net_valid():
    raw = {"id": "n1", "name": "VCC", "pins": [{"componentId": "c1", "pinNumber": "1"}]}
    net, err = _parse_net(raw, "test")
    assert net is not None
    assert err is None
    assert net.name == "VCC"


def test_parse_net_missing_name():
    raw = {"id": "n1"}
    net, err = _parse_net(raw, "test")
    assert net is None
    assert err is not None
    assert err.record_type == "NET_MISSING_FIELD"


def test_easyeda_std_component_to_dict():
    c = EasyEdaStdComponent(id="c1", ref="R1", value="10k", package="R_0402", x=1.0, y=2.0)
    d = c.to_dict()
    assert d == {"id": "c1", "ref": "R1", "value": "10k", "package": "R_0402", "x": 1.0, "y": 2.0}


def test_easyeda_std_net_to_dict():
    n = EasyEdaStdNet(id="n1", name="VCC", pins=[{"componentId": "c1", "pinNumber": "1"}])
    d = n.to_dict()
    assert d["id"] == "n1"
    assert d["name"] == "VCC"
    assert len(d["pins"]) == 1


def test_easyeda_std_project_to_dict():
    p = EasyEdaStdProject(format_version="6.5.40")
    d = p.to_dict()
    assert d["format_version"] == "6.5.40"
    assert d["component_count"] == 0
    assert d["net_count"] == 0
