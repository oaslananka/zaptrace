from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci_sonar_debt.py"
WORKFLOW = ROOT / ".github" / "workflows" / "sonar-debt.yml"
POLICY = ROOT / ".github" / "sonar-debt-policy.json"
SCHEMA = ROOT / "schemas" / "sonar-debt-report-v1.schema.json"
BASELINE = ROOT / "docs" / "reports" / "sonar-historical-debt-baseline.json"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_sonar_debt_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_contract_files_exist() -> None:
    assert SCRIPT.is_file()
    assert WORKFLOW.is_file()
    assert POLICY.is_file()
    assert SCHEMA.is_file()
    assert BASELINE.is_file()


def test_workflow_is_secret_bounded_and_retains_evidence() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "workflow_run:" not in workflow
    assert "pull_request:" not in workflow
    assert "SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39" in workflow
    assert "uv lock --check && uv sync --locked" in workflow
    assert ".venv/bin/python scripts/ci_sonar_debt.py" in workflow
    assert '--expected-analysis-revision "$GITHUB_SHA"' in workflow
    assert "--analysis-attempts 30" in workflow
    assert "--analysis-poll-seconds 10" in workflow
    assert "scripts/ci_sonar_debt.py" in workflow
    assert "sonar-debt-report.json" in workflow
    assert "sonar-debt-report.md" in workflow
    assert "sonar-scanner" not in workflow
    assert "NOSONAR" not in workflow


def test_cli_rejects_missing_token_for_capture(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    monkeypatch.delenv("SONAR_TOKEN", raising=False)
    code = module.main(
        [
            "capture",
            "--trusted-output-root",
            str(tmp_path),
            "--output",
            "report.json",
            "--markdown",
            "report.md",
        ]
    )
    assert code == 2


def test_capture_writes_redacted_artifacts(monkeypatch, tmp_path: Path) -> None:
    module = _module()
    secret_value = "credential-must-not-appear"
    monkeypatch.setenv("SONAR_TOKEN", secret_value)

    class FakeClient:
        token_expiration = "2026-12-31T00:00:00Z"
        api_warnings: list[str] = []

        def __init__(self, *, token: str) -> None:
            assert token == secret_value

        def fetch_latest_analysis(self, *, project_key: str, branch: str) -> tuple[str, str]:
            assert project_key == "oaslananka_zaptrace"
            assert branch == "main"
            return "a" * 40, "2026-07-30T02:45:00Z"

        def fetch_issues(self, *, project_key: str, branch: str) -> list[dict[str, object]]:
            del project_key, branch
            return []

        def fetch_quality_gate(self, *, project_key: str, branch: str) -> str:
            del project_key, branch
            return "OK"

        def fetch_measures(self, *, project_key: str, branch: str, metrics: list[str]) -> dict[str, str]:
            del project_key, branch, metrics
            return {"code_smells": "0"}

    monkeypatch.setattr(module, "SonarWebApiClient", FakeClient)
    monkeypatch.setattr(
        module,
        "capture_evidence_identity",
        lambda **kwargs: SimpleNamespace(
            model_dump=lambda mode="json": {
                "source_commit": "b" * 40,
                "identity_sha256": "c" * 64,
            }
        ),
    )

    code = module.main(
        [
            "capture",
            "--trusted-output-root",
            str(tmp_path),
            "--output",
            "report.json",
            "--markdown",
            "report.md",
        ]
    )

    assert code == 0
    json_text = (tmp_path / "report.json").read_text(encoding="utf-8")
    markdown_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert secret_value not in json_text
    assert secret_value not in markdown_text
    assert json.loads(json_text)["total"] == 0


def test_committed_baseline_matches_schema_and_policy_binding() -> None:
    from jsonschema import Draft202012Validator

    from zaptrace.evidence.sonar_debt import (
        SonarDebtReport,
        load_sonar_debt_policy,
        validate_policy_baseline,
    )

    baseline_payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    schema_payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema_payload).validate(baseline_payload)
    report = SonarDebtReport.model_validate(baseline_payload)
    policy = load_sonar_debt_policy(POLICY, trusted_root=ROOT)
    assert validate_policy_baseline(policy, report) == []
    assert report.total == len(report.findings) == 27
    assert report.blocker_count == 0
    assert report.critical_security_reliability_count == 0
    assert policy.budgets.max_total == 27
    assert policy.tracking_issue is None
    assert policy.implementation_issue == 338
    assert [
        (target.release, target.max_total, target.minimum_reduction_percent) for target in policy.release_targets
    ] == [("0.4.0", 27, 0.0), ("0.5.0", 25, 6.5)]
    assert all("message" not in item and "line" not in item for item in baseline_payload["findings"])
    serialized = json.dumps(baseline_payload)
    assert "Authorization" not in serialized
    assert "Bearer " not in serialized


def test_committed_schema_matches_report_model() -> None:
    from zaptrace.evidence.sonar_debt import SonarDebtReport

    committed = json.loads((ROOT / "schemas/sonar-debt-report-v1.schema.json").read_text(encoding="utf-8"))
    assert committed == SonarDebtReport.model_json_schema()


def test_committed_baseline_hashes_finding_identifiers_and_matches_policy() -> None:
    from zaptrace.evidence.sonar_debt import SonarDebtReport

    baseline_path = ROOT / "docs/reports/sonar-historical-debt-baseline.json"
    policy_path = ROOT / ".github/sonar-debt-policy.json"
    baseline_text = baseline_path.read_text(encoding="utf-8")
    baseline = json.loads(baseline_text)
    policy = json.loads(policy_path.read_text(encoding="utf-8"))

    assert '"key"' not in baseline_text
    assert all(set(finding).issuperset({"finding_id_sha256"}) for finding in baseline["findings"])
    assert all(len(finding["finding_id_sha256"]) == 64 for finding in baseline["findings"])

    report = SonarDebtReport.model_validate(baseline)
    assert report.report_sha256 == report.compute_sha256()
    assert policy["baseline"]["report_sha256"] == report.report_sha256
