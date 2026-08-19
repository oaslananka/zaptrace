from __future__ import annotations

import json

import pytest

from zaptrace.generation import (
    ArchitectureCompileStatus,
    ArchitectureConstraint,
    ArchitectureIntentBridgeStatus,
    ArchitectureRequirement,
    ElectronicsArchitectureArtifact,
    RequirementCategory,
    compile_electronics_intent_to_architecture,
    compile_intent_to_design_ir,
    convert_architecture_to_board_generation_intent,
    convert_architecture_to_board_generation_intent_report,
    infer_board_generation_family,
)


def test_infers_supported_family_from_ready_architecture() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )

    assert infer_board_generation_family(artifact) == "esp32_usb_sensor"


def test_convert_ready_architecture_to_board_generation_intent() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )

    intent = convert_architecture_to_board_generation_intent(artifact)

    assert intent.family_id == "esp32_usb_sensor"
    assert intent.design_name == artifact.design_name
    assert {requirement.id for requirement in intent.requirements} == artifact.requirement_ids
    assert {power.net_name for power in intent.power} >= {"VBUS", "VDD_3V3"}
    assert {interface.name for interface in intent.interfaces} >= {"usb", "i2c"}
    assert "not fabrication-ready" in " ".join(intent.non_claims)


def test_bridge_report_for_ready_architecture() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail"
    )

    report = convert_architecture_to_board_generation_intent_report(artifact)

    assert report.status == ArchitectureIntentBridgeStatus.CONVERTED
    assert report.converted is True
    assert report.family_id == "esp32_usb_sensor"
    assert report.blocking_reasons == []


def test_converted_intent_compiles_to_design_ir() -> None:
    artifact = compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail"
    )
    intent = convert_architecture_to_board_generation_intent(artifact)

    compiled = compile_intent_to_design_ir(intent)

    assert compiled.report.compiled is True
    assert compiled.report.family_id == "esp32_usb_sensor"
    assert compiled.design.meta.name == intent.design_name


def test_non_ready_architecture_blocks_with_report() -> None:
    artifact = compile_electronics_intent_to_architecture("make a small board")

    with pytest.raises(ValueError) as excinfo:
        convert_architecture_to_board_generation_intent(artifact)

    report = json.loads(str(excinfo.value))
    assert report["status"] == "not-ready"
    assert report["architecture_status"] == "needs-clarification"
    assert report["blocking_reasons"] == ["intent is too vague to derive electronics architecture"]


def test_unsupported_ready_architecture_blocks_with_report() -> None:
    artifact = ElectronicsArchitectureArtifact(
        status=ArchitectureCompileStatus.READY,
        design_name="generic_power_board",
        source_intent="regulated 3.3V power board",
        requirements=[
            ArchitectureRequirement(
                id="REQ-POWER-001",
                text="Provide a regulated 3.3 V rail.",
                category=RequirementCategory.POWER,
            )
        ],
        constraints=[
            ArchitectureConstraint(
                id="CONSTRAINT-POWER-001",
                domain="simulation",
                text="Verify the regulated rail margin.",
                requirement_ids=["REQ-POWER-001"],
            )
        ],
    )

    with pytest.raises(ValueError) as excinfo:
        convert_architecture_to_board_generation_intent(artifact)

    report = json.loads(str(excinfo.value))
    assert report["status"] == "unsupported-architecture"
    assert report["family_id"] is None
    assert report["blocking_reasons"]


def test_explicit_family_override_allows_ready_architecture_conversion() -> None:
    artifact = ElectronicsArchitectureArtifact(
        status=ArchitectureCompileStatus.READY,
        design_name="generic_overridden_board",
        source_intent="generic reviewed board",
        requirements=[
            ArchitectureRequirement(
                id="REQ-FUNCTIONAL-001",
                text="Provide a reviewed board candidate.",
                category=RequirementCategory.FUNCTIONAL,
            )
        ],
        constraints=[
            ArchitectureConstraint(
                id="CONSTRAINT-FUNCTIONAL-001",
                domain="review",
                text="Retain requirement traceability through generation.",
                requirement_ids=["REQ-FUNCTIONAL-001"],
            )
        ],
    )

    intent = convert_architecture_to_board_generation_intent(
        artifact,
        family_id="esp32_usb_sensor",
        target_output_dir="generated/overridden",
    )

    assert intent.family_id == "esp32_usb_sensor"
    assert intent.target_output_dir == "generated/overridden"
