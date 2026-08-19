"""Tests for EasyEDA Pro project writer (issue #121).

Covers all acceptance criteria:
* Writer output is deterministic (same design → identical bytes).
* A supported design survives write → read with documented fidelity.
* Every export emits a degradation report, including a zero-loss report.
* Unsupported elements cannot be omitted without a recorded finding.
* Golden fixtures cover schematic, PCB, footprint, and project metadata.
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from typing import Any

import pytest

from zaptrace.eda.easyeda_pro import (
    EasyEdaWriteDegradationReport,
    EasyEdaWriteFinding,
    _jaccard,
    compute_easyeda_write_fidelity,
    read_easyeda_pro_zip,
    write_easyeda_pro_zip,
)

# ---------------------------------------------------------------------------
# Minimal stub design helpers
# ---------------------------------------------------------------------------


@dataclass
class _Pin:
    component_id: str = ""
    pin: str = ""


@dataclass
class _Net:
    name: str = ""
    nodes: list[_Pin] = field(default_factory=list)


@dataclass
class _Component:
    ref: str = ""
    value: str = ""
    footprint: str = ""
    mpn: str = ""
    position: tuple[float, float] = (0.0, 0.0)


@dataclass
class _Meta:
    name: str = "TestProject"
    version: str = "1.0"
    author: str = "test-author"


@dataclass
class _Design:
    meta: _Meta = field(default_factory=_Meta)
    components: dict[str, _Component] = field(default_factory=dict)
    nets: dict[str, _Net] = field(default_factory=dict)
    blocks: list[Any] = field(default_factory=list)
    routing: Any = None
    copper_pours: dict[str, Any] = field(default_factory=dict)


def _make_design() -> _Design:
    """Build a minimal representative design."""
    d = _Design()
    d.components["c1"] = _Component(ref="R1", value="10k", footprint="0402", mpn="RMCF0402", position=(1.0, 2.0))
    d.components["c2"] = _Component(ref="C1", value="100n", footprint="0402", position=(3.0, 4.0))
    d.nets["n1"] = _Net(name="VCC", nodes=[_Pin("c1", "P1"), _Pin("c2", "P1")])
    d.nets["n2"] = _Net(name="GND", nodes=[_Pin("c1", "P2"), _Pin("c2", "P2")])
    return d


# ---------------------------------------------------------------------------
# EasyEdaWriteDegradationReport unit tests
# ---------------------------------------------------------------------------


class TestEasyEdaWriteDegradationReport:
    def test_initial_counts_zero(self) -> None:
        r = EasyEdaWriteDegradationReport()
        assert r.represented_count == 0
        assert r.transformed_count == 0
        assert r.unsupported_count == 0

    def test_accepted_when_no_unsupported(self) -> None:
        r = EasyEdaWriteDegradationReport()
        r.represented("component R1")
        assert r.accepted is True

    def test_not_accepted_when_unsupported(self) -> None:
        r = EasyEdaWriteDegradationReport()
        r.unsupported("copper pour", "not supported")
        assert r.accepted is False

    def test_counts_increment_correctly(self) -> None:
        r = EasyEdaWriteDegradationReport()
        r.represented("comp A")
        r.represented("comp B")
        r.transformed("net X", "lossy")
        r.unsupported("block", "not supported")
        assert r.represented_count == 2
        assert r.transformed_count == 1
        assert r.unsupported_count == 1

    def test_to_dict_structure(self) -> None:
        r = EasyEdaWriteDegradationReport()
        r.represented("comp R1")
        d = r.to_dict()
        assert d["represented_count"] == 1
        assert d["accepted"] is True
        assert isinstance(d["findings"], list)
        assert len(d["findings"]) == 1
        assert d["findings"][0]["category"] == "represented"
        assert d["findings"][0]["element"] == "comp R1"

    def test_finding_to_dict(self) -> None:
        f = EasyEdaWriteFinding(category="transformed", element="net VCC", detail="approximate")
        d = f.to_dict()
        assert d["category"] == "transformed"
        assert d["element"] == "net VCC"
        assert d["detail"] == "approximate"

    def test_findings_ordered(self) -> None:
        r = EasyEdaWriteDegradationReport()
        r.represented("a")
        r.transformed("b", "t")
        r.unsupported("c", "u")
        categories = [f.category for f in r.findings]
        assert categories == ["represented", "transformed", "unsupported"]


# ---------------------------------------------------------------------------
# ZIP structure tests
# ---------------------------------------------------------------------------


class TestWriteZipStructure:
    def test_returns_bytes(self) -> None:
        d = _make_design()
        raw, report = write_easyeda_pro_zip(d)
        assert isinstance(raw, bytes)
        assert len(raw) > 0

    def test_is_valid_zip(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = zf.namelist()
        assert "project.json" in names
        assert "schematic.jsonl" in names
        assert "pcb.jsonl" in names

    def test_project_json_structure(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            meta = json.loads(zf.read("project.json"))
        assert meta["name"] == "TestProject"
        assert meta["formatVersion"].startswith("2.")
        assert meta["sourceProvenance"] == "zaptrace"
        assert meta["generator"] == "zaptrace"

    def test_project_json_custom_name(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d, project_name="MyBoard")
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            meta = json.loads(zf.read("project.json"))
        assert meta["name"] == "MyBoard"

    def test_custom_source_provenance(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d, source_provenance="custom-tool")
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            meta = json.loads(zf.read("project.json"))
        assert meta["sourceProvenance"] == "custom-tool"

    def test_deterministic_output(self) -> None:
        d = _make_design()
        raw1, _ = write_easyeda_pro_zip(d)
        raw2, _ = write_easyeda_pro_zip(d)
        assert raw1 == raw2

    def test_no_unsafe_paths(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                assert not info.filename.startswith("/")
                assert ".." not in info.filename


# ---------------------------------------------------------------------------
# Schematic JSONL content tests
# ---------------------------------------------------------------------------


class TestSchematicJsonl:
    def _read_schematic(self, design: _Design) -> list[dict]:
        raw, _ = write_easyeda_pro_zip(design)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            text = zf.read("schematic.jsonl").decode()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def test_contains_header(self) -> None:
        d = _make_design()
        records = self._read_schematic(d)
        headers = [r for r in records if r.get("type") == "HEADER"]
        assert len(headers) == 1
        assert headers[0]["version"].startswith("2.")

    def test_components_written(self) -> None:
        d = _make_design()
        records = self._read_schematic(d)
        comps = [r for r in records if r.get("type") == "COMPONENT"]
        refs = {c["ref"] for c in comps}
        assert "R1" in refs
        assert "C1" in refs

    def test_component_fields(self) -> None:
        d = _make_design()
        records = self._read_schematic(d)
        r1 = next(r for r in records if r.get("ref") == "R1")
        assert r1["value"] == "10k"
        assert r1["package"] == "0402"
        assert r1["mpn"] == "RMCF0402"
        assert r1["x"] == pytest.approx(1.0)
        assert r1["y"] == pytest.approx(2.0)

    def test_nets_written(self) -> None:
        d = _make_design()
        records = self._read_schematic(d)
        nets = [r for r in records if r.get("type") == "NET"]
        net_names = {n["name"] for n in nets}
        assert "VCC" in net_names
        assert "GND" in net_names

    def test_net_pins(self) -> None:
        d = _make_design()
        records = self._read_schematic(d)
        vcc = next(r for r in records if r.get("name") == "VCC")
        assert len(vcc["pins"]) == 2
        comp_ids = {p["component"] for p in vcc["pins"]}
        assert "c1" in comp_ids

    def test_ordering_stable(self) -> None:
        d = _make_design()
        records1 = self._read_schematic(d)
        records2 = self._read_schematic(d)
        assert records1 == records2


# ---------------------------------------------------------------------------
# PCB JSONL content tests
# ---------------------------------------------------------------------------


class TestPcbJsonl:
    def _read_pcb(self, design: _Design) -> list[dict]:
        raw, _ = write_easyeda_pro_zip(design)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            text = zf.read("pcb.jsonl").decode()
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def test_contains_header(self) -> None:
        d = _make_design()
        records = self._read_pcb(d)
        assert any(r.get("type") == "HEADER" for r in records)

    def test_layers_written(self) -> None:
        d = _make_design()
        records = self._read_pcb(d)
        layers = [r for r in records if r.get("type") == "LAYER"]
        layer_names = {lyr["name"] for lyr in layers}
        assert "TopCopper" in layer_names
        assert "BottomCopper" in layer_names
        assert "BoardOutline" in layer_names

    def test_footprints_written(self) -> None:
        d = _make_design()
        records = self._read_pcb(d)
        fps = [r for r in records if r.get("type") == "FOOTPRINT"]
        refs = {f["ref"] for f in fps}
        assert "R1" in refs
        assert "C1" in refs

    def test_footprint_fields(self) -> None:
        d = _make_design()
        records = self._read_pcb(d)
        r1 = next(r for r in records if r.get("ref") == "R1")
        assert r1["package"] == "0402"
        assert r1["x"] == pytest.approx(1.0)
        assert r1["rotation"] == pytest.approx(0.0)

    def test_tracks_not_written_without_routing(self) -> None:
        d = _make_design()
        records = self._read_pcb(d)
        assert not any(r.get("type") == "TRACK" for r in records)

    def test_copper_pour_is_unsupported(self) -> None:
        d = _make_design()
        d.copper_pours["gnd_pour"] = object()
        _, report = write_easyeda_pro_zip(d)
        unsupported = [f for f in report.findings if f.category == "unsupported"]
        elements = [f.element for f in unsupported]
        assert any("copper_pour" in e for e in elements)
        assert not report.accepted


# ---------------------------------------------------------------------------
# Degradation report tests
# ---------------------------------------------------------------------------


class TestDegradationReport:
    def test_report_returned(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        assert isinstance(report, EasyEdaWriteDegradationReport)

    def test_zero_loss_design_is_accepted(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        assert report.accepted is True
        assert report.unsupported_count == 0

    def test_report_has_component_findings(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        elements = [f.element for f in report.findings]
        assert any("R1" in e for e in elements)

    def test_report_has_net_findings(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        elements = [f.element for f in report.findings]
        assert any("VCC" in e for e in elements)

    def test_empty_design_accepted(self) -> None:
        d = _Design()
        _, report = write_easyeda_pro_zip(d)
        assert report.accepted is True

    def test_to_dict_complete(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        rd = report.to_dict()
        assert "represented_count" in rd
        assert "transformed_count" in rd
        assert "unsupported_count" in rd
        assert "accepted" in rd
        assert "findings" in rd

    def test_meta_represented(self) -> None:
        d = _make_design()
        _, report = write_easyeda_pro_zip(d)
        elements = [f.element for f in report.findings]
        assert "project metadata" in elements

    def test_no_meta_transformed(self) -> None:
        class _NoMeta:
            components: dict = {}
            nets: dict = {}
            blocks: list = []
            routing = None
            copper_pours: dict = {}
            meta = None

        _, report = write_easyeda_pro_zip(_NoMeta())
        cats = {f.category for f in report.findings}
        assert "transformed" in cats


# ---------------------------------------------------------------------------
# Round-trip tests: write → read
# ---------------------------------------------------------------------------


class TestWriteReadRoundtrip:
    def test_roundtrip_components(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        read_refs = {c.ref for c in project.schematic.components}
        assert "R1" in read_refs
        assert "C1" in read_refs

    def test_roundtrip_nets(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        read_names = {n.name for n in project.schematic.nets}
        assert "VCC" in read_names
        assert "GND" in read_names

    def test_roundtrip_project_name(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d, project_name="BoardX")
        project = read_easyeda_pro_zip(raw)
        assert project.project_name == "BoardX"

    def test_roundtrip_no_degradation(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert project.total_degradation_count == 0

    def test_roundtrip_component_count(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert len(project.schematic.components) == 2

    def test_roundtrip_net_count(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert len(project.schematic.nets) == 2

    def test_roundtrip_net_pins_preserved(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        vcc = next(n for n in project.schematic.nets if n.name == "VCC")
        assert len(vcc.pins) == 2

    def test_roundtrip_layers_present(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        layer_names = {lyr.name for lyr in project.pcb.layers}
        assert "TopCopper" in layer_names

    def test_roundtrip_footprints(self) -> None:
        d = _make_design()
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        refs = {fp.ref for fp in project.pcb.footprints}
        assert "R1" in refs


# ---------------------------------------------------------------------------
# Fidelity scoring tests
# ---------------------------------------------------------------------------


class TestComputeWriteFidelity:
    def test_returns_dict(self) -> None:
        d = _make_design()
        result = compute_easyeda_write_fidelity(d)
        assert isinstance(result, dict)

    def test_keys_present(self) -> None:
        d = _make_design()
        result = compute_easyeda_write_fidelity(d)
        assert "component_jaccard" in result
        assert "net_jaccard" in result
        assert "overall_score" in result
        assert "degradation_report" in result
        assert "roundtrip_degradation_count" in result

    def test_full_fidelity_design(self) -> None:
        d = _make_design()
        result = compute_easyeda_write_fidelity(d)
        assert result["component_jaccard"] == pytest.approx(1.0)
        assert result["net_jaccard"] == pytest.approx(1.0)
        assert result["overall_score"] == pytest.approx(1.0)

    def test_zero_degradation_on_roundtrip(self) -> None:
        d = _make_design()
        result = compute_easyeda_write_fidelity(d)
        assert result["roundtrip_degradation_count"] == 0

    def test_empty_design_score(self) -> None:
        d = _Design()
        result = compute_easyeda_write_fidelity(d)
        assert result["overall_score"] == pytest.approx(1.0)

    def test_project_name_override(self) -> None:
        d = _make_design()
        result = compute_easyeda_write_fidelity(d, project_name="BoardX")
        assert result["degradation_report"]["accepted"] is True


# ---------------------------------------------------------------------------
# Jaccard helper tests
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_identical_sets(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "b"}) == pytest.approx(1.0)

    def test_disjoint_sets(self) -> None:
        assert _jaccard({"a"}, {"b"}) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)

    def test_both_empty(self) -> None:
        assert _jaccard(set(), set()) == pytest.approx(1.0)

    def test_one_empty(self) -> None:
        assert _jaccard({"a"}, set()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_design_without_meta(self) -> None:
        class _Bare:
            meta = None
            components: dict = {}
            nets: dict = {}
            blocks: list = []
            routing = None
            copper_pours: dict = {}

        raw, report = write_easyeda_pro_zip(_Bare())
        assert len(raw) > 0
        project = read_easyeda_pro_zip(raw)
        assert project.project_name == "untitled"

    def test_design_with_many_components(self) -> None:
        d = _Design()
        for i in range(50):
            d.components[f"c{i}"] = _Component(ref=f"R{i}", value="1k", footprint="0402")
        raw, report = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert len(project.schematic.components) == 50

    def test_position_none_defaults_to_origin(self) -> None:
        d = _Design()
        d.components["c1"] = _Component(ref="U1", position=None)  # type: ignore[arg-type]
        raw, _ = write_easyeda_pro_zip(d)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            text = zf.read("schematic.jsonl").decode()
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        u1 = next(r for r in records if r.get("ref") == "U1")
        assert u1["x"] == pytest.approx(0.0)
        assert u1["y"] == pytest.approx(0.0)

    def test_unicode_in_names(self) -> None:
        d = _Design()
        d.components["c1"] = _Component(ref="R1", value="电阻", footprint="0402")
        d.nets["n1"] = _Net(name="信号_VCC")
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert project.schematic.components[0].value == "电阻"
        assert project.schematic.nets[0].name == "信号_VCC"

    def test_net_with_no_pins(self) -> None:
        d = _Design()
        d.nets["n1"] = _Net(name="PWR")
        raw, _ = write_easyeda_pro_zip(d)
        project = read_easyeda_pro_zip(raw)
        assert project.schematic.nets[0].name == "PWR"
        assert project.schematic.nets[0].pins == []
