"""Contract for the isolated TPSM82901 review-only power-stage candidate."""

from __future__ import annotations

from pathlib import Path

from zaptrace.core.parser import parse_file
from zaptrace.kicad.importer import load_kicad_footprint

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "examples" / "esp32_i2c_sensor_node" / "power_candidate_tpsm82901"


def test_tpsm82901_candidate_keeps_exact_pin_and_power_contract() -> None:
    design = parse_file(CANDIDATE / "design.yaml")
    regulator = design.components["U3"]

    assert design.board.layers == 4
    assert regulator.mpn == "TPSM82901SISR"
    assert regulator.package_pin_map == {
        "1": "VIN_A",
        "2": "VIN_B",
        "3": "EN",
        "4": "MODE_SCONF",
        "5": "SS_TR",
        "6": "PG",
        "7": "FB_VSET",
        "8": "SW_NC",
        "9": "VOUT_A",
        "10": "VOUT_B",
        "11": "GND",
    }
    assert regulator.pins["SW_NC"].net is None
    assert all(
        not (node.component_ref == "U3" and node.pin_name == "SW_NC")
        for net in design.nets.values()
        for node in net.nodes
    )
    assert {node.pin_name for node in design.nets["VCC_5V"].nodes if node.component_ref == "U3"} == {
        "VIN_A",
        "VIN_B",
        "EN",
    }
    assert {node.pin_name for node in design.nets["VCC_3V3"].nodes if node.component_ref == "U3"} == {
        "VOUT_A",
        "VOUT_B",
    }
    assert next(node for node in design.nets["GND"].nodes if node.component_ref == "U3").pin_name == "GND"


def test_tpsm82901_candidate_matches_evm_configuration_values() -> None:
    design = parse_file(CANDIDATE / "design.yaml")
    values = {ref: design.components[ref].value for ref in ("C1", "C2", "R1", "R2", "R3", "C3", "C4", "R4")}

    c1, c2 = values["C1"], values["C2"]
    r1, r2, r3 = values["R1"], values["R2"], values["R3"]
    c3, c4, r4 = values["C3"], values["C4"], values["R4"]
    assert c1 is not None and "10uF 25V" in c1 and "C3216X7R1E106K160AE" in c1
    assert c2 is not None and "22uF 10V" in c2 and "C2012X7S1A226M125AC" in c2
    assert r1 == "113k 1%"
    assert r2 == "24.9k 1%"
    assert r3 == "7.15k 1%"
    assert c3 is not None and c3.startswith("22pF")
    assert c4 is not None and c4.startswith("3.3nF")
    assert r4 is not None and r4.startswith("1M")


def test_tpsm82901_review_footprint_is_explicitly_draft_and_11_pad() -> None:
    footprint = load_kicad_footprint(CANDIDATE / "TPSM82901SISR-11-DRAFT.kicad_mod")

    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == {str(number) for number in range(1, 12)}
    assert "DRAFT" in footprint.description
    exposed_pad = next(pad for pad in footprint.pads if pad.id == "11")
    assert exposed_pad.size == (0.9, 2.1)
