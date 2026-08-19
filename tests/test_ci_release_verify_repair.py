"""CI entry-point and schema contracts for release verify/repair evidence."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ci_release_verify_repair import main
from zaptrace.pipeline.verify_repair_models import VerifyRepairReport

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/release-verify-repair-report-v1.schema.json"


def test_committed_verify_repair_schema_matches_model() -> None:
    assert json.loads(SCHEMA.read_text(encoding="utf-8")) == VerifyRepairReport.model_json_schema()


def test_ci_script_writes_identity_bound_four_family_evidence(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    output = tmp_path / "release-convergence-report.json"
    markdown = tmp_path / "release-convergence-report.md"

    code = main(
        [
            "--trusted-output-root",
            str(tmp_path),
            "--artifact-dir",
            str(artifact_dir),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["family_count"] == 4
    assert payload["converged_count"] == 4
    assert payload["evidence_identity"]["source_commit"]
    assert payload["evidence_identity"]["lock_sha256"]
    assert len(payload["report_sha256"]) == 64
    assert "Release Verify/Repair Convergence" in markdown.read_text(encoding="utf-8")
    assert (artifact_dir / "release-convergence-report.json").exists()
    assert len(list(artifact_dir.glob("*/verify-repair.json"))) == 4


def test_strict_mode_returns_one_for_nonconverged_report(tmp_path: Path, monkeypatch) -> None:
    import scripts.ci_release_verify_repair as script

    fake = SimpleNamespace(
        passed=False,
        model_dump=lambda mode="json": {
            "passed": False,
            "family_count": 4,
            "converged_count": 3,
            "policy_version": "test",
            "policy_sha256": "0" * 64,
            "report_sha256": "1" * 64,
            "families": [],
            "non_claims": ["not release readiness"],
            "evidence_identity": {},
        },
    )
    monkeypatch.setattr(script, "run_release_convergence_benchmark", lambda *_args, **_kwargs: fake)

    code = main(
        [
            "--trusted-output-root",
            str(tmp_path),
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.md"),
            "--strict",
        ]
    )

    assert code == 1


def test_ci_script_rejects_outputs_outside_trusted_root(tmp_path: Path) -> None:
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()

    code = main(
        [
            "--trusted-output-root",
            str(trusted_root),
            "--artifact-dir",
            str(tmp_path / "outside-artifacts"),
            "--output",
            str(tmp_path / "outside.json"),
            "--markdown",
            str(tmp_path / "outside.md"),
        ]
    )

    assert code == 2
    assert not (tmp_path / "outside-artifacts").exists()
    assert not (tmp_path / "outside.json").exists()
    assert not (tmp_path / "outside.md").exists()
