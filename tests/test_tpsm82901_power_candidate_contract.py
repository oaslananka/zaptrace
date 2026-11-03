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


def test_tpsm82901_review_footprint_matches_ti_sis0011a_land_pattern() -> None:
    footprint_path = CANDIDATE / "TPSM82901SISR-11-DRAFT.kicad_mod"
    footprint = load_kicad_footprint(footprint_path)

    assert footprint is not None
    assert {pad.id for pad in footprint.pads} == {str(number) for number in range(1, 12)}
    assert "DRAFT" in footprint.description
    pads = {pad.id: pad for pad in footprint.pads if pad.id != "11"}
    assert pads["1"].position == (-1.075, -1.1625)
    assert pads["5"].position == (-1.075, 1.1625)
    assert pads["10"].position == (1.075, -1.1625)
    assert pads["6"].position == (1.075, 1.1625)
    assert all(pads[number].size == (0.55, 0.575) for number in ("1", "5", "6", "10"))
    assert all(pads[number].size == (0.55, 0.25) for number in ("2", "3", "4", "7", "8", "9"))
    exposed_pad = next(pad for pad in footprint.pads if pad.id == "11")
    assert exposed_pad.size == (0.9, 2.15)
    assert exposed_pad.solder_paste is False
    source = footprint_path.read_text(encoding="utf-8")
    assert source.count('(layer "F.Paste")') == 2
    assert "(solder_mask_margin -0.05)" in source
    # The TI drawing shows optional via locations; the candidate currently
    # leaves them out until the paste/assembly and minimum-drill process is set.
    assert "thru_hole" not in source


def test_tpsm82901_candidate_compact_placement_keeps_passives_near_u3() -> None:
    design = parse_file(CANDIDATE / "design.yaml")
    assert design.placement is not None
    u3_x, u3_y = design.placement["U3"]
    assert abs(design.placement["C1"][0] - u3_x) < 4.0
    assert abs(design.placement["C2"][0] - u3_x) < 3.5
    assert abs(design.placement["R1"][1] - u3_y) < 2.0
    assert abs(design.placement["R2"][0] - u3_x) < 5.5
    assert design.components["C1"].pins["P1"].net == "GND"
    assert design.components["C1"].pins["P2"].net == "VCC_5V"


def test_tpsm82901_review_passives_have_signal_facing_pin_orientation() -> None:
    mode = load_kicad_footprint(CANDIDATE / "R_0603_Mode_Rev.kicad_mod")
    soft_start = load_kicad_footprint(CANDIDATE / "C_0603_SS_Rev.kicad_mod")

    assert mode is not None and soft_start is not None
    assert {pad.id for pad in mode.pads} == {"1", "2"}
    assert {pad.id for pad in soft_start.pads} == {"1", "2"}
    # Symmetric, non-polar parts: geometry is unchanged; only pad numbering
    # is reversed so the MODE and SS/TR nets face the regulator.
    assert mode.pads[0].size == mode.pads[1].size
    assert soft_start.pads[0].size == soft_start.pads[1].size
    mode_by_id = {pad.id: pad for pad in mode.pads}
    ss_by_id = {pad.id: pad for pad in soft_start.pads}
    assert mode_by_id["1"].position[0] > mode_by_id["2"].position[0]
    assert ss_by_id["1"].position[0] > ss_by_id["2"].position[0]


def test_tpsm82901_generated_kicad_reports_are_native_clean() -> None:
    import json

    generated = CANDIDATE / "generated"
    drc = json.loads((generated / "candidate-drc.json").read_text(encoding="utf-8"))
    erc = json.loads((generated / "candidate-erc.json").read_text(encoding="utf-8"))

    warnings = [item for sheet in erc.get("sheets", []) for item in sheet.get("violations", [])]
    assert drc["violations"] == []
    assert drc["unconnected_items"] == []
    assert erc.get("violations", []) == []
    assert warnings == []


def test_tpsm82901_review_board_keeps_all_reference_labels_visible_on_fab() -> None:
    from zaptrace.io.sexp import parse

    board_path = CANDIDATE / "generated" / "ESP32_Sensor_Node_TPSM82901_Review-Only_Power_Stage.kicad_pcb"
    board = parse(board_path.read_text(encoding="utf-8"))
    footprints = [item for item in board[1:] if isinstance(item, list) and item and item[0] == "footprint"]
    assert len(footprints) == 12

    references: set[str] = set()
    for footprint in footprints:
        properties = [
            item
            for item in footprint[1:]
            if isinstance(item, list) and item and item[0] == "property" and len(item) >= 3
        ]
        reference = next(item for item in properties if item[1] == "Reference")
        references.add(str(reference[2]))
        layers = [item for item in reference[3:] if isinstance(item, list) and item and item[0] == "layer"]
        assert layers == [["layer", "F.Fab"]]
        assert not any(isinstance(item, list) and item[:2] == ["hide", "yes"] for item in reference[3:])
    assert references == {"U3", "C1", "C2", "C3", "C4", "R1", "R2", "R3", "R4", "TP_IN", "TP_OUT", "TP_GND"}
