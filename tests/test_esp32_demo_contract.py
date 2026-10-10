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


def test_regulator_vout_and_tab_share_physical_pad_id_without_short(tmp_path: Path) -> None:
    import re

    from zaptrace.export.kicad import export_kicad_pcb

    design = parse_file(EXAMPLE / "design.yaml")
    regulator = design.components["U3"]
    assert regulator.footprint_asset == "ams1117-sot223-tabpin2"
    assert regulator.package_pin_map == {"1": "GND", "2": "OUTPUT", "3": "INPUT"}
    assert regulator.footprint_def is not None
    assert [str(p.id) for p in regulator.footprint_def.pads] == ["1", "2", "2", "3"]
    # Direct PCB export only includes components with a resolved placement.
    design.placement = {"U3": (20.0, 15.0)}
    pcb = export_kicad_pcb(design, tmp_path)["pcb"].read_text(encoding="utf-8")
    u3 = next(part for part in pcb.split("\n  (footprint ") if '(property "Reference" "U3"' in part)
    pads = re.findall(
        r'\(pad "([123])" smd[\s\S]*?\(net \d+ "([^"]+)"\)[\s\S]*?\(uuid "([0-9a-f-]{36})"\)',
        u3,
    )
    assert [(num, net) for num, net, _ in pads] == [
        ("1", "GND"),
        ("2", "VCC_3V3"),
        ("2", "VCC_3V3"),
        ("3", "VCC_5V"),
    ]
    # Both VOUT copper regions share the physical pin number but not the
    # KiCad object UUID. Neither may be shorted to GND or VIN.
    assert len({uuid for _, _, uuid in pads}) == 4


def test_bidirectional_tvs_candidate_uses_real_kicad_pads_and_distinct_nets(tmp_path: Path) -> None:
    import re

    from zaptrace.export.kicad import export_kicad_pcb

    design = parse_file(EXAMPLE / "design.yaml")
    tvs = design.components["D1"]
    assert tvs.type == "PESD5V0S1BA"
    assert tvs.footprint_asset == "pesd5v0s1ba-sod323"
    assert tvs.package_pin_map == {"1": "IO", "2": "GND"}
    assert tvs.footprint_def is not None
    assert [str(pad.id) for pad in tvs.footprint_def.pads] == ["1", "2"]
    assert tvs.pins["IO"].net == "VCC_5V"
    assert tvs.pins["GND"].net == "GND"

    # This is pad identity and export fidelity, NOT surge/thermal approval.
    design.placement = {"D1": (20.0, 15.0)}
    pcb = Path(export_kicad_pcb(design, tmp_path)["pcb"]).read_text(encoding="utf-8")
    d1 = next(part for part in pcb.split("\n  (footprint ") if '(property "Reference" "D1"' in part)
    pads = re.findall(
        r'\(pad "([12])" smd[\s\S]*?\(net \d+ "([^"]+)"\)[\s\S]*?\(uuid "([0-9a-f-]{36})"\)',
        d1,
    )
    assert [(pad_id, net) for pad_id, net, _ in pads] == [
        ("1", "VCC_5V"),
        ("2", "GND"),
    ]
    assert len({uuid for _, _, uuid in pads}) == 2


def test_usb_c_sink_uses_two_independent_resistors_and_ground_returns() -> None:
    from zaptrace.erc import rules

    design = parse_file(EXAMPLE / "design.yaml")
    j1 = design.components["J1"]
    assert j1.footprint_asset == "usb4105-16p"
    assert j1.package_pin_map == {
        "A1": "GND",
        "A4": "VBUS",
        "A5": "CC1",
        "A9": "VBUS",
        "A12": "GND",
        "B1": "GND",
        "B4": "VBUS",
        "B5": "CC2",
        "B9": "VBUS",
        "B12": "GND",
    }
    assert {pin: j1.pins[pin].net for pin in ("CC1", "CC2")} == {
        "CC1": "USB_CC1",
        "CC2": "USB_CC2",
    }
    for cc, ref in (("CC1", "R3"), ("CC2", "R4")):
        resistor = design.components[ref]
        assert resistor.value == "5.1k"
        assert resistor.footprint_asset == "r-0402"
        assert resistor.package_pin_map == {"1": "P1", "2": "P2"}
        assert resistor.footprint_def is not None
        assert {str(pad.id) for pad in resistor.footprint_def.pads} == {"1", "2"}
        assert resistor.pins["P1"].net == f"USB_{cc}"
        assert resistor.pins["P2"].net == "GND"
        nodes = {f"{node.component_ref}.{node.pin_name}" for node in design.nets[f"USB_{cc}"].nodes}
        assert nodes == {f"J1.{cc}", f"{ref}.P1"}
        assert f"{ref}.P2" in {f"{node.component_ref}.{node.pin_name}" for node in design.nets["GND"].nodes}
    assert not rules.rule_erc021(design)


