from __future__ import annotations

import json

from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_kicad_schematic_project,
    generated_kicad_schematic_report_json,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)
from zaptrace.generation.kicad_schematic import _claim_violations


def _compiled_esp32():
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    return compile_intent_to_design_ir(intent)


def test_generate_kicad_schematic_project_from_compiled_design_ir(tmp_path) -> None:
    compiled = _compiled_esp32()

    generated = generate_kicad_schematic_project(compiled, tmp_path)

    assert generated.project_path.exists()
    assert generated.schematic_path.exists()
    assert generated.report_path.exists()
    assert generated.project_path.name == "esp32_usb_sensor_generated_v1.kicad_pro"
    assert generated.schematic_path.name == "esp32_usb_sensor_generated_v1.kicad_sch"
    assert generated.report.passed is True
    assert generated.report.family_id == "esp32_usb_sensor"
    assert generated.report.requirement_trace_count == 2
    assert generated.report.provenance_record_count == 1
    assert generated.report.claim_violations == []
    assert "not fabrication-ready" in " ".join(generated.report.non_claims)

    schematic_text = generated.schematic_path.read_text(encoding="utf-8")
    project = json.loads(generated.project_path.read_text(encoding="utf-8"))

    assert "kicad_sch" in schematic_text
    assert "esp32_usb_sensor_generated_v1" in schematic_text
    assert "U1" in schematic_text
    assert project["meta"]["version"] == 1


def test_generated_kicad_schematic_report_contains_stable_hash_records(tmp_path) -> None:
    first = generate_kicad_schematic_project(_compiled_esp32(), tmp_path / "first")
    second = generate_kicad_schematic_project(_compiled_esp32(), tmp_path / "second")

    first_payload = json.loads(first.report_path.read_text(encoding="utf-8"))
    second_payload = json.loads(second.report_path.read_text(encoding="utf-8"))

    assert first_payload["schema_version"] == "1.0"
    assert [item["kind"] for item in first_payload["generated_files"]] == ["project", "schematic"]
    assert [item["sha256"] for item in first_payload["generated_files"]] == [
        item["sha256"] for item in second_payload["generated_files"]
    ]
    assert all(item["size_bytes"] > 0 for item in first_payload["generated_files"])


def test_generated_kicad_schematic_report_json_round_trip(tmp_path) -> None:
    generated = generate_kicad_schematic_project(_compiled_esp32(), tmp_path)

    payload = json.loads(generated_kicad_schematic_report_json(generated.report))

    assert payload["design_name"] == "esp32_usb_sensor_generated_v1"
    assert payload["passed"] is True
    assert payload["generated_files"][0]["path"].endswith(".kicad_pro")


def test_generated_kicad_schematic_claim_guard_detects_fabrication_claim(tmp_path) -> None:
    bad = tmp_path / "bad.kicad_sch"
    safe = tmp_path / "safe.kicad_sch"
    bad.write_text("fabrication-ready\n", encoding="utf-8")
    safe.write_text("not fabrication-ready\n", encoding="utf-8")

    assert _claim_violations([bad, safe]) == ["bad.kicad_sch"]
