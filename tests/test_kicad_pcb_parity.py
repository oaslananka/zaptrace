from __future__ import annotations

import json
from pathlib import Path

from tests.test_kicad_export import _make_test_design
from zaptrace.export.kicad import export_kicad_netlist_evidence, export_kicad_pcb
from zaptrace.kicad.parity import (
    compare_kicad_schematic_to_pcb_files,
    parse_kicad_pcb_pad_net_map,
    schematic_evidence_ref_net_map,
    write_kicad_pcb_parity_report,
)


def _exported_paths(tmp_path: Path):
    design = _make_test_design()
    design.placement = {"r1": (10.0, 10.0), "c1": (20.0, 10.0)}
    evidence_path = export_kicad_netlist_evidence(design, tmp_path)["netlist_evidence"]
    pcb_path = export_kicad_pcb(design, tmp_path)["pcb"]
    return design, evidence_path, pcb_path


def test_schematic_to_pcb_parity_passes_for_exported_files(tmp_path: Path) -> None:
    design, evidence_path, pcb_path = _exported_paths(tmp_path)

    report = compare_kicad_schematic_to_pcb_files(design, evidence_path, pcb_path)

    assert report.passed is True
    assert report.error_count == 0
    assert report.schematic_net_count == 2
    assert report.pcb_net_count == 2


def test_pcb_missing_net_fails(tmp_path: Path) -> None:
    design, evidence_path, pcb_path = _exported_paths(tmp_path)
    pcb_text = pcb_path.read_text(encoding="utf-8").replace('      (net 2 "GND")\n', "")
    pcb_path.write_text(pcb_text, encoding="utf-8")

    report = compare_kicad_schematic_to_pcb_files(design, evidence_path, pcb_path)

    assert report.passed is False
    assert report.missing_nets == ["GND"]


def test_footprint_reference_mismatch_fails_with_actionable_nodes(tmp_path: Path) -> None:
    design, evidence_path, pcb_path = _exported_paths(tmp_path)
    pcb_text = pcb_path.read_text(encoding="utf-8").replace('(property "Reference" "R1"', '(property "Reference" "RX"')
    pcb_path.write_text(pcb_text, encoding="utf-8")

    report = compare_kicad_schematic_to_pcb_files(design, evidence_path, pcb_path)

    assert report.passed is False
    vcc = next(item for item in report.pin_mismatches if item.net_id == "VCC")
    assert "R1.1" in vcc.missing_nodes
    assert "RX.1" in vcc.extra_nodes


def test_parse_pcb_pad_net_map_and_schematic_ref_map(tmp_path: Path) -> None:
    design, evidence_path, pcb_path = _exported_paths(tmp_path)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    schematic = schematic_evidence_ref_net_map(design, evidence)
    pcb = parse_kicad_pcb_pad_net_map(pcb_path.read_text(encoding="utf-8"))

    assert schematic["VCC"] == {"R1.1", "C1.1"}
    assert pcb["VCC"] == {"R1.1", "C1.1"}


def test_write_pcb_parity_report(tmp_path: Path) -> None:
    design, evidence_path, pcb_path = _exported_paths(tmp_path)
    out = write_kicad_pcb_parity_report(design, evidence_path, pcb_path, tmp_path / "pcb_parity.json")

    data = json.loads(out.read_text(encoding="utf-8"))

    assert data["schema_version"] == "1.0"
    assert data["check"] == "kicad_schematic_to_pcb_netlist"
    assert data["passed"] is True
