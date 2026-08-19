from __future__ import annotations

import json

from zaptrace.generation import (
    compile_intent_to_design_ir,
    generate_project_evidence_bundle,
    generated_project_evidence_bundle_json,
    minimal_board_generation_intent_example,
    validate_board_generation_intent,
)


def _intent_and_compiled():
    intent = validate_board_generation_intent(minimal_board_generation_intent_example())
    return intent, compile_intent_to_design_ir(intent)


def test_generate_project_evidence_bundle_emits_required_artifacts(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()

    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    assert result.bundle_path.exists()
    assert result.schematic.schematic_path.exists()
    assert result.pcb.pcb_path.exists()
    assert result.bundle.passed is True
    assert result.bundle.family_id == "esp32_usb_sensor"
    assert result.bundle.artifact_count == 9
    assert result.bundle.required_artifact_count == 9
    assert result.bundle.missing_required_artifact_count == 0
    assert result.bundle.requirement_trace_count == 2
    assert result.bundle.provenance_record_count == 1
    assert result.bundle.schematic_passed is True
    assert result.bundle.pcb_passed is True
    assert result.bundle.manufacturing_manifest_present is True
    assert result.bundle.review_handoff_present is True
    assert result.bundle.blocking_reasons == []
    assert "not fabrication-ready" in " ".join(result.bundle.non_claims)

    artifact_kinds = {artifact.kind for artifact in result.bundle.artifacts}
    assert artifact_kinds == {
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
    for artifact in result.bundle.artifacts:
        assert (tmp_path / artifact.path).is_file()
        assert artifact.sha256
        assert artifact.size_bytes > 0


def test_generated_project_evidence_bundle_json_round_trip(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    payload = json.loads(generated_project_evidence_bundle_json(result.bundle))

    assert payload["schema_version"] == "1.0"
    assert payload["passed"] is True
    assert payload["design_name"] == "esp32_usb_sensor_generated_v1"
    assert payload["artifact_count"] == 9


def test_generated_project_evidence_bundle_hashes_are_stable(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    first = generate_project_evidence_bundle(intent, compiled, tmp_path / "first")
    second = generate_project_evidence_bundle(intent, compiled, tmp_path / "second")

    first_hashes = {artifact.kind: artifact.sha256 for artifact in first.bundle.artifacts}
    second_hashes = {artifact.kind: artifact.sha256 for artifact in second.bundle.artifacts}

    assert first_hashes == second_hashes


def test_generated_project_evidence_writes_manufacturing_and_review_handoff(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    generate_project_evidence_bundle(intent, compiled, tmp_path)

    manifest = json.loads((tmp_path / "exports/manifest.json").read_text(encoding="utf-8"))
    handoff = json.loads((tmp_path / "review/handoff.json").read_text(encoding="utf-8"))

    assert manifest["artifact_kind"] == "generated-manufacturing-export-manifest"
    assert "not fabrication-ready" in manifest["non_claims"]
    assert handoff["status"] == "human-review-required"
    assert "KiCad ERC/DRC oracle evidence" in handoff["required_review_items"]


def test_generated_project_evidence_bundle_file_matches_returned_model(tmp_path) -> None:
    intent, compiled = _intent_and_compiled()
    result = generate_project_evidence_bundle(intent, compiled, tmp_path)

    payload = json.loads(result.bundle_path.read_text(encoding="utf-8"))

    assert payload == result.bundle.model_dump(mode="json")


def test_generated_project_evidence_accepts_architecture_artifact(tmp_path) -> None:
    from zaptrace.generation import (
        compile_electronics_intent_to_architecture,
        convert_architecture_to_board_generation_intent,
    )

    architecture = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )
    intent = convert_architecture_to_board_generation_intent(architecture)
    compiled = compile_intent_to_design_ir(intent)

    result = generate_project_evidence_bundle(intent, compiled, tmp_path, architecture=architecture)

    assert result.bundle.passed is True
    assert result.bundle.artifact_count == 11
    assert result.bundle.required_artifact_count == 11
    assert result.bundle.architecture_present is True
    assert result.bundle.architecture_status == "ready"
    assert result.bundle.architecture_requirement_count == len(architecture.requirements)
    assert result.bundle.architecture_bridge_status == "converted"

    artifact_kinds = {artifact.kind for artifact in result.bundle.artifacts}
    assert "architecture" in artifact_kinds
    assert "architecture-intent-bridge-report" in artifact_kinds
    assert (tmp_path / "architecture/electronics-architecture.json").is_file()
    assert (tmp_path / "architecture/architecture-intent-bridge.json").is_file()


def test_generate_project_evidence_bundle_accepts_relative_output_root(tmp_path, monkeypatch) -> None:
    intent, compiled = _intent_and_compiled()
    monkeypatch.chdir(tmp_path)

    result = generate_project_evidence_bundle(intent, compiled, ".generated/release-gate")

    assert result.bundle_path.is_file()
    assert result.bundle.passed is True
    assert all(not artifact.path.startswith("/") for artifact in result.bundle.artifacts)
    assert all((tmp_path / ".generated/release-gate" / artifact.path).is_file() for artifact in result.bundle.artifacts)
