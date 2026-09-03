from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci_docs_status_sync import (
    actual_drc_rule_count,
    actual_erc_rule_count,
    actual_mcp_admin_tool_names,
    actual_mcp_tool_count,
    actual_tool_count,
    main,
    validate_docs,
)


def test_actual_erc_rule_count_matches_runner() -> None:
    from zaptrace.erc.runner import _ALL_RULES

    assert actual_erc_rule_count() == len(_ALL_RULES) >= 20


def test_actual_drc_rule_count_matches_engine() -> None:
    from zaptrace.ee.drc.engine import _ALL_CHECKS

    assert actual_drc_rule_count() == len(_ALL_CHECKS) >= 11


def test_actual_tool_count_matches_registry() -> None:
    from zaptrace.agent._tool_impls import TOOL_REGISTRY

    assert actual_tool_count() == len(TOOL_REGISTRY) >= 50


def test_actual_mcp_tool_count_includes_session_administration() -> None:
    assert actual_mcp_admin_tool_names() == ["session_create", "session_destroy", "session_list"]
    assert actual_mcp_tool_count() == actual_tool_count() + 3


def test_docs_status_sync_current_repo_passes() -> None:
    result = validate_docs()
    assert result["passed"], result["errors"]


def test_docs_status_sync_cli_writes_report(tmp_path: Path) -> None:
    output = tmp_path / "docs-status.json"
    assert main(["--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["erc_rule_count"] == actual_erc_rule_count()
    assert report["drc_rule_count"] == actual_drc_rule_count()
    assert report["tool_count"] == actual_tool_count()
    assert report["mcp_admin_tools"] == actual_mcp_admin_tool_names()
    assert report["mcp_tool_count"] == actual_mcp_tool_count()


def test_docs_workflow_validates_pull_requests_without_deploying() -> None:
    workflow = Path(".github/workflows/docs.yml").read_text(encoding="utf-8")

    assert "  pull_request:" in workflow
    assert "uvx --no-build --from mkdocs-material==9.6.21 mkdocs build --strict" in workflow
    deploy = workflow.split("  deploy:", 1)[1]
    assert "if: github.event_name == 'push'" in deploy


def test_all_public_markdown_pages_are_in_mkdocs_navigation() -> None:
    from scripts import ci_docs_status_sync

    assert ci_docs_status_sync.navigation_gaps() == []


def test_documented_release_gate_command_matches_ci_contract() -> None:
    document = Path("docs/development/validation-environment.md").read_text(encoding="utf-8")

    assert "--risky-package-reviewed" in document
    assert '--risky-package-approval-id "GENERATED-BOARD-BASELINE-REVIEW-2026-07-22"' in document


def test_public_docs_use_current_examples_plugin_and_support_paths() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    getting_started = Path("docs/GETTING_STARTED.md").read_text(encoding="utf-8")
    faq = Path("docs/FAQ.md").read_text(encoding="utf-8")
    plugin_guide = Path("docs/plugins/development-guide.md").read_text(encoding="utf-8")

    assert "https://github.com/oaslananka/zaptrace/discussions" in readme
    assert "GitHub Discussions is currently disabled" not in readme
    assert "../examples/" not in getting_started
    assert "../examples/" not in faq
    assert "zaptrace/plugins/" not in plugin_guide
    assert "zaptrace/plugin/" in plugin_guide


def test_maturity_docs_match_live_repository_capabilities() -> None:
    maturity = Path("docs/repo-maturity-report.md").read_text(encoding="utf-8")
    openssf = Path("docs/openssf-evidence.md").read_text(encoding="utf-8")
    gaps = Path("docs/openssf-gap-analysis.md").read_text(encoding="utf-8")
    current_state = Path("docs/strategy/current-state-audit.md").read_text(encoding="utf-8")
    dependency = Path("docs/security/dependency-and-static-analysis.md").read_text(encoding="utf-8")

    for stale in (
        "| Fuzzing | Missing |",
        "fuzzing workflow because no fuzz harness exists",
        "heavy Docker vulnerability scan because",
        "checksum manifest automation if required",
        "Admin-enforced branch protection was not enabled",
        "[#80]",
        "[#81]",
        "[#82]",
        "[#84]",
        "[#85]",
    ):
        assert stale not in maturity
        assert stale not in gaps

    assert "config/github-main-ruleset.json" in maturity
    assert "repository-ruleset-evidence.json" in openssf
    assert "machine-verifiable periodic capture is still future work" not in current_state
    assert "Branch protection continues to require the three stable Python check names" not in dependency


def test_docs_status_report_tracks_component_library_baseline_and_revision() -> None:
    report = validate_docs()
    baseline = json.loads(Path("config/component-trust-baseline.json").read_text(encoding="utf-8"))

    assert "component_library" in report
    assert report["component_library"]["source"] == "config/component-trust-baseline.json"
    assert report["component_library"]["component_count"] == baseline["component_count"]
    assert report["component_library"]["trust_tier_counts"] == {"heuristic": baseline["component_count"]}
    assert len(report["source_revision"]) == 40


def test_docs_status_report_tracks_current_import_and_release_capabilities() -> None:
    capabilities = validate_docs()["capabilities"]
    required = {
        "kicad_project_import",
        "github_release",
        "sbom_generation",
        "release_attestation",
    }

    assert required <= capabilities.keys()
    assert all(capabilities[name] for name in required)


def test_internal_implementation_plans_are_not_public_docs() -> None:
    assert not Path("docs/superpowers").exists()
    assert "superpowers/" not in Path("mkdocs.yml").read_text(encoding="utf-8")


def test_current_state_audit_uses_machine_derived_current_facts() -> None:
    baseline = json.loads(Path("config/component-trust-baseline.json").read_text(encoding="utf-8"))
    current_state = Path("docs/strategy/current-state-audit.md").read_text(encoding="utf-8")

    assert f"{baseline['component_count']} component records" in current_state
    assert "~50 packages supported" not in current_state
    assert "KiCad export is unidirectional" not in current_state
    assert "No release automation" not in current_state
    assert "config/component-trust-baseline.json" in current_state
    assert "scripts/ci_docs_status_sync.py" in current_state


def test_current_state_guard_rejects_reintroduced_drift(tmp_path: Path) -> None:
    from scripts import ci_docs_status_sync

    validator = getattr(ci_docs_status_sync, "_validate_current_state_document", None)
    assert validator is not None

    stale = tmp_path / "current-state-audit.md"
    stale.write_text(
        "503 component records\nKiCad export is unidirectional — no import capability\nNo release automation\n",
        encoding="utf-8",
    )
    errors = validator(stale)

    assert any("claims 503 component records but code has 504" in error for error in errors)
    assert any("KiCad export is unidirectional" in error for error in errors)
    assert any("No release automation" in error for error in errors)


def test_public_facts_matches_committed_configuration() -> None:
    from scripts.ci_docs_status_sync import load_public_facts

    facts = load_public_facts()
    assert facts, "public-facts.json should load successfully"
    assert facts["package"]["name"] == "zaptrace-eda"
    assert facts["package"]["import_name"] == "zaptrace"
    assert facts["package"]["current_version"] == "0.3.5.dev0"
    assert facts["package"]["status"] == "unreleased-development"
    assert facts["package"]["latest_published_tag"] == "v0.3.3"

    mcp = facts["mcp"]
    assert mcp["total_exposed_tool_count"] == actual_mcp_tool_count()
    assert mcp["design_tool_count"] == actual_tool_count()
    assert mcp["session_admin_tool_count"] == len(actual_mcp_admin_tool_names())
    assert mcp["session_tools"] == actual_mcp_admin_tool_names()

    docs = facts["documentation"]
    assert docs["deployment_source_sha"] == "HEAD"
    assert docs["freshness_check_enabled"] is True
    assert docs["deployment_evidence_path"] == "site/deployment-provenance.json"
    assert docs["deployment_provenance_url"] == "https://oaslananka.github.io/zaptrace/deployment-provenance.json"


def test_public_facts_validation_detects_deliberate_mismatch() -> None:
    from scripts.ci_docs_status_sync import _validate_public_facts, load_public_facts, source_revision

    facts = load_public_facts()
    revision = source_revision()

    # Base state passes
    assert _validate_public_facts(facts, revision) == []

    # Deliberate MCP tool count mismatch fails
    bad_facts = json.loads(json.dumps(facts))
    bad_facts["mcp"]["total_exposed_tool_count"] = 999
    bad_facts["mcp"]["design_tool_count"] = 996
    errors = _validate_public_facts(bad_facts, revision)
    assert any("claims 96 MCP tools but public-facts has 999" in e for e in errors)
    assert any("claims 93 design tools but public-facts has 996" in e for e in errors)

    # Deliberate deployment SHA mismatch fails
    bad_sha_facts = json.loads(json.dumps(facts))
    bad_sha_facts["documentation"]["deployment_source_sha"] = "0000000000000000000000000000000000000000"
    errors = _validate_public_facts(bad_sha_facts, revision)
    assert any("documentation deployment source SHA mismatch" in e for e in errors)

    # Deployment source SHA missing or 'unknown' fails fail-closed
    unknown_facts = json.loads(json.dumps(facts))
    unknown_facts["documentation"]["deployment_source_sha"] = "unknown"
    errors = _validate_public_facts(unknown_facts, revision)
    assert any("missing or 'unknown'" in e for e in errors)


def test_deployment_evidence_verification_fail_closed(tmp_path: Path) -> None:
    from scripts.ci_docs_status_sync import _validate_public_facts, load_public_facts, source_revision

    facts = load_public_facts()
    revision = source_revision()

    valid_evidence = tmp_path / "valid-provenance.json"
    valid_evidence.write_text(json.dumps({"source_sha": revision, "deployment_timestamp": "2026-09-02T12:00:00Z"}))
    assert _validate_public_facts(facts, revision, deployment_evidence_path=valid_evidence) == []

    mismatched_evidence = tmp_path / "mismatched-provenance.json"
    mismatched_evidence.write_text(
        json.dumps({"source_sha": "0000000000000000000000000000000000000000", "deployment_timestamp": "now"})
    )
    errors = _validate_public_facts(facts, revision, deployment_evidence_path=mismatched_evidence)
    assert any("deployment provenance evidence mismatch" in e for e in errors)

    corrupt_evidence = tmp_path / "corrupt-provenance.json"
    corrupt_evidence.write_text("not json content")
    errors = _validate_public_facts(facts, revision, deployment_evidence_path=corrupt_evidence)
    assert any("failed to read deployment provenance evidence" in e for e in errors)


def test_verify_deployment_freshness_robust_polling_success() -> None:
    from scripts.ci_docs_status_sync import verify_deployment_freshness

    expected_sha = "180e6aef31c87eef86a0c995540ec2ecfd27deb9"
    calls: list[str] = []
    sleeps: list[float] = []

    def mock_fetch(url: str) -> str:
        calls.append(url)
        if len(calls) == 1:
            # First attempt returns stale deployment provenance
            return json.dumps(
                {
                    "source_sha": "b7fa54075747088cc8996293455f3a604ed5e259",
                    "deployment_timestamp": "2026-08-21T00:00:00Z",
                }
            )
        return json.dumps(
            {
                "source_sha": expected_sha,
                "deployment_timestamp": "2026-09-03T02:00:00Z",
            }
        )

    def mock_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    result = verify_deployment_freshness(
        expected_sha=expected_sha,
        max_attempts=5,
        initial_backoff=2.0,
        backoff_multiplier=2.0,
        fetcher=mock_fetch,
        sleeper=mock_sleep,
    )

    assert result["passed"] is True
    assert result["attempts"] == 2
    assert result["deployed_sha"] == expected_sha
    assert sleeps == [2.0]


def test_verify_deployment_freshness_robust_polling_timeout() -> None:
    from scripts.ci_docs_status_sync import verify_deployment_freshness

    expected_sha = "180e6aef31c87eef86a0c995540ec2ecfd27deb9"

    def mock_fetch(url: str) -> str:
        return json.dumps(
            {
                "source_sha": "0000000000000000000000000000000000000000",
                "deployment_timestamp": "stale",
            }
        )

    result = verify_deployment_freshness(
        expected_sha=expected_sha,
        max_attempts=3,
        initial_backoff=0.1,
        fetcher=mock_fetch,
        sleeper=lambda s: None,
    )

    assert result["passed"] is False
    assert result["attempts"] == 3
    assert "does not match expected revision" in result["error"]


def test_docs_workflow_embeds_provenance_and_verifies_freshness() -> None:
    workflow = Path(".github/workflows/docs.yml").read_text(encoding="utf-8")

    # Workflow uses uv run --no-project for docs status validation
    assert "uv run --no-project python scripts/ci_docs_status_sync.py" in workflow

    # Workflow captures source SHA and embeds deployment provenance
    assert "Capture source SHA" in workflow
    assert "site/deployment-provenance.json" in workflow
    assert "source_sha" in workflow
    assert "deployment_timestamp" in workflow

    # Post-deploy freshness verification job exists and uses robust backoff
    assert "freshness-check:" in workflow
    assert "Post-deploy freshness verification" in workflow
    assert "--verify-freshness" in workflow
    assert "--expected-sha" in workflow
    assert "deployed-provenance.json" in workflow

    # Repo self-mutation is not performed
    assert "Update public-facts with deployment info" not in workflow


def test_deployment_evidence_path_traversal_rejected_fail_closed(tmp_path: Path) -> None:
    from scripts.ci_docs_status_sync import (
        _validate_public_facts,
        _validate_safe_evidence_path,
        load_public_facts,
        source_revision,
    )

    with pytest.raises(ValueError, match="path traversal"):
        _validate_safe_evidence_path("../../../etc/passwd")

    with pytest.raises(ValueError, match="escapes allowed"):
        _validate_safe_evidence_path("/some/unauthorized/root/file.json")

    facts = load_public_facts()
    revision = source_revision()
    errors = _validate_public_facts(facts, revision, deployment_evidence_path=Path("../traversal.json"))
    assert any("invalid deployment provenance evidence path" in e for e in errors)


def test_provenance_url_ssrf_rejected_fail_closed() -> None:
    from scripts.ci_docs_status_sync import _default_provenance_fetcher, _validate_safe_provenance_url

    with pytest.raises(ValueError, match="invalid scheme"):
        _validate_safe_provenance_url("http://oaslananka.github.io/zaptrace/deployment-provenance.json")

    with pytest.raises(ValueError, match="unauthorized host"):
        _validate_safe_provenance_url("https://malicious.evil.com/deployment-provenance.json")

    with pytest.raises(ValueError, match="unauthorized host"):
        _validate_safe_provenance_url("https://169.254.169.254/latest/meta-data")

    with pytest.raises(ValueError, match="unauthorized host"):
        _default_provenance_fetcher("https://evil.internal.net/steal")

    custom_url = "https://oaslananka.github.io/zaptrace/custom-provenance.json"
    assert _validate_safe_provenance_url(custom_url) == custom_url
    assert _validate_safe_provenance_url(f"  {custom_url}  ") == custom_url


def test_verify_freshness_cli_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import scripts.ci_docs_status_sync as sync_mod

    expected_sha = "180e6aef31c87eef86a0c995540ec2ecfd27deb9"

    def mock_fetch(url: str) -> str:
        return json.dumps(
            {
                "source_sha": expected_sha,
                "deployment_timestamp": "2026-09-03T02:00:00Z",
            }
        )

    monkeypatch.setattr(sync_mod, "_default_provenance_fetcher", mock_fetch)

    output = tmp_path / "freshness-report.json"
    code = main(
        [
            "--verify-freshness",
            "--expected-sha",
            expected_sha,
            "--output",
            str(output),
            "--max-attempts",
            "1",
        ]
    )
    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["deployed_sha"] == expected_sha
