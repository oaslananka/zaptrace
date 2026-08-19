from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from zaptrace.generation import (
    ArchitectureCompileStatus,
    ElectronicsArchitectureArtifact,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
    electronics_architecture_schema_json,
    minimal_electronics_architecture_example,
)


def test_empty_architecture_intent_is_rejected() -> None:
    with pytest.raises(ValueError, match="intent must not be empty"):
        compile_electronics_intent_to_architecture("   ")


def test_compile_ready_esp32_usb_sensor_architecture() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )

    assert artifact.status == ArchitectureCompileStatus.READY
    assert artifact.design_name == "esp32_usb_temperature_sensor_architecture_v1"
    assert artifact.blocking_reasons == []
    assert artifact.human_review_required is True
    assert "not fabrication-ready" in " ".join(artifact.non_claims)

    requirement_ids = artifact.release_blocking_requirement_ids
    assert requirement_ids
    assert any(req.category == "power" for req in artifact.requirements)
    assert any(req.category == "interface" for req in artifact.requirements)
    assert {rail.net_name for rail in artifact.power_tree} >= {"VBUS", "VDD_3V3"}
    assert {interface.name for interface in artifact.interfaces} >= {"usb", "i2c"}
    assert any(interface.controlled_impedance for interface in artifact.interfaces if interface.name == "usb")

    coverage = artifact.requirement_coverage_matrix()
    for req_id in requirement_ids:
        assert coverage[req_id], f"missing architecture coverage for {req_id}"


def test_feature_population_helper_preserves_requirement_and_test_order() -> None:
    from zaptrace.generation import architecture as architecture_module

    draft_type = getattr(architecture_module, "_ArchitectureDraft", None)
    helper = getattr(architecture_module, "_populate_detected_features", None)
    assert draft_type is not None
    assert helper is not None

    normalized = (
        "ESP32 USB-C battery charger temperature sensor with I2C SPI RS-485 CAN "
        "microSD storage LoRa radio and 3.3V regulator"
    )
    draft = draft_type()
    helper(architecture_module._words(normalized), normalized, draft)

    assert [item.id for item in draft.requirements] == [
        "REQ-FUNCTIONAL-001",
        "REQ-POWER-002",
        "REQ-POWER-003",
        "REQ-POWER-004",
        "REQ-FUNCTIONAL-005",
        "REQ-INTERFACE-006",
        "REQ-INTERFACE-007",
        "REQ-INTERFACE-008",
        "REQ-INTERFACE-009",
        "REQ-FUNCTIONAL-010",
        "REQ-INTERFACE-011",
    ]
    assert [item.id for item in draft.acceptance_tests] == [f"AT-{index:03d}" for index in range(1, 12)]


def test_architecture_artifact_json_round_trip() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail"
    )

    payload = json.loads(electronics_architecture_artifact_json(artifact))
    loaded = ElectronicsArchitectureArtifact.model_validate(payload)

    assert loaded == artifact
    assert payload["status"] == "ready"
    assert payload["schema_version"] == "1.0"


def test_architecture_schema_contains_required_sections() -> None:
    schema = json.loads(electronics_architecture_schema_json())

    assert schema["title"] == "ElectronicsArchitectureArtifact"
    required = set(schema["required"])
    assert {"status", "design_name", "source_intent", "requirements"}.issubset(required)


def test_minimal_architecture_example_validates() -> None:
    payload = minimal_electronics_architecture_example()
    artifact = ElectronicsArchitectureArtifact.model_validate(payload)

    assert artifact.status == ArchitectureCompileStatus.READY
    assert artifact.design_name == "esp32_usb_temperature_sensor_architecture_v1"
    assert artifact.requirement_coverage_matrix()


def test_ambiguous_intent_blocks_for_clarification() -> None:
    artifact = compile_electronics_intent_to_architecture("make a small board")

    assert artifact.status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert artifact.blocking_reasons == ["intent is too vague to derive electronics architecture"]
    assert artifact.assumptions[0].confidence == "low"
    assert artifact.release_blocking_requirement_ids


def test_high_risk_intent_blocks_autonomous_generation() -> None:
    artifact = compile_electronics_intent_to_architecture("230V mains medical controller with sensor")

    assert artifact.status == ArchitectureCompileStatus.UNSAFE_BLOCKED
    assert artifact.blocking_reasons
    assert artifact.risks[0].severity == "critical"
    assert artifact.risks[0].human_review_required is True


