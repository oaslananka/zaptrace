from __future__ import annotations

import json

from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_kicad_pcb_project,
    generated_kicad_pcb_report_json,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)
from zaptrace.generation.kicad_schematic import _claim_violations


def _compiled_esp32():
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    return compile_intent_to_design_ir(intent)


def test_generate_kicad_pcb_project_from_compiled_design_ir(tmp_path) -> None:
    compiled = _compiled_esp32()

    generated = generate_kicad_pcb_project(compiled, tmp_path)

    assert generated.pcb_path.exists()
    assert generated.report_path.exists()
    assert generated.pcb_path.name == "esp32_usb_sensor_generated_v1.kicad_pcb"
    assert generated.report.passed is True
    assert generated.report.family_id == "esp32_usb_sensor"
    assert generated.report.board_width_mm == 50
    assert generated.report.board_height_mm == 40
    assert generated.report.layer_count == 2
    assert generated.report.net_count == len(compiled.design.nets)
    assert generated.report.component_count == len(compiled.design.components)
    assert generated.report.routing_constraint_count == 4
    assert generated.report.requirement_trace_count == 2
    assert generated.report.provenance_record_count == 1
    assert generated.report.claim_violations == []
    assert "not fabrication-ready" in " ".join(generated.report.non_claims)

    pcb_text = generated.pcb_path.read_text(encoding="utf-8")
    assert "kicad_pcb" in pcb_text
    assert "esp32_usb_sensor_generated_v1" in pcb_text
    assert '(net 1 "VCC_5V")' in pcb_text
    assert '"Edge.Cuts"' in pcb_text


def test_generated_kicad_pcb_report_contains_stable_hash_records(tmp_path) -> None:
    first = generate_kicad_pcb_project(_compiled_esp32(), tmp_path / "first")
    second = generate_kicad_pcb_project(_compiled_esp32(), tmp_path / "second")

    first_payload = json.loads(first.report_path.read_text(encoding="utf-8"))
    second_payload = json.loads(second.report_path.read_text(encoding="utf-8"))

    assert first_payload["schema_version"] == "1.0"
    assert first_payload["generated_files"][0]["kind"] == "pcb"
    assert first_payload["generated_files"][0]["sha256"] == second_payload["generated_files"][0]["sha256"]
    assert first_payload["generated_files"][0]["size_bytes"] > 0


def test_generated_kicad_pcb_report_json_round_trip(tmp_path) -> None:
    generated = generate_kicad_pcb_project(_compiled_esp32(), tmp_path)

    payload = json.loads(generated_kicad_pcb_report_json(generated.report))

    assert payload["design_name"] == "esp32_usb_sensor_generated_v1"
    assert payload["passed"] is True
    assert payload["generated_files"][0]["path"].endswith(".kicad_pcb")


def test_generated_kicad_pcb_claim_guard_detects_fabrication_claim(tmp_path) -> None:
    bad = tmp_path / "bad.kicad_pcb"
    safe = tmp_path / "safe.kicad_pcb"
    bad.write_text("production-ready\n", encoding="utf-8")
    safe.write_text("not production-ready\n", encoding="utf-8")

    assert _claim_violations([bad, safe]) == ["bad.kicad_pcb"]
