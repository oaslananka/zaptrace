from __future__ import annotations

import json
from pathlib import Path

import pytest

from zaptrace.benchmark.families import (
    AcceptanceThreshold,
    BenchmarkBoardFamily,
    BoardFamilyManifest,
    RequiredBenchmarkArtifact,
)
from zaptrace.benchmark.fixtures import (
    evaluate_fixture_coverage,
    fixture_coverage_json,
)
from zaptrace.benchmark.kicad_fixtures import compare_golden_kicad_fixture, load_golden_kicad_fixture
from zaptrace.proof.manifest import ProofManifest

ESP32_FIXTURE_ROOT = Path("benchmarks/esp32_usb_sensor")


def _single_family_manifest() -> BoardFamilyManifest:
    return BoardFamilyManifest(
        manifest_version="test",
        families=[
            BenchmarkBoardFamily(
                family_id="fixture_family",
                title="Fixture Family",
                domain="test",
                representative_intent="test fixture family",
                tags=["test"],
                supported_profiles=["proof-pack-required"],
                required_artifacts=[
                    RequiredBenchmarkArtifact(
                        name="requirements",
                        kind="requirements-json",
                        path_pattern="benchmarks/fixture_family/requirements.json",
                    ),
                    RequiredBenchmarkArtifact(
                        name="golden",
                        kind="kicad-project",
                        path_pattern="benchmarks/fixture_family/golden/*.kicad_*",
                    ),
                ],
                acceptance_thresholds=[
                    AcceptanceThreshold(metric="fixture.complete", operator="==", value=True, release_blocking=True)
                ],
            )
        ],
    )


def test_fixture_coverage_detects_missing_required_artifacts(tmp_path: Path) -> None:
    manifest = _single_family_manifest()

    report = evaluate_fixture_coverage(tmp_path, manifest=manifest)

    assert report.complete is False
    assert report.complete_family_count == 0
    assert report.missing_required_artifact_count == 2
    family = report.families[0]
    assert family.complete is False
    assert {artifact.name for artifact in family.artifacts if not artifact.present} == {"requirements", "golden"}


def test_fixture_coverage_detects_present_exact_and_glob_artifacts(tmp_path: Path) -> None:
    (tmp_path / "benchmarks/fixture_family/golden").mkdir(parents=True)
    (tmp_path / "benchmarks/fixture_family/requirements.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "benchmarks/fixture_family/golden/example.kicad_pcb").write_text("pcb\n", encoding="utf-8")

    report = evaluate_fixture_coverage(tmp_path, manifest=_single_family_manifest())

    assert report.complete is True
    assert report.complete_family_count == 1
    family = report.families[0]
    assert family.present_required_artifact_count == 2
    assert family.missing_required_artifact_count == 0
    assert family.artifacts[1].matched_paths == ["benchmarks/fixture_family/golden/example.kicad_pcb"]


def test_committed_esp32_usb_sensor_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "esp32_usb_sensor")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0
    assert {artifact.name for artifact in family.artifacts if artifact.present} == {
        "requirements",
        "proof-pack",
        "kicad-project",
        "manufacturing-exports",
    }


def test_committed_fixture_coverage_is_complete_for_all_families() -> None:
    report = evaluate_fixture_coverage(Path("."))

    assert report.family_count == 12
    assert report.complete is True
    assert report.complete_family_count == 12
    assert report.incomplete_family_count == 0
    assert report.missing_required_artifact_count == 0
    assert "not fabrication approval" in " ".join(report.non_claims)


def test_committed_esp32_golden_fixture_compares_cleanly() -> None:
    fixture = load_golden_kicad_fixture(ESP32_FIXTURE_ROOT / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, ESP32_FIXTURE_ROOT / "golden")

    assert result.passed is True
    assert result.checked_count == 3
    assert result.missing_files == []
    assert result.changed_files == []
    assert result.unexpected_files == []


def test_committed_esp32_proof_manifest_validates_as_proof_manifest() -> None:
    data = json.loads((ESP32_FIXTURE_ROOT / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "esp32_usb_sensor_fixture_v1"
    assert len(manifest.checks) == 3
    assert manifest.check_records[0].status == "pass"
    assert any("does not prove" in limitation for limitation in manifest.limitations)


def test_committed_stm32_rs485_industrial_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "stm32_rs485_industrial")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0


def test_committed_stm32_golden_fixture_compares_cleanly() -> None:
    root = Path("benchmarks/stm32_rs485_industrial")
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3


def test_committed_stm32_proof_manifest_validates_as_proof_manifest() -> None:
    root = Path("benchmarks/stm32_rs485_industrial")
    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "stm32_rs485_industrial_fixture_v1"
    assert len(manifest.checks) == 3
    assert any("industrial safety" in limitation for limitation in manifest.limitations)


def test_committed_nrf52_ble_multisensor_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "nrf52_ble_multisensor")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0


