from __future__ import annotations

import hashlib
import json

from zaptrace.generation import (
    ArchitectureCompileStatus,
    architecture_traceability_report_json,
    build_architecture_traceability_report,
    compile_electronics_intent_to_architecture,
    electronics_architecture_artifact_json,
)


def _ready_artifact():
    return compile_electronics_intent_to_architecture(
        "ESP32 USB-C temperature sensor board with I2C sensor and 3.3V logic rail",
        design_name="esp32_usb_temperature_sensor_architecture_v1",
    )


def test_ready_architecture_traceability_report_is_complete() -> None:
    artifact = _ready_artifact()

    report = build_architecture_traceability_report(artifact)

    expected_hash = hashlib.sha256(electronics_architecture_artifact_json(artifact).encode("utf-8")).hexdigest()
    assert report.artifact_sha256 == expected_hash
    assert report.architecture_status == ArchitectureCompileStatus.READY
    assert report.blocked is False
    assert report.human_review_required is False
    assert report.fully_traced is True
    assert report.uncovered_requirement_ids == []
    assert report.untraced_elements == []
    assert report.conflict_ids == []
    assert set(report.requirement_ids) == artifact.requirement_ids
    assert {row.kind for row in report.traceability} >= {
        "subsystem",
        "power",
        "interface",
        "constraint",
        "risk",
        "acceptance-test",
    }


def test_architecture_traceability_json_is_byte_deterministic() -> None:
    first_artifact = _ready_artifact()
    second_artifact = _ready_artifact()

    first = architecture_traceability_report_json(build_architecture_traceability_report(first_artifact))
    second = architecture_traceability_report_json(build_architecture_traceability_report(second_artifact))

    assert first == second
    assert first.endswith("\n")
    assert json.loads(first)["blocked"] is False


def test_ambiguous_architecture_traceability_blocks_and_requires_review() -> None:
    artifact = compile_electronics_intent_to_architecture("make a small board")

    report = build_architecture_traceability_report(artifact)

    assert report.architecture_status == ArchitectureCompileStatus.NEEDS_CLARIFICATION
    assert report.blocked is True
    assert report.human_review_required is True
    assert report.unconfirmed_assumption_ids == ["ASM-CLARIFY-001"]


def test_unsafe_architecture_traceability_blocks() -> None:
    artifact = compile_electronics_intent_to_architecture("230V mains medical controller with sensor")

    report = build_architecture_traceability_report(artifact)

    assert report.architecture_status == ArchitectureCompileStatus.UNSAFE_BLOCKED
    assert report.blocked is True
    assert report.human_review_required is True
    assert report.conflict_ids == []
    assert any(row.kind == "risk" and row.id == "RISK-SAFETY-001" for row in report.traceability)
