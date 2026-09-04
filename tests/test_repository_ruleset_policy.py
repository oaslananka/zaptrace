from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
POLICY = ROOT / "config" / "github-main-ruleset.json"


def test_main_ruleset_policy_defines_stable_required_checks() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))

    assert policy["name"] == "main-branch-integrity"
    assert policy["target"] == "branch"
    assert policy["enforcement"] == "active"
    assert policy["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    assert policy["bypass_actors"] == []

    required = next(rule for rule in policy["rules"] if rule["type"] == "required_status_checks")
    contexts = {entry["context"] for entry in required["parameters"]["required_status_checks"]}
    assert contexts == {
        "Release gate summary",
        "Security gate",
        "Repository hooks",
        "Repository hygiene",
        "Dependency review",
        "Container security gate",
    }
    assert required["parameters"]["strict_required_status_checks_policy"] is True

    rule_types = {rule["type"] for rule in policy["rules"]}
    assert {
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "pull_request",
        "required_status_checks",
    }.issubset(rule_types)


def test_security_workflow_exposes_one_stable_aggregate_gate() -> None:
    workflow = (WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8")

    gate = workflow.split("  security-gate:", 1)[1]
    assert "name: Security gate" in gate
    assert "needs: [audit, cargo-audit, semgrep, codeql]" in gate
    assert "if: always()" in gate
    for result in ("audit", "cargo-audit", "semgrep", "codeql"):
        assert f"${{{{ needs.{result}.result }}}}" in gate


def test_container_workflow_always_emits_stable_gate_without_always_scanning() -> None:
    workflow = (WORKFLOWS / "container-security.yml").read_text(encoding="utf-8")
    trigger = workflow.split("permissions:", 1)[0]

    assert "paths:" not in trigger
    assert "  changes:" in workflow
    assert "scan_required" in workflow
    assert "if: needs.changes.outputs.scan_required == 'true'" in workflow

    gate = workflow.split("  container-security-gate:", 1)[1]
    assert "name: Container security gate" in gate
    assert "needs: [changes, scan]" in gate
    assert "if: always()" in gate
    assert "needs.changes.outputs.scan_required" in gate
    assert "needs.scan.result" in gate


def test_repository_hygiene_validates_live_ruleset_contract() -> None:
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert "scripts/ci_repository_ruleset.py" in workflow
    assert '--repository "$GITHUB_REPOSITORY"' in workflow
    assert "--policy config/github-main-ruleset.json" in workflow
    assert "--strict" in workflow
    assert "repository-ruleset-evidence.json" in workflow


def test_ruleset_validator_accepts_matching_live_configuration() -> None:
    from scripts import ci_repository_ruleset

    policy = {
        "name": "main-branch-integrity",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "Release gate summary"}],
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                },
            },
        ],
    }
    live = {
        "name": "main-branch-integrity",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {"type": "deletion"},
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "Release gate summary", "integration_id": 15368}],
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                },
            },
        ],
    }

    assert ci_repository_ruleset.compare_ruleset(policy, live) == []


def test_ruleset_validator_rejects_missing_check_and_disabled_enforcement() -> None:
    from scripts import ci_repository_ruleset

    policy = {
        "name": "main-branch-integrity",
        "target": "branch",
        "enforcement": "active",
        "bypass_actors": [],
        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [
                        {"context": "Release gate summary"},
                        {"context": "Security gate"},
                    ],
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                },
            }
        ],
    }
    live = {
        **policy,
        "enforcement": "disabled",
        "rules": [
            {
                "type": "required_status_checks",
                "parameters": {
                    "required_status_checks": [{"context": "Release gate summary"}],
                    "strict_required_status_checks_policy": True,
                    "do_not_enforce_on_create": False,
                },
            }
        ],
    }

    errors = ci_repository_ruleset.compare_ruleset(policy, live)

    assert any("enforcement" in error for error in errors)
    assert any("Security gate" in error for error in errors)


def test_governance_documents_solo_maintainer_ruleset_and_emergency_process() -> None:
    document = (ROOT / "docs" / "governance" / "main-branch-ruleset.md").read_text(encoding="utf-8")

    for phrase in (
        "Release gate summary",
        "Security gate",
        "Repository hooks",
        "Repository hygiene",
        "Dependency review",
        "Container security gate",
        "zero required approvals",
        "independent review",
        "emergency",
        "rule suite",
    ):
        assert phrase in document


def test_ruleset_fetch_rejects_non_github_repository_identifier() -> None:
    from scripts import ci_repository_ruleset

    with pytest.raises(ValueError, match="owner/name"):
        ci_repository_ruleset.fetch_ruleset("https://attacker.invalid/repo", "main-branch-integrity")


def test_ruleset_request_rejects_non_positive_identifier() -> None:
    from scripts import ci_repository_ruleset

    with pytest.raises(ValueError, match="positive integer"):
        ci_repository_ruleset._request_json("oaslananka/zaptrace", ruleset_id=0)


def test_ruleset_request_uses_fixed_github_origin(monkeypatch) -> None:
    from scripts import ci_repository_ruleset

    observed: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return Response()

    monkeypatch.setattr(ci_repository_ruleset.urllib.request, "urlopen", fake_urlopen)

    assert ci_repository_ruleset._request_json("oaslananka/zaptrace") == []
    assert observed == {
        "url": "https://api.github.com/repos/oaslananka/zaptrace/rulesets?per_page=100",
        "timeout": 30,
    }


def test_mergify_queue_uses_stable_aggregate_required_checks() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    expected = {
        "Release gate summary",
        "Security gate",
        "Repository hooks",
        "Repository hygiene",
        "Dependency review",
        "Container security gate",
    }
    expected_success = {f"check-success = {name}" for name in expected}
    expected_failure = {f"check-failure = {name}" for name in expected}

    queue = next(rule for rule in config["queue_rules"] if rule["name"] == "default")
    assert set(queue["queue_conditions"]) == expected_success
    assert set(queue["merge_conditions"]) == expected_success

    automatic = next(rule for rule in config["pull_request_rules"] if rule["name"] == "automatic merge on CI success")
    assert expected_success <= set(automatic["conditions"])

    failure_rule = next(rule for rule in config["pull_request_rules"] if rule["name"] == "label CI failure")
    assert set(failure_rule["conditions"][0]["or"]) == expected_failure


def test_mergify_config_has_no_unsupported_dequeue_queue_action() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))

    for rule in config["pull_request_rules"]:
        queue_action = rule.get("actions", {}).get("queue")
        if isinstance(queue_action, dict):
            assert "method" not in queue_action


def test_mergify_queue_is_solo_compatible_and_uses_in_place_checks() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))

    assert config["merge_queue"]["mode"] == "serial"
    assert config["merge_queue"]["max_parallel_checks"] == 1
    queue = next(rule for rule in config["queue_rules"] if rule["name"] == "default")
    assert queue["batch_size"] == 1

    automatic = next(rule for rule in config["pull_request_rules"] if rule["name"] == "automatic merge on CI success")
    string_conditions = [condition for condition in automatic["conditions"] if isinstance(condition, str)]
    assert not any("approved-reviews-by" in condition for condition in string_conditions)
    assert all(rule["name"] != "request review on new PR" for rule in config["pull_request_rules"])
