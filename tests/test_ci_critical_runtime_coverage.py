"""Critical runtime coverage policy and CI report tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts.ci_critical_runtime_coverage import audit_critical_coverage, build_report, load_policy, render_markdown

POLICY_PATH = Path("config/critical-runtime-coverage.json")
EXPECTED_FLOORS = {
    "zaptrace/mcp/server.py": 78.94,
    "zaptrace/agent/execution.py": 77.22,
    "zaptrace/api/server.py": 91.34,
    "zaptrace/api/abuse_control.py": 90.0,
    "zaptrace/api/routes/_session.py": 95.65,
    "zaptrace/security/objects.py": 99.21,
    "zaptrace/security/policy.py": 93.54,
    "zaptrace/security/release.py": 92.08,
    "zaptrace/api/routes/release_export.py": 100.0,
}


def _write_project(root: Path, *, omit: list[str] | None = None, pragma: bool = False) -> None:
    omit_lines = json.dumps(omit or ["*/tests/*"])
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "zaptrace"\n'
        'version = "0.3.0"\n\n'
        "[tool.coverage.run]\n"
        'source = ["zaptrace"]\n'
        f"omit = {omit_lines}\n",
        encoding="utf-8",
    )
    for relative in EXPECTED_FLOORS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = "  # pragma: no cover" if pragma and relative == "zaptrace/mcp/server.py" else ""
        path.write_text(f"def covered():{suffix}\n    return True\n", encoding="utf-8")


def _policy_payload(
    *,
    floors: dict[str, float] | None = None,
    exceptions: list[dict[str, object]] | None = None,
    allowed_exclusions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    selected = floors or EXPECTED_FLOORS
    return {
        "schema_version": "1.0",
        "modules": [
            {
                "path": path,
                "owner": "@oaslananka",
                "minimum_line_coverage": floor,
                "rationale": "Security-critical runtime boundary.",
            }
            for path, floor in selected.items()
        ],
        "exceptions": exceptions or [],
        "allowed_exclusions": allowed_exclusions or [],
    }


def _write_policy(root: Path, payload: dict[str, object] | None = None) -> Path:
    path = root / "config/critical-runtime-coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or _policy_payload(), indent=2) + "\n", encoding="utf-8")
    return path


def _write_coverage(root: Path, percentages: dict[str, float] | None = None) -> Path:
    selected = percentages or {path: 100.0 for path in EXPECTED_FLOORS}
    files = {}
    for path, percent in selected.items():
        statements = 100
        covered = int(percent)
        files[path] = {
            "summary": {
                "covered_lines": covered,
                "num_statements": statements,
                "percent_covered": percent,
            }
        }
    coverage_path = root / "coverage.json"
    coverage_path.write_text(json.dumps({"meta": {"version": "7.14.1"}, "files": files}), encoding="utf-8")
    return coverage_path


def test_committed_policy_matches_approved_baseline_and_owner() -> None:
    policy = load_policy(POLICY_PATH)

    assert {item.path: item.minimum_line_coverage for item in policy.modules} == EXPECTED_FLOORS
    assert {item.owner for item in policy.modules} == {"@oaslananka"}
    assert policy.exceptions == []
    assert policy.allowed_exclusions == []


def test_audit_passes_when_every_module_meets_floor(tmp_path: Path) -> None:
    _write_project(tmp_path)
    policy_path = _write_policy(tmp_path)
    coverage_path = _write_coverage(tmp_path)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is True
    assert result.violations == []
    assert all(module.status == "pass" for module in result.modules)


def test_audit_fails_when_critical_module_is_missing(tmp_path: Path) -> None:
    _write_project(tmp_path)
    policy_path = _write_policy(tmp_path)
    percentages = {path: 100.0 for path in EXPECTED_FLOORS if path != "zaptrace/mcp/server.py"}
    coverage_path = _write_coverage(tmp_path, percentages)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    assert any(
        item.code == "missing-module-coverage" and item.path == "zaptrace/mcp/server.py" for item in result.violations
    )


def test_audit_fails_when_module_drops_below_approved_floor(tmp_path: Path) -> None:
    _write_project(tmp_path)
    policy_path = _write_policy(tmp_path)
    percentages = {path: 100.0 for path in EXPECTED_FLOORS}
    percentages["zaptrace/agent/execution.py"] = 77.21
    coverage_path = _write_coverage(tmp_path, percentages)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    violation = next(item for item in result.violations if item.code == "coverage-below-floor")
    assert violation.path == "zaptrace/agent/execution.py"
    assert "77.21" in violation.message
    assert "77.22" in violation.message


def test_audit_rejects_broad_omit_covering_critical_module(tmp_path: Path) -> None:
    _write_project(tmp_path, omit=["*/tests/*", "*/mcp/server.py"])
    policy_path = _write_policy(tmp_path)
    coverage_path = _write_coverage(tmp_path)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    assert any(
        item.code == "critical-module-omitted" and item.path == "zaptrace/mcp/server.py" for item in result.violations
    )


def test_audit_rejects_global_exclude_also_rules(tmp_path: Path) -> None:
    _write_project(tmp_path)
    with (tmp_path / "pyproject.toml").open("a", encoding="utf-8") as handle:
        handle.write('\n[tool.coverage.report]\nexclude_also = ["if TYPE_CHECKING:"]\n')
    policy_path = _write_policy(tmp_path)
    coverage_path = _write_coverage(tmp_path)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    assert any(item.code == "global-coverage-exclusion" and item.path == "pyproject.toml" for item in result.violations)


def test_audit_rejects_unapproved_pragma_no_cover(tmp_path: Path) -> None:
    _write_project(tmp_path, pragma=True)
    policy_path = _write_policy(tmp_path)
    coverage_path = _write_coverage(tmp_path)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    assert any(
        item.code == "unapproved-coverage-exclusion" and item.path == "zaptrace/mcp/server.py:1"
        for item in result.violations
    )


def test_active_reviewed_exception_temporarily_lowers_floor(tmp_path: Path) -> None:
    _write_project(tmp_path)
    policy_path = _write_policy(
        tmp_path,
        _policy_payload(
            exceptions=[
                {
                    "path": "zaptrace/mcp/server.py",
                    "minimum_line_coverage": 70.0,
                    "rationale": "Temporary refactor window with equivalent branch tests.",
                    "approved_by": "@oaslananka",
                    "tracking_issue": "https://github.com/oaslananka/zaptrace/issues/300",
                    "expires_on": "2026-07-31",
                }
            ]
        ),
    )
    percentages = {path: 100.0 for path in EXPECTED_FLOORS}
    percentages["zaptrace/mcp/server.py"] = 75.0
    coverage_path = _write_coverage(tmp_path, percentages)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    module = next(item for item in result.modules if item.path == "zaptrace/mcp/server.py")
    assert result.passed is True
    assert module.status == "exception-approved"
    assert module.required_line_coverage == 70.0


def test_expired_exception_is_rejected(tmp_path: Path) -> None:
    _write_project(tmp_path)
    policy_path = _write_policy(
        tmp_path,
        _policy_payload(
            exceptions=[
                {
                    "path": "zaptrace/mcp/server.py",
                    "minimum_line_coverage": 70.0,
                    "rationale": "Expired temporary refactor window.",
                    "approved_by": "@oaslananka",
                    "tracking_issue": "https://github.com/oaslananka/zaptrace/issues/300",
                    "expires_on": "2026-07-21",
                }
            ]
        ),
    )
    percentages = {path: 100.0 for path in EXPECTED_FLOORS}
    percentages["zaptrace/mcp/server.py"] = 75.0
    coverage_path = _write_coverage(tmp_path, percentages)

    result = audit_critical_coverage(
        root=tmp_path,
        coverage_path=coverage_path,
        policy_path=policy_path,
        today=date(2026, 7, 22),
    )

    assert result.passed is False
    assert any(item.code == "expired-coverage-exception" for item in result.violations)


def test_repository_configuration_does_not_hide_critical_modules(tmp_path: Path) -> None:
    coverage_path = _write_coverage(tmp_path)

    result = audit_critical_coverage(
        root=Path("."),
        coverage_path=coverage_path,
        policy_path=POLICY_PATH,
        today=date(2026, 7, 22),
    )

    assert not [
        item
        for item in result.violations
        if item.code
        in {
            "critical-module-omitted",
            "global-coverage-exclusion",
            "unapproved-coverage-exclusion",
            "expired-coverage-exclusion",
            "stale-coverage-exclusion",
        }
    ]


def test_identity_bound_report_and_markdown_use_critical_metrics(tmp_path: Path) -> None:
    coverage_path = _write_coverage(tmp_path)

    report = build_report(root=Path("."), coverage_path=coverage_path, policy_path=POLICY_PATH)
    markdown = render_markdown(report)

    assert report["passed"] is True
    assert report["evidence_identity"]["mode"] == "snapshot"
    assert report["evidence_identity"]["source_commit"]
    assert len(report["coverage_input_sha256"]) == 64
    assert len(report["policy_sha256"]) == 64
    assert "Critical Runtime Coverage" in markdown
    assert "zaptrace/mcp/server.py" in markdown


def test_required_negative_path_tests_remain_present() -> None:
    mcp_tests = Path("tests/test_mcp_server.py").read_text(encoding="utf-8")
    api_tests = Path("tests/test_network_transport_security.py").read_text(encoding="utf-8")
    api_hardening_tests = Path("tests/test_api_hardening.py").read_text(encoding="utf-8")
    object_tests = Path("tests/test_object_authorization.py").read_text(encoding="utf-8")
    transaction_tests = Path("tests/test_transactions.py").read_text(encoding="utf-8")

    for test_name in (
        "test_mcp_denies_write_tool_without_capability_and_records_audit",
        "test_mcp_timeout_rolls_back_mutation_and_records_terminal_audit",
        "test_mcp_cancellation_terminates_worker_and_records_rollback",
        "test_mcp_serializes_same_session_mutators_and_records_commits",
        "test_mcp_release_export_fails_closed_without_current_drc",
    ):
        assert test_name in mcp_tests
    assert "test_rest_non_loopback_startup_fails_without_auth" in api_tests
    assert "test_authenticated_session_scoped_read_requires_explicit_session_header" in api_tests
    assert "test_bearer_token_scopes_override_spoofed_capability_header" in api_hardening_tests
    assert "test_guessed_session_id_cannot_read_or_mutate_sandbox" in object_tests
    assert "test_primary_state_change_blocks_stale_transaction_commit" in transaction_tests
