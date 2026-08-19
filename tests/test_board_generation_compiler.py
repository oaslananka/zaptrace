from __future__ import annotations

import json

import pytest

from zaptrace.generation import (
    CompilationStatus,
    compile_intent_to_design_ir,
    design_ir_compilation_report_json,
    minimal_board_generation_intent_example,
    supported_generation_families,
    validate_board_generation_intent,
)


def test_supported_generation_families_start_with_esp32_usb_sensor() -> None:
    assert supported_generation_families() == ["esp32_usb_sensor"]


def test_compile_esp32_intent_to_design_ir() -> None:
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())

    compiled = compile_intent_to_design_ir(intent)

    assert compiled.report.status == CompilationStatus.COMPILED
    assert compiled.report.compiled is True
    assert compiled.report.family_id == "esp32_usb_sensor"
    assert compiled.report.template_id == "esp32_i2c_sensor"
    assert compiled.report.template_match_score is not None
    assert compiled.report.requirement_traces[0].requirement_id == "REQ-USBC-POWER"
    assert "not fabrication-ready" in " ".join(compiled.report.non_claims)

    design = compiled.design
    assert design.meta.name == "esp32_usb_sensor_generated_v1"
    assert "generated-board-intent" in design.meta.tags
    assert "family:esp32_usb_sensor" in design.meta.tags
    assert "not-fabrication-ready" in design.meta.tags
    assert {"U1", "U2", "U3"}.issubset(set(design.components))
    assert {"VCC_3V3", "GND", "I2C_SDA", "I2C_SCL"}.issubset(set(design.nets))
    assert design.constraints.manufacturing.profile == "reviewable-generated-board"
    assert {domain.id for domain in design.constraints.voltage_domains} == {"VBUS", "VDD_3V3"}
    assert any(route.net == "USB_D_P" and route.differential_pair for route in design.constraints.routing)
    assert design.prov_records
    assert "board_generation_intent" in design.prov_records[0].artifact_hashes


def test_design_ir_compilation_report_json_round_trip() -> None:
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    report = compile_intent_to_design_ir(intent).report

    payload = json.loads(design_ir_compilation_report_json(report))

    assert payload["status"] == "compiled"
    assert payload["template_id"] == "esp32_i2c_sensor"
    assert payload["method"] == "template_selection"


def test_compile_valid_but_unsupported_family_blocks_with_report() -> None:
    data = minimal_board_generation_intent_example()
    data["family_id"] = "lipo_charger_node"
    data["design_name"] = "lipo_charger_node_generated_v1"
    intent = validate_board_generation_intent(data)

    with pytest.raises(ValueError) as excinfo:
        compile_intent_to_design_ir(intent)

    payload = json.loads(str(excinfo.value))
    assert payload["status"] == "unsupported-family"
    assert payload["family_id"] == "lipo_charger_node"
    assert payload["blocking_reasons"]
    assert payload["requirement_traces"][0]["requirement_id"] == "REQ-USBC-POWER"
