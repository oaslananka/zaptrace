from __future__ import annotations

import json
from pathlib import Path

from tests.test_kicad_export import _make_test_design
from zaptrace.export.kicad import export_kicad_netlist_evidence
from zaptrace.kicad.parity import (
    compare_ir_to_kicad_netlist_evidence,
    compare_ir_to_kicad_netlist_evidence_file,
    ir_net_map,
    kicad_evidence_net_map,
    write_kicad_netlist_parity_report,
)


def test_parity_passes_for_exported_netlist_evidence(tmp_path: Path) -> None:
    design = _make_test_design()
    evidence_path = export_kicad_netlist_evidence(design, tmp_path)["netlist_evidence"]

    report = compare_ir_to_kicad_netlist_evidence_file(design, evidence_path)

    assert report.passed is True
    assert report.error_count == 0
    assert report.ir_net_count == 2
    assert report.kicad_net_count == 2


def test_parity_detects_missing_and_extra_nets() -> None:
    design = _make_test_design()
    evidence = {
        "nets": [
            {"id": "vcc", "nodes": [{"component_ref": "r1", "pin_name": "1"}]},
            {"id": "extra", "nodes": []},
        ]
    }

    report = compare_ir_to_kicad_netlist_evidence(design, evidence)

    assert report.passed is False
    assert report.missing_nets == ["gnd"]
    assert report.extra_nets == ["extra"]


def test_parity_detects_pin_mismatch() -> None:
    design = _make_test_design()
    evidence = {
        "nets": [
            {
                "id": "vcc",
                "nodes": [
                    {"component_ref": "r1", "pin_name": "1"},
                    {"component_ref": "c1", "pin_name": "2"},
                ],
            },
            {
                "id": "gnd",
                "nodes": [
                    {"component_ref": "r1", "pin_name": "2"},
                    {"component_ref": "c1", "pin_name": "2"},
                ],
            },
        ]
    }

    report = compare_ir_to_kicad_netlist_evidence(design, evidence)

    assert report.passed is False
    mismatch = next(item for item in report.pin_mismatches if item.net_id == "vcc")
    assert mismatch.missing_nodes == ["c1.1"]
    assert mismatch.extra_nodes == ["c1.2"]


def test_write_parity_report(tmp_path: Path) -> None:
    design = _make_test_design()
    evidence_path = export_kicad_netlist_evidence(design, tmp_path)["netlist_evidence"]
    out = write_kicad_netlist_parity_report(design, evidence_path, tmp_path / "parity.json")

    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["check"] == "ir_to_kicad_schematic_netlist"
    assert data["passed"] is True


def test_net_map_helpers() -> None:
    design = _make_test_design()
    ir = ir_net_map(design)
    ev = kicad_evidence_net_map({"nets": [{"id": "vcc", "nodes": [{"component_ref": "r1", "pin_name": "1"}]}]})

    assert ir["vcc"] == {"r1.1", "c1.1"}
    assert ev["vcc"] == {"r1.1"}
