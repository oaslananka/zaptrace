from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci_generated_board_release_gate import build_report

REPORT_PATH = Path("docs/reports/generated-board-release-gate.json")

EXPECTED_ARTIFACT_KINDS = [
    "intent",
    "design-ir-compile-report",
    "kicad-project",
    "kicad-schematic",
    "schematic-generation-report",
    "kicad-pcb",
    "pcb-generation-report",
    "manufacturing-export-manifest",
    "review-handoff",
]

EXPECTED_ARTIFACT_HASHES = {
    "intent": "a8ab42aff48cf91fe15396c3a1e219d7b1648d7bb46c5754005e7997df83958f",
    "design-ir-compile-report": "1cb74987d98b141bf5361e1a308d8895f62e3a388562430c4f40ee1185dcabb1",
    "kicad-project": "e672a2fd0ef2bf3edc4b29f5f44cc49bc3af3a9f6cc9a6f42ee249209b9ae2e7",
    "kicad-schematic": "c9a00c2921e308dbe9f6cf18c1330af2fb0c36880096035d7d8104de0cac1f11",
    "schematic-generation-report": "17b6fe7fa68e220e93339a1aa1bf2460d9547694c1741e1de7595501c39780c5",
    "kicad-pcb": "67441d1ea69e17343cf459d96208e86d67839d17ee3dd56468b5d491be1b9d1a",
    "pcb-generation-report": "f474d238f5d6eaba1e870e8f20159b1134249e877cf107aebceacb1dd37d4a2b",
    "manufacturing-export-manifest": "1f49b6c584e94847734e89ac715f650a95ab19e4606df67d5532a3238e3a9576",
    "review-handoff": "df586620a33f74ae270aa193e0a4bdf4e59eb947d7b45da2e34513b6680b30ed",
}

EXPECTED_ARTIFACT_PATHS = {
    "intent": "board-generation-intent.json",
    "design-ir-compile-report": "esp32_usb_sensor_generated_v1.design_ir_compilation.json",
    "kicad-project": "esp32_usb_sensor_generated_v1.kicad_pro",
    "kicad-schematic": "esp32_usb_sensor_generated_v1.kicad_sch",
    "schematic-generation-report": "esp32_usb_sensor_generated_v1.kicad_schematic_generation.json",
    "kicad-pcb": "esp32_usb_sensor_generated_v1.kicad_pcb",
    "pcb-generation-report": "esp32_usb_sensor_generated_v1.kicad_pcb_generation.json",
    "manufacturing-export-manifest": "exports/manifest.json",
    "review-handoff": "review/handoff.json",
}


@pytest.fixture(scope="module")
def current_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    trusted_root = tmp_path_factory.mktemp("generated-board-release-gate")
    return build_report(
        trusted_root / "artifacts",
        trusted_root=trusted_root,
        risky_package_reviewed=True,
        risky_package_approval_id="GENERATED-BOARD-BASELINE-REVIEW-2026-07-22",
    )


def test_current_generated_board_report_is_ci_artifact_only() -> None:
    assert not REPORT_PATH.exists()


def test_generated_board_artifact_hash_snapshot(current_report: dict[str, object]) -> None:
    assert current_report["expected_artifact_kinds"] == EXPECTED_ARTIFACT_KINDS
    assert current_report["artifact_hashes"] == EXPECTED_ARTIFACT_HASHES
    assert current_report["artifact_paths"] == EXPECTED_ARTIFACT_PATHS


def test_generated_board_report_required_structure_snapshot(current_report: dict[str, object]) -> None:
    report = current_report
    assert report["schema_version"] == "3.0"
    assert report["gate_id"] == "generated-board-release-gate-v3"
    assert report["family_id"] == "esp32_usb_sensor"
    assert report["design_name"] == "esp32_usb_sensor_generated_v1"
    assert report["passed"] is True
    assert report["generated_project_evidence_passed"] is True
    assert report["artifact_count"] == 9
    assert report["required_artifact_count"] == 9
    assert report["missing_required_artifact_count"] == 0
    assert report["requirement_trace_count"] == 2
    assert report["provenance_record_count"] == 1
    assert report["schematic_passed"] is True
    assert report["pcb_passed"] is True
    assert report["manufacturing_manifest_present"] is True
    assert report["review_handoff_present"] is True
    assert report["blocking_reasons"] == []
    assert report["non_claims_enforced"] is True
    identity = report["evidence_identity"]
    assert identity["mode"] == "snapshot"
    assert len(identity["identity_sha256"]) == 64
    coverage = report["component_coverage"]
    assert coverage["status"] == "pass"
    assert coverage["checked_component_count"] == 8
    assert coverage["bom_accounted_component_count"] == 8
    assert coverage["pick_and_place_accounted_component_count"] == 8
    assert coverage["unresolved_component_count"] == 0
    assert coverage["placement_missing_component_count"] == 0
    assert coverage["blocked_component_count"] == 0
    assert coverage["reviewed"] is True
    assert coverage["approval_id"] == "GENERATED-BOARD-BASELINE-REVIEW-2026-07-22"


def test_generated_board_report_non_claim_snapshot(current_report: dict[str, object]) -> None:
    report = current_report
    assert report["non_claims"] == [
        "generated board project is for engineering review only",
        "not fabrication-ready",
        "not manufacturer-approved",
        "not production-ready",
    ]
    assert "fabrication-ready" not in set(report["non_claims"]) - {"not fabrication-ready"}