def test_usb_c_sink_resistor_pads_export_to_separate_kicad_nets(tmp_path: Path) -> None:
    import re

    from zaptrace.export.kicad import export_kicad_pcb

    design = parse_file(EXAMPLE / "design.yaml")
    design.placement = {"R3": (12.0, 12.0), "R4": (16.0, 12.0)}
    pcb = Path(export_kicad_pcb(design, tmp_path)["pcb"]).read_text(encoding="utf-8")
    for ref, cc_net in (("R3", "USB_CC1"), ("R4", "USB_CC2")):
        footprint = next(block for block in pcb.split("\n  (footprint ") if f'(property "Reference" "{ref}"' in block)
        pads = re.findall(
            r'\(pad "([12])" smd[\s\S]*?\(net \d+ "([^"]+)"\)',
            footprint,
        )
        assert pads == [("1", cc_net), ("2", "GND")]


def test_passive_and_testpoint_physical_pad_maps_are_explicit() -> None:
    design = parse_file(EXAMPLE / "design.yaml")
    assets = {
        "R1": "r-0402",
        "R2": "r-0402",
        "R3": "r-0402",
        "R4": "r-0402",
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
        assert comp.footprint_def is not None
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

    assert evidence["node_count"] == 37
    assert evidence["missing_pcb_pad_node_count"] == 0
    assert evidence["missing_schematic_pin_node_count"] == 0
    assert evidence["fidelity"]["schematic_node_coverage"] == 1.0
    assert evidence["fidelity"]["pcb_pad_coverage"] == 1.0
    assert all(node["pcb_pad_present"] for net in evidence["nets"] for node in net["nodes"])


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
        "physical-pads-mapped",
    }
    assert {name for name, result in by_name.items() if not result.passed} == {
        "drc-clean",
        "min-clearance",
    }
    physical_details = by_name["physical-pads-mapped"].details
    drc_details = by_name["drc-clean"].details
    clearance_details = by_name["min-clearance"].details
    assert physical_details is not None
    assert drc_details is not None
    assert clearance_details is not None
    assert physical_details["pcb_pad_coverage"] == 1.0
    assert physical_details["missing_pcb_pad_node_count"] == 0
    assert drc_details["violations"]
    assert clearance_details["violations"]
    assert not pack.passed
    assert pack.autonomous_signoff.status.value == "blocked-insufficient-evidence"


def test_esp32_reference_field_is_outside_verified_pad_copper(tmp_path: Path) -> None:
    import re

    from zaptrace.export.kicad import export_kicad_pcb

    design = parse_file(EXAMPLE / "design.yaml")
    u1 = design.components["U1"]
    assert u1.footprint_def is not None
    left = min(pad.position[0] - pad.size[0] / 2 for pad in u1.footprint_def.pads)
    right = max(pad.position[0] + pad.size[0] / 2 for pad in u1.footprint_def.pads)
    bottom = min(pad.position[1] - pad.size[1] / 2 for pad in u1.footprint_def.pads)
    top = max(pad.position[1] + pad.size[1] / 2 for pad in u1.footprint_def.pads)
    board = Path(export_kicad_pcb(design, tmp_path)["pcb"]).read_text(encoding="utf-8")
    block = next(part for part in board.split("\n  (footprint ") if '(property "Reference" "U1"' in part)
    match = re.search(r'\(property "Reference" "U1"\s*\(at ([-.\d]+) ([-.\d]+) ([-.\d]+)\)', block)
    assert match is not None
    x, y, _angle = map(float, match.groups())
    assert x < left - 0.5 or x > right + 0.5 or y < bottom - 0.5 or y > top + 0.5