def test_non_ready_architecture_requires_blocking_reasons() -> None:
    with pytest.raises(ValidationError, match="blocking_reasons"):
        ElectronicsArchitectureArtifact.model_validate(
            {
                "status": ArchitectureCompileStatus.NEEDS_CLARIFICATION,
                "design_name": "bad",
                "source_intent": "ambiguous",
                "requirements": [
                    {
                        "id": "REQ-FUNCTIONAL-001",
                        "text": "Clarify functional intent.",
                        "category": "functional",
                    }
                ],
            }
        )


def test_architecture_requires_fabrication_non_claim() -> None:
    payload = minimal_electronics_architecture_example()
    payload["non_claims"] = ["engineering review only"]

    with pytest.raises(ValidationError, match="not fabrication-ready"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_ready_architecture_rejects_untraced_element() -> None:
    payload = minimal_electronics_architecture_example()
    payload["subsystems"].append(
        {
            "id": "SUBSYS-UNTRACED",
            "name": "Untraced",
            "kind": "generic",
            "requirement_ids": [],
        }
    )

    with pytest.raises(ValidationError, match="trace reference"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_architecture_rejects_unknown_requirement_reference() -> None:
    payload = minimal_electronics_architecture_example()
    payload["subsystems"][0]["requirement_ids"] = ["REQ-MISSING"]

    with pytest.raises(ValidationError, match="unknown requirement ID REQ-MISSING"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_architecture_rejects_unknown_assumption_reference() -> None:
    payload = minimal_electronics_architecture_example()
    payload["subsystems"][0]["assumption_ids"] = ["ASM-MISSING"]

    with pytest.raises(ValidationError, match="unknown assumption ID ASM-MISSING"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_ready_architecture_rejects_uncovered_release_requirement() -> None:
    payload = minimal_electronics_architecture_example()
    payload["requirements"].append(
        {
            "id": "REQ-FUNCTIONAL-999",
            "text": "Provide an uncovered release function.",
            "category": "functional",
            "source": "test",
            "release_blocking": True,
        }
    )

    with pytest.raises(ValidationError, match="uncovered release-blocking requirement REQ-FUNCTIONAL-999"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_ready_architecture_rejects_unconfirmed_assumption() -> None:
    payload = minimal_electronics_architecture_example()
    payload["assumptions"].append(
        {
            "id": "ASM-UNCONFIRMED-001",
            "text": "Connector orientation requires confirmation.",
            "confidence": "low",
            "requires_confirmation": True,
            "related_requirement_ids": [payload["requirements"][0]["id"]],
        }
    )
    payload["subsystems"][0]["assumption_ids"] = ["ASM-UNCONFIRMED-001"]

    with pytest.raises(ValidationError, match="unconfirmed assumption ASM-UNCONFIRMED-001"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_wireless_presence_conflict_requires_clarification() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "LoRa wireless sensor node with no wireless radio allowed and 3.3V logic"
    )

    assert artifact.status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert [item.code for item in artifact.conflicts] == ["wireless-presence-conflict"]


def test_single_usb_connector_role_conflict_requires_clarification() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "Use the same USB connector as an exclusive USB host and USB device on a 3.3V MCU board"
    )

    assert artifact.status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert [item.code for item in artifact.conflicts] == ["usb-role-conflict"]


def test_logic_voltage_only_conflict_requires_clarification() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "MCU controller with 1.8 V only logic and 3.3 V only logic over SPI"
    )

    assert artifact.status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert [item.code for item in artifact.conflicts] == ["logic-voltage-conflict"]


def test_architecture_requires_at_least_one_release_blocking_requirement() -> None:
    payload = minimal_electronics_architecture_example()
    for requirement in payload["requirements"]:
        requirement["release_blocking"] = False

    with pytest.raises(ValidationError, match="at least one release-blocking requirement"):
        ElectronicsArchitectureArtifact.model_validate(payload)


def test_ready_architecture_rejects_unresolved_conflict() -> None:
    payload = minimal_electronics_architecture_example()
    requirement_ids = [item["id"] for item in payload["requirements"][:2]]
    payload["conflicts"] = [
        {
            "id": "CONFLICT-TEST-001",
            "code": "test-conflict",
            "description": "Fixture conflict remains unresolved.",
            "requirement_ids": requirement_ids,
            "resolution_required": "Resolve the fixture conflict.",
        }
    ]

    with pytest.raises(ValidationError, match="ready architecture contains unresolved conflict CONFLICT-TEST-001"):
        ElectronicsArchitectureArtifact.model_validate(payload)
