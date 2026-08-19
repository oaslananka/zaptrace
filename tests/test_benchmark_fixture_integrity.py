from __future__ import annotations

import json
import shutil
from pathlib import Path

from zaptrace.benchmark.integrity import evaluate_fixture_integrity, fixture_integrity_json


def _copy_family_fixture(tmp_path: Path, family_id: str) -> Path:
    root = tmp_path / "repo"
    source = Path("benchmarks") / family_id
    target = root / "benchmarks" / family_id
    target.mkdir(parents=True)
    for source_path in source.rglob("*"):
        relative = source_path.relative_to(source)
        target_path = target / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target_path)
    return root


def test_committed_benchmark_fixture_integrity_passes_all_families() -> None:
    report = evaluate_fixture_integrity(Path("."))

    assert report.passed is True
    assert report.family_count == 12
    assert report.passed_family_count == 12
    assert report.failed_family_count == 0
    assert report.failed_check_count == 0
    assert "fabrication approval" in " ".join(report.non_claims)


def test_fixture_integrity_json_round_trip() -> None:
    payload = json.loads(fixture_integrity_json(evaluate_fixture_integrity(Path("."))))

    assert payload["schema_version"] == "1.0"
    assert payload["passed"] is True
    assert payload["failed_check_count"] == 0


def test_fixture_integrity_detects_requirement_regression(tmp_path: Path) -> None:
    root = _copy_family_fixture(tmp_path, "esp32_usb_sensor")
    path = root / "benchmarks/esp32_usb_sensor/requirements.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["requirements"][0]["release_blocking"] = False
    path.write_text(json.dumps(data), encoding="utf-8")

    report = evaluate_fixture_integrity(root)
    family = next(item for item in report.families if item.family_id == "esp32_usb_sensor")

    assert report.passed is False
    assert family.status == "fail"
    assert any(check.kind == "requirements" and check.status == "fail" for check in family.checks)


def test_fixture_integrity_detects_proof_manifest_regression(tmp_path: Path) -> None:
    root = _copy_family_fixture(tmp_path, "esp32_usb_sensor")
    path = root / "benchmarks/esp32_usb_sensor/proof-pack/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["limitations"] = []
    path.write_text(json.dumps(data), encoding="utf-8")

    report = evaluate_fixture_integrity(root)
    family = next(item for item in report.families if item.family_id == "esp32_usb_sensor")

    assert report.passed is False
    assert any(check.kind == "proof-pack" and check.status == "fail" for check in family.checks)


def test_fixture_integrity_detects_golden_hash_regression(tmp_path: Path) -> None:
    root = _copy_family_fixture(tmp_path, "esp32_usb_sensor")
    pcb = root / "benchmarks/esp32_usb_sensor/golden/esp32_usb_sensor.kicad_pcb"
    pcb.write_text("changed\n", encoding="utf-8")

    report = evaluate_fixture_integrity(root)
    family = next(item for item in report.families if item.family_id == "esp32_usb_sensor")

    assert report.passed is False
    assert any(check.kind == "golden-kicad" and check.status == "fail" for check in family.checks)


def test_fixture_integrity_detects_export_non_claim_regression(tmp_path: Path) -> None:
    root = _copy_family_fixture(tmp_path, "esp32_usb_sensor")
    path = root / "benchmarks/esp32_usb_sensor/exports/manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["non_claims"] = []
    path.write_text(json.dumps(data), encoding="utf-8")

    report = evaluate_fixture_integrity(root)
    family = next(item for item in report.families if item.family_id == "esp32_usb_sensor")

    assert report.passed is False
    assert any(check.kind == "manufacturing-export" and check.status == "fail" for check in family.checks)


def test_fixture_integrity_script_writes_reports_and_blocks_on_failure(tmp_path: Path) -> None:
    from scripts.ci_benchmark_fixture_integrity import main

    clean_json = tmp_path / "clean.json"
    clean_md = tmp_path / "clean.md"
    assert main(["--output", str(clean_json), "--markdown", str(clean_md), "--strict"]) == 0
    payload = json.loads(clean_json.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "2.0"
    assert payload["passed"] is True
    assert payload["evidence_identity"]["mode"] == "snapshot"
    assert len(payload["evidence_identity"]["identity_sha256"]) == 64
    assert "Evidence identity" in clean_md.read_text(encoding="utf-8")
    assert "Benchmark Fixture Integrity" in clean_md.read_text(encoding="utf-8")

    root = _copy_family_fixture(tmp_path, "esp32_usb_sensor")
    export_path = root / "benchmarks/esp32_usb_sensor/exports/manifest.json"
    data = json.loads(export_path.read_text(encoding="utf-8"))
    data["non_claims"] = []
    export_path.write_text(json.dumps(data), encoding="utf-8")

    broken_json = tmp_path / "broken.json"
    assert main(["--root", str(root), "--output", str(broken_json), "--strict"]) == 1
    assert json.loads(broken_json.read_text(encoding="utf-8"))["passed"] is False
