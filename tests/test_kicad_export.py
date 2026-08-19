"""Tests for KiCad export — pad-net mapping and via net IDs."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.core.models import (
    Component,
    Design,
    DesignMeta,
    FootprintDef,
    Net,
    NetNode,
    NetType,
    Pad,
    Pin,
    PinType,
    RouteResult,
    TraceSegment,
)
from zaptrace.export.kicad import export_kicad, export_kicad_pcb, export_kicad_schematic
from zaptrace.kicad.parity import compare_kicad_schematic_to_pcb_files


def _make_test_design() -> Design:
    c1 = Component(
        id="r1",
        ref="R1",
        type="resistor",
        value="10k",
        footprint="0805",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE, net="vcc"),
            "2": Pin(name="2", type=PinType.PASSIVE, net="gnd"),
        },
    )
    c2 = Component(
        id="c1",
        ref="C1",
        type="capacitor",
        value="100nF",
        footprint="0805",
        pins={
            "1": Pin(name="1", type=PinType.PASSIVE, net="vcc"),
            "2": Pin(name="2", type=PinType.PASSIVE, net="gnd"),
        },
    )
    n_vcc = Net(
        id="vcc",
        name="VCC",
        type=NetType.POWER,
        nodes=[NetNode(component_ref="r1", pin_name="1"), NetNode(component_ref="c1", pin_name="1")],
    )
    n_gnd = Net(
        id="gnd",
        name="GND",
        type=NetType.GROUND,
        nodes=[NetNode(component_ref="r1", pin_name="2"), NetNode(component_ref="c1", pin_name="2")],
    )
    c1.footprint_def = FootprintDef(pads=[Pad(id="1"), Pad(id="2")])
    c2.footprint_def = FootprintDef(pads=[Pad(id="1"), Pad(id="2")])
    return Design(
        meta=DesignMeta(name="KiCadTest", version="0.1.0"),
        components={"r1": c1, "c1": c2},
        nets={"vcc": n_vcc, "gnd": n_gnd},
    )


def _make_design_with_vias() -> Design:
    d = _make_test_design()
    d.routing = RouteResult(
        traces=[TraceSegment(layer="F.Cu", start=(0.0, 0.0), end=(10.0, 0.0), width=0.2, net_id="vcc")],
        vias=[(5.0, 0.0, 0.45, 0.2, "vcc")],
    )
    return d


def test_pad_net_mapping(tmp_path: Path) -> None:
    d = _make_test_design()
    out = export_kicad_schematic(d, tmp_path)
    kicad_sch = Path(out["schematic"]).read_text(encoding="utf-8")
    assert "KiCadTest" in kicad_sch
    assert "kicad_sch" in kicad_sch


def test_schematic_exports_connected_net_nodes_as_kicad_library_pins(tmp_path: Path) -> None:
    design = _make_test_design()
    schematic = Path(export_kicad_schematic(design, tmp_path)["schematic"]).read_text(encoding="utf-8")

    assert "(lib_symbols" in schematic
    assert '(symbol "ZapTrace_R1"' in schematic
    assert "(pin passive line (at -5.08 0 0)" in schematic
    assert '(number "1"' in schematic
    assert '(pin "1" (uuid ' in schematic
    assert '(label "VCC" (at 45.72 50.8 0)' in schematic
    assert '(pin "2" (uuid ' in schematic
    assert '(label "GND" (at 55.88 50.8 0)' in schematic
    assert '(pin "1" (at ' not in schematic
    assert '(label "VCC" (at 200 10 0))' not in schematic


def test_schematic_multirow_pin_labels_follow_kicad_library_y_axis(tmp_path: Path) -> None:
    design = _make_test_design()
    component = design.components["r1"]
    component.pins["3"] = Pin(name="3", type=PinType.PASSIVE, net="sig")
    design.nets["sig"] = Net(
        id="sig",
        name="SIG",
        nodes=[NetNode(component_ref="r1", pin_name="3")],
    )

    schematic = Path(export_kicad_schematic(design, tmp_path)["schematic"]).read_text(encoding="utf-8")

    assert "(pin passive line (at -5.08 2.54 0)" in schematic
    assert '(label "SIG" (at 45.72 48.26 0)' in schematic


def test_pcb_pad_net_numbers(tmp_path: Path) -> None:
    d = _make_test_design()
    out = export_kicad_pcb(d, tmp_path)
    pcb_text = Path(out["pcb"]).read_text(encoding="utf-8")
    assert '(net 1 "VCC")' in pcb_text
    assert '(net 2 "GND")' in pcb_text


def _make_logical_package_pin_design() -> Design:
    sensor = Component(
        id="sensor",
        ref="U1",
        type="sensor",
        value="BME280-like",
        pins={
            "GND": Pin(name="GND", type=PinType.POWER),
            "SDI": Pin(name="SDI", type=PinType.BIDIRECTIONAL),
            "VDD": Pin(name="VDD", type=PinType.POWER),
        },
        package_pin_map={"1": "GND", "3": "SDI", "7": "GND", "8": "VDD"},
        footprint_def=FootprintDef(pads=[Pad(id="1"), Pad(id="3"), Pad(id="7"), Pad(id="8")]),
        position=(10.0, 10.0),
    )
    return Design(
        meta=DesignMeta(name="PackagePinMap", version="0.1.0"),
        components={"sensor": sensor},
        nets={
            "gnd": Net(
                id="gnd",
                name="GND",
                type=NetType.GROUND,
                nodes=[NetNode(component_ref="sensor", pin_name="GND")],
            ),
            "sda": Net(
                id="sda",
                name="SDA",
                nodes=[NetNode(component_ref="sensor", pin_name="SDI")],
            ),
            "vcc": Net(
                id="vcc",
                name="VCC",
                type=NetType.POWER,
                nodes=[NetNode(component_ref="sensor", pin_name="VDD")],
            ),
        },
    )


def test_physical_package_pads_inherit_logical_pin_nets(tmp_path: Path) -> None:
    from zaptrace.kicad.parity import parse_kicad_pcb_pad_net_map

    design = _make_logical_package_pin_design()
    out = export_kicad(design, tmp_path)
    pcb = parse_kicad_pcb_pad_net_map(Path(out["pcb"]).read_text(encoding="utf-8"))
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))

    assert pcb["GND"] == {"U1.1", "U1.7"}
    assert pcb["SDA"] == {"U1.3"}
    assert pcb["VCC"] == {"U1.8"}
    assert evidence["missing_or_unmapped_node_count"] == 0
    parity = compare_kicad_schematic_to_pcb_files(design, out["netlist_evidence"], out["pcb"])
    assert parity.passed is True
    assert parity.pin_mismatches == []


def test_partial_package_pin_map_is_not_treated_as_identity_mapping(tmp_path: Path) -> None:
    design = _make_logical_package_pin_design()
    component = design.components["sensor"]
    component.package_pin_map.pop("8")

    out = export_kicad(design, tmp_path)
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))
    pcb_text = Path(out["pcb"]).read_text(encoding="utf-8")

    vcc = next(net for net in evidence["nets"] if net["id"] == "vcc")
    assert "sensor.VDD" in vcc["missing_or_unmapped_nodes"]
    assert evidence["missing_or_unmapped_node_count"] == 1
    assert '(pad "8"' in pcb_text
    assert '      (net 3 "VCC")' not in pcb_text.split('(pad "8"', 1)[1].split("    )", 1)[0]
    parity = compare_kicad_schematic_to_pcb_files(design, out["netlist_evidence"], out["pcb"])
    assert parity.passed is False
    assert parity.missing_nets == ["VCC"]


def test_via_net_id_present(tmp_path: Path) -> None:
    d = _make_design_with_vias()
    out = export_kicad_pcb(d, tmp_path)
    pcb_text = Path(out["pcb"]).read_text(encoding="utf-8")
    assert "(via" in pcb_text
    assert "(net 1)" in pcb_text


def test_kicad_export_writes_connected_netlist_evidence(tmp_path: Path) -> None:
    d = _make_design_with_vias()
    out = export_kicad(d, tmp_path)
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))
    assert evidence["schema_version"] == "1.0"
    assert evidence["net_count"] == 2
    assert evidence["missing_or_unmapped_node_count"] == 0
    vcc = next(net for net in evidence["nets"] if net["id"] == "vcc")
    assert vcc["name"] == "VCC"
    assert len(vcc["nodes"]) == 2
    assert vcc["routed_segment_count"] == 1
    assert vcc["routed_via_count"] == 1
    assert evidence["fidelity"]["has_routed_pcb_geometry"] is True


def test_kicad_netlist_evidence_reports_missing_footprint_pad(tmp_path: Path) -> None:
    d = _make_test_design()
    d.components["r1"].footprint_def = FootprintDef(pads=[Pad(id="1")])
    out = export_kicad(d, tmp_path)
    evidence = json.loads(Path(out["netlist_evidence"]).read_text(encoding="utf-8"))
    assert evidence["missing_or_unmapped_node_count"] == 1
    gnd = next(net for net in evidence["nets"] if net["id"] == "gnd")
    assert "r1.2" in gnd["missing_or_unmapped_nodes"]
    assert evidence["fidelity"]["pcb_pad_coverage"] < 1.0
