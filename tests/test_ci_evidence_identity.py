from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_evidence_identity import audit_repository, build_report, main

ROOT = Path(__file__).resolve().parents[1]


def _minimal_repo(tmp_path: Path) -> Path:
    (tmp_path / "docs/reports").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "zaptrace"\nversion = "1.2.3"\n', encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    for relative in (
        "scripts/ci_release_gate.py",
        "scripts/ci_generated_board_release_gate.py",
        "scripts/ci_benchmark_001.py",
        "scripts/ci_benchmark_fixture_coverage.py",
        "scripts/ci_benchmark_fixture_integrity.py",
        "scripts/ci_validation_environment.py",
        "scripts/ci_critical_runtime_coverage.py",
        "scripts/ci_version_consistency.py",
    ):
        (tmp_path / relative).write_text("evidence_identity = True\n", encoding="utf-8")
    (tmp_path / ".github/workflows/quality.yml").write_text("name: Quality\n", encoding="utf-8")
    return tmp_path


def test_audit_rejects_committed_current_release_evidence(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "docs/reports/v0.3.0-release-gate.json").write_text("{}\n", encoding="utf-8")

    result = audit_repository(root)

    assert result.passed is False
    assert any(item.code == "committed-current-evidence" for item in result.violations)


def test_audit_accepts_explicitly_classified_non_authoritative_reports(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    reports = {
        "sample.json": {"sample": True, "evidence_status": "non-authoritative-example"},
        "reference.json": {"reference": True, "evidence_status": "deterministic-reference-not-current-evidence"},
        "historical.json": {"historical_snapshot": True, "evidence_status": "historical-governance-snapshot"},
        "policy.json": {"policy_artifact": True, "evidence_status": "generated-policy-not-runtime-evidence"},
    }
    for name, payload in reports.items():
        (root / "docs/reports" / name).write_text(json.dumps(payload), encoding="utf-8")

    result = audit_repository(root)

    assert result.passed is True
    assert result.classified_report_count == 4


def test_audit_rejects_unclassified_json_report(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "docs/reports/ambiguous.json").write_text('{"schema_version":"1.0"}\n', encoding="utf-8")

    result = audit_repository(root)

    assert result.passed is False
    assert any(item.code == "unclassified-report" for item in result.violations)


def test_audit_rejects_hardcoded_historical_release_in_generic_gate(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    (root / "scripts/ci_release_gate.py").write_text('release = "v0.3.0"\nevidence_identity = True\n', encoding="utf-8")

    result = audit_repository(root)

    assert result.passed is False
    assert any(item.code == "hardcoded-release-identity" for item in result.violations)


def test_repository_evidence_inventory_is_unambiguous() -> None:
    result = audit_repository(ROOT)

    assert result.passed is True, [item.model_dump(mode="json") for item in result.violations]
    assert result.identity_producer_count >= 8
    assert result.classified_report_count >= 5


def test_cli_writes_identity_bound_policy_report(tmp_path: Path) -> None:
    output = tmp_path / "evidence-identity-policy.json"

    code = main(["--output", str(output), "--strict"])

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["evidence_identity"]["mode"] == "snapshot"
    assert len(payload["evidence_identity"]["source_commit"]) == 40
    assert len(payload["evidence_identity"]["identity_sha256"]) == 64
    rebuilt = build_report(ROOT)
    assert payload["passed"] == rebuilt["passed"]
    assert payload["evidence_identity"]["identity_sha256"] == rebuilt["evidence_identity"]["identity_sha256"]
