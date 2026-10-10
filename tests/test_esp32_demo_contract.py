"""Regression guard: the public ESP32 demo must not pretend unsafe routing is approved."""

from __future__ import annotations

from pathlib import Path

import yaml

from zaptrace.core.parser import parse_file
from zaptrace.proof.pack import run_proof

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "esp32_i2c_sensor_node"


def test_esp32_and_bme280_physical_pin_maps_match_documented_land_patterns() -> None:
    design = parse_file(EXAMPLE / "design.yaml")
    assert design.components["U1"].package_pin_map == {
        "1": "GND",
        "2": "VCC",
        "3": "EN",
        "15": "GND",
        "33": "GPIO21",
        "36": "GPIO22",
        "38": "GND",
        "39": "GND",
    }
    assert design.components["U2"].package_pin_map == {
        "1": "GND",
        "2": "CSB",
        "3": "SDA",
        "4": "SCK",
        "5": "SDO",
        "6": "VDDIO",
        "7": "GND",
        "8": "VDD",
    }
    assert design.components["U2"].pins["VDDIO"].net == "VCC_3V3"
    assert "U2.VDDIO" in {f"{node.component_ref}.{node.pin_name}" for node in design.nets["VCC_3V3"].nodes}


def test_passive_and_testpoint_physical_pad_maps_are_explicit() -> None:
    design = parse_file(EXAMPLE / "design.yaml")
    assets = {
        "R1": "r-0402",
        "R2": "r-0402",
        "C1": "c-0402",
        "C2": "c-0805",
        "C3": "c-0402",
        "TP1": "testpoint-pad-d1",
        "TP2": "testpoint-pad-d1",
    }
    for ref, asset in assets.items():
        comp = design.components[ref]
        assert comp.footprint_asset == asset
        assert comp.package_pin_map == ({"1": "P1"} if ref.startswith("TP") else {"1": "P1", "2": "P2"})
        assert {str(pad.id) for pad in comp.footprint_def.pads} == set(comp.package_pin_map)


def test_example_proof_expectations_match_real_component_and_pin_identities() -> None:
    design = parse_file(EXAMPLE / "design.yaml")
    policy = yaml.safe_load((EXAMPLE / ".proof" / "proof.yaml").read_text(encoding="utf-8"))
    checks = {check["name"]: check for check in policy["checks"]}

    for name in ("power-nets-connected", "gnd-connected"):
        assertion = checks[name]["params"]
        matching_net = next(net for net in design.nets.values() if net.name == assertion["net_name"])
        connected = {f"{node.component_ref}.{node.pin_name}" for node in matching_net.nodes}
        assert set(assertion["expected_pins"]) <= connected
        assert all("." in pin for pin in assertion["expected_pins"])


def test_esp32_demo_reports_partial_pinned_physical_pad_coverage(tmp_path: Path) -> None:
    import json

    from zaptrace.export.kicad import export_kicad_netlist_evidence

    design = parse_file(EXAMPLE / "design.yaml")
    artifact = export_kicad_netlist_evidence(design, tmp_path)
    evidence = json.loads(Path(artifact["netlist_evidence"]).read_text(encoding="utf-8"))

    assert evidence["node_count"] == 31
    assert evidence["missing_pcb_pad_node_count"] == 7
    assert evidence["missing_schematic_pin_node_count"] == 0
    assert evidence["fidelity"]["schematic_node_coverage"] == 1.0
    assert evidence["fidelity"]["pcb_pad_coverage"] == 24 / 31
    assert all(
        node["pcb_pad_present"]
        for net in evidence["nets"]
        for node in net["nodes"]
        if node["component_ref"] not in {"U3", "J1", "D1"}
    )
    assert all(
        not node["pcb_pad_present"]
        for net in evidence["nets"]
        for node in net["nodes"]
        if node["component_ref"] in {"U3", "J1", "D1"}
    )


def test_esp32_demo_exports_but_strict_proof_remains_blocked_on_real_geometry() -> None:
    pack = run_proof(EXAMPLE / ".proof")
    by_name = {result.check.name: result for result in pack.results}
    assert len(by_name) == 8
    assert {name for name, result in by_name.items() if result.passed} == {
        "erc-clean",
        "all-nets-routed",
        "footprints-complete",
        "power-nets-connected",
        "gnd-connected",
    }
    assert {name for name, result in by_name.items() if not result.passed} == {
        "drc-clean",
        "min-clearance",
        "physical-pads-mapped",
    }
    assert by_name["physical-pads-mapped"].details["pcb_pad_coverage"] == 24 / 31
    assert by_name["physical-pads-mapped"].details["missing_pcb_pad_node_count"] == 7
    assert by_name["drc-clean"].details["violations"]
    assert by_name["min-clearance"].details["violations"]
    assert not pack.passed
    assert pack.autonomous_signoff.status.value == "blocked-insufficient-evidence"