def test_committed_nrf52_golden_fixture_compares_cleanly() -> None:
    root = Path("benchmarks/nrf52_ble_multisensor")
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3


def test_committed_nrf52_proof_manifest_validates_as_proof_manifest() -> None:
    root = Path("benchmarks/nrf52_ble_multisensor")
    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "nrf52_ble_multisensor_fixture_v1"
    assert len(manifest.checks) == 3
    assert any("BLE RF performance" in limitation for limitation in manifest.limitations)


def test_committed_rp2040_can_node_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "rp2040_can_node")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0


def test_committed_rp2040_golden_fixture_compares_cleanly() -> None:
    root = Path("benchmarks/rp2040_can_node")
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3


def test_committed_rp2040_proof_manifest_validates_as_proof_manifest() -> None:
    root = Path("benchmarks/rp2040_can_node")
    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "rp2040_can_node_fixture_v1"
    assert len(manifest.checks) == 3
    assert any("CAN compliance" in limitation for limitation in manifest.limitations)


def test_committed_usb_c_power_sink_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "usb_c_power_sink")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0


def test_committed_usb_c_power_sink_golden_fixture_compares_cleanly() -> None:
    root = Path("benchmarks/usb_c_power_sink")
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3


def test_committed_usb_c_power_sink_proof_manifest_validates_as_proof_manifest() -> None:
    root = Path("benchmarks/usb_c_power_sink")
    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "usb_c_power_sink_fixture_v1"
    assert len(manifest.checks) == 3
    assert any("USB-C compliance" in limitation for limitation in manifest.limitations)


def test_committed_lipo_charger_node_fixture_is_complete() -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == "lipo_charger_node")

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0


def test_committed_lipo_charger_node_golden_fixture_compares_cleanly() -> None:
    root = Path("benchmarks/lipo_charger_node")
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3


def test_committed_lipo_charger_node_proof_manifest_validates_as_proof_manifest() -> None:
    root = Path("benchmarks/lipo_charger_node")
    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == "lipo_charger_node_fixture_v1"
    assert len(manifest.checks) == 3
    assert any("Li-ion charge safety" in limitation for limitation in manifest.limitations)


REMAINING_BATCH_FAMILY_LIMITATIONS = [
    ("poe_ethernet_controller", "PoE compliance"),
    ("motor_driver_hbridge", "motor safety"),
    ("switching_regulator_module", "switching stability"),
    ("high_current_led_driver", "LED thermal safety"),
    ("mcu_sd_datalogger", "SD-card compatibility"),
    ("lora_gateway_node", "RF performance"),
]


@pytest.mark.parametrize("family_id, limitation", REMAINING_BATCH_FAMILY_LIMITATIONS)
def test_committed_remaining_batch_fixture_is_complete(family_id: str, limitation: str) -> None:
    report = evaluate_fixture_coverage(Path("."))
    family = next(item for item in report.families if item.family_id == family_id)

    assert family.complete is True
    assert family.present_required_artifact_count == 4
    assert family.missing_required_artifact_count == 0

    root = Path("benchmarks") / family_id
    fixture = load_golden_kicad_fixture(root / "golden/fixture.json")
    result = compare_golden_kicad_fixture(fixture, root / "golden")

    assert result.passed is True
    assert result.checked_count == 3

    data = json.loads((root / "proof-pack/manifest.json").read_text(encoding="utf-8"))
    manifest = ProofManifest.model_validate(data)

    assert manifest.name == f"{family_id}_fixture_v1"
    assert len(manifest.checks) == 3
    assert any(limitation in item for item in manifest.limitations)


def test_fixture_coverage_json_round_trip() -> None:
    payload = json.loads(fixture_coverage_json(evaluate_fixture_coverage(Path("."))))

    assert payload["schema_version"] == "1.0"
    assert payload["family_count"] == 12
    assert payload["complete_family_count"] == 12


def test_fixture_coverage_script_writes_json_and_markdown(tmp_path: Path) -> None:
    from scripts.ci_benchmark_fixture_coverage import main

    output = tmp_path / "coverage.json"
    markdown = tmp_path / "coverage.md"

    code = main(["--output", str(output), "--markdown", str(markdown), "--strict", "--min-complete-families", "12"])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert payload["complete_family_count"] == 12
    assert payload["evidence_identity"]["mode"] == "snapshot"
    assert len(payload["evidence_identity"]["identity_sha256"]) == 64
    assert "Evidence identity" in markdown.read_text(encoding="utf-8")
    assert "Benchmark Fixture Coverage" in markdown.read_text(encoding="utf-8")


def test_fixture_coverage_script_blocks_when_threshold_not_met(tmp_path: Path) -> None:
    from scripts.ci_benchmark_fixture_coverage import main

    output = tmp_path / "coverage.json"

    code = main(["--output", str(output), "--strict", "--min-complete-families", "13"])

    assert code == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["complete_family_count"] == 12
