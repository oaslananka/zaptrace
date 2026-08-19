from __future__ import annotations

import json
from pathlib import Path

from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)


def test_esp32_usb_sensor_generated_board_end_to_end_acceptance(tmp_path: Path) -> None:
    """Acceptance: intent -> Design IR -> KiCad schematic/PCB -> evidence bundle."""
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())

    compiled = compile_intent_to_design_ir(intent)
    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    assert compiled.report.compiled is True
    assert compiled.report.family_id == "esp32_usb_sensor"
    assert compiled.design.meta.name == "esp32_usb_sensor_generated_v1"
    assert "not-fabrication-ready" in compiled.design.meta.tags

    expected_files = {
        "board-generation-intent.json",
        "esp32_usb_sensor_generated_v1.design_ir_compilation.json",
        "esp32_usb_sensor_generated_v1.kicad_pro",
        "esp32_usb_sensor_generated_v1.kicad_sch",
        "esp32_usb_sensor_generated_v1.kicad_schematic_generation.json",
        "esp32_usb_sensor_generated_v1.kicad_pcb",
        "esp32_usb_sensor_generated_v1.kicad_pcb_generation.json",
        "exports/manifest.json",
        "review/handoff.json",
        "esp32_usb_sensor_generated_v1.generated_project_evidence.json",
    }
    assert expected_files == {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file()}

    bundle = result.bundle
    assert bundle.passed is True
    assert bundle.family_id == "esp32_usb_sensor"
    assert bundle.artifact_count == 9
    assert bundle.required_artifact_count == 9
    assert bundle.missing_required_artifact_count == 0
    assert bundle.requirement_trace_count == len(intent.requirements)
    assert bundle.provenance_record_count == 1
    assert bundle.schematic_passed is True
    assert bundle.pcb_passed is True
    assert bundle.manufacturing_manifest_present is True
    assert bundle.review_handoff_present is True
    assert bundle.blocking_reasons == []
    assert "not fabrication-ready" in " ".join(bundle.non_claims)

    schematic_text = result.schematic.schematic_path.read_text(encoding="utf-8")
    pcb_text = result.pcb.pcb_path.read_text(encoding="utf-8")
    handoff = json.loads((tmp_path / "review/handoff.json").read_text(encoding="utf-8"))
    manufacturing = json.loads((tmp_path / "exports/manifest.json").read_text(encoding="utf-8"))

    assert "kicad_sch" in schematic_text
    assert "esp32_usb_sensor_generated_v1" in schematic_text
    assert "kicad_pcb" in pcb_text
    assert "Edge.Cuts" in pcb_text
    assert handoff["status"] == "human-review-required"
    assert "KiCad ERC/DRC oracle evidence" in handoff["required_review_items"]
    assert "not fabrication-ready" in manufacturing["non_claims"]

    evidence_payload = json.loads(result.bundle_path.read_text(encoding="utf-8"))
    artifact_hashes = {artifact["kind"]: artifact["sha256"] for artifact in evidence_payload["artifacts"]}
    assert set(artifact_hashes) == {
        "intent",
        "design-ir-compile-report",
        "kicad-project",
        "kicad-schematic",
        "schematic-generation-report",
        "kicad-pcb",
        "pcb-generation-report",
        "manufacturing-export-manifest",
        "review-handoff",
    }
    assert all(len(value) == 64 for value in artifact_hashes.values())
