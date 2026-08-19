from __future__ import annotations

import importlib.util
import json
import secrets
from datetime import UTC, date, datetime
from pathlib import Path
from types import ModuleType
from urllib.parse import parse_qs
from urllib.request import Request

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sonar_new_code_baseline.py"
POLICY = ROOT / ".github" / "sonar-new-code-baseline.json"
WORKFLOW = ROOT / ".github" / "workflows" / "sonar-baseline.yml"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sonar_new_code_baseline_under_test", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_policy_uses_explicit_date_baseline() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy == {
        "schema_version": "1.0",
        "project_key": "oaslananka_zaptrace",
        "definition_type": "date",
        "value": "2026-07-21",
        "tracking_issue": 296,
        "historical_backlog_policy": "visible-and-triaged-separately",
    }


def test_policy_validation_rejects_future_or_wrong_project_baseline() -> None:
    module = _module()
    valid = {
        "schema_version": "1.0",
        "project_key": "oaslananka_zaptrace",
        "definition_type": "date",
        "value": "2026-07-21",
        "tracking_issue": 296,
        "historical_backlog_policy": "visible-and-triaged-separately",
    }

    baseline_day = date(2026, 7, 21)
    assert module.validate_policy(valid, today=baseline_day)["value"] == "2026-07-21"

    wrong_project = {**valid, "project_key": "other_project"}
    with pytest.raises(RuntimeError, match="project_key"):
        module.validate_policy(wrong_project, today=baseline_day)

    future_policy = {**valid, "value": "2026-07-22"}
    with pytest.raises(RuntimeError, match="future"):
        module.validate_policy(future_policy, today=baseline_day)


def test_apply_sets_both_sonar_settings_and_verifies_exact_values(tmp_path: Path) -> None:
    module = _module()
    requests: list[Request] = []
    secret_value = secrets.token_urlsafe(32)
    module.DEFAULT_EVIDENCE_PATH = tmp_path / "summary.json"

    def transport(request: Request) -> bytes:
        requests.append(request)
        if request.get_method() == "POST":
            return b"{}"
        return json.dumps(
            {
                "settings": [
                    {"key": "sonar.leak.period", "value": "2026-07-21"},
                    {"key": "sonar.leak.period.type", "value": "date"},
                ]
            }
        ).encode()

    report = module.apply_policy(
        module.load_policy(),
        token=secret_value,
        transport=transport,
        now=datetime(2026, 7, 21, 14, 30, tzinfo=UTC),
    )

    assert [request.get_method() for request in requests] == ["POST", "POST", "GET"]
    post_forms = [parse_qs(request.data.decode()) for request in requests[:2] if request.data is not None]
    assert post_forms == [
        {
            "component": ["oaslananka_zaptrace"],
            "key": ["sonar.leak.period"],
            "value": ["2026-07-21"],
        },
        {
            "component": ["oaslananka_zaptrace"],
            "key": ["sonar.leak.period.type"],
            "value": ["date"],
        },
    ]
    assert all(request.get_header("Authorization") == f"Bearer {secret_value}" for request in requests)
    assert report["verified"] is True
    assert report["settings"] == {
        "sonar.leak.period": "2026-07-21",
        "sonar.leak.period.type": "date",
    }
    evidence = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert secret_value not in evidence
    assert json.loads(evidence)["applied_at"] == "2026-07-21T14:30:00Z"


def test_apply_requires_token_and_rejects_mismatched_verification(tmp_path: Path) -> None:
    module = _module()
    policy = module.load_policy()
    module.DEFAULT_EVIDENCE_PATH = tmp_path / "x.json"
    secret_value = secrets.token_urlsafe(32)

    with pytest.raises(RuntimeError, match="SONAR_TOKEN"):
        module.apply_policy(policy, token="", transport=lambda request: b"{}")

    def mismatched_transport(request: Request) -> bytes:
        if request.get_method() == "POST":
            return b"{}"
        return b'{"settings":[{"key":"sonar.leak.period","value":"previous_version"}]}'

    with pytest.raises(RuntimeError, match="verification failed"):
        module.apply_policy(
            policy,
            token=secret_value,
            transport=mismatched_transport,
        )


def test_workflow_is_manual_bounded_and_does_not_run_a_scanner() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow
    assert "push:" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}" in workflow
    assert "run: python3 scripts/sonar_new_code_baseline.py" in workflow
    assert "--policy" not in workflow
    assert "--evidence" not in workflow
    assert "sonar-scanner" not in workflow
    assert "sonarqube-scan-action" not in workflow
    assert "artifacts/sonar-baseline/" in workflow
