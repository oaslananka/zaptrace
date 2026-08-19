"""Static contracts for Codecov observability and GitHub Actions security."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
QUALITY = WORKFLOWS / "quality.yml"
PRE_COMMIT_WORKFLOW = WORKFLOWS / "pre-commit.yml"

CODECOV_ACTION = "codecov/codecov-action@fb8b3582c8e4def4969c97caa2f19720cb33a72f"


def _workflow_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(WORKFLOWS.glob("*.yml")))


def _checkout_steps_without_credential_policy(path: Path) -> list[int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    missing: list[int] = []
    for index, line in enumerate(lines):
        if "uses: actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        block: list[str] = []
        for later in lines[index + 1 :]:
            later_indent = len(later) - len(later.lstrip())
            if later.lstrip().startswith("- ") and later_indent <= indent:
                break
            block.append(later)
        if not any("persist-credentials: false" in item for item in block):
            missing.append(index + 1)
    return missing


def test_codecov_status_policy_tracks_project_and_patch_regressions() -> None:
    config = yaml.safe_load((ROOT / "codecov.yml").read_text(encoding="utf-8"))
    statuses = config["coverage"]["status"]

    for status_name in ("project", "patch"):
        default = statuses[status_name]["default"]
        assert default["target"] == "auto"
        assert str(default["threshold"]) == "1%"
    assert config["github_checks"]["annotations"] is True


def test_quality_matrix_generates_and_uploads_junit_results() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")

    assert "JUNIT_PATH: junit-lane-${{ matrix.artifact }}.xml" in workflow
    assert '--junitxml "$JUNIT_PATH"' in workflow
    assert "junit-${lane}-${{ matrix.python-version }}.xml" in workflow
    assert workflow.count("-o junit_family=legacy") >= 2
    assert workflow.count(CODECOV_ACTION) == 2
    assert "codecov/test-results-action@" not in workflow
    assert "report_type: test_results" in workflow
    assert "token: ${{ secrets.CODECOV_TOKEN }}" in workflow
    assert "files: ${{ env.JUNIT_PATH }}" in workflow
    assert "flags: lane-${{ matrix.artifact }}" in workflow
    assert "fail_ci_if_error: true" in workflow
    assert "!cancelled()" in workflow
    assert "github.event.pull_request.head.repo.full_name == github.repository" in workflow
    assert "test-lane-report-${{ matrix.artifact }}.json" in workflow


def test_coverage_upload_is_explicit_and_fails_on_uploader_errors() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")

    assert CODECOV_ACTION in workflow
    coverage_block = workflow[workflow.index("- name: Upload combined coverage") :]
    coverage_block = coverage_block[: coverage_block.index("\n  rust:")]
    assert "files: ./coverage.xml" in coverage_block
    assert "disable_search: true" in coverage_block
    assert "fail_ci_if_error: true" in coverage_block
    assert "coverage combine test-lane-artifacts" in workflow


def test_bundle_analysis_is_explicitly_out_of_scope() -> None:
    guide = (ROOT / "docs" / "development" / "ci-observability.md").read_text(encoding="utf-8")

    assert "Bundle Analysis" in guide
    assert "Vite" in guide
    assert "Webpack" in guide
    assert "not enabled" in guide
    assert "bundle-analysis" not in _workflow_text().lower()


def test_pre_commit_pins_actionlint_and_zizmor() -> None:
    config = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    assert "repo: https://github.com/rhysd/actionlint" in config
    assert "rev: v1.7.12" in config
    assert "repo: https://github.com/zizmorcore/zizmor-pre-commit" in config
    assert "rev: v1.29.0" in config
    assert "rev: v1.27.0" not in config
    assert "--min-severity=medium" in config
    assert "--strict-collection" in config


def test_required_repository_hook_runs_workflow_security_on_all_files() -> None:
    workflow = PRE_COMMIT_WORKFLOW.read_text(encoding="utf-8")

    assert "pre-commit run actionlint --all-files" in workflow
    assert "pre-commit run zizmor --all-files" in workflow
    assert "Repository hooks" in workflow


def test_checkout_never_persists_credentials() -> None:
    missing = {
        path.name: _checkout_steps_without_credential_policy(path)
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if _checkout_steps_without_credential_policy(path)
    }
    assert missing == {}


def test_workflows_avoid_privileged_pr_trigger_and_shell_template_injection() -> None:
    workflows = _workflow_text()
    fuzz = (WORKFLOWS / "fuzz.yml").read_text(encoding="utf-8")
    auto_assign = (WORKFLOWS / "auto-assign.yml").read_text(encoding="utf-8")

    assert "pull_request_target:" not in workflows
    assert re.search(r"^ {2}pull_request:\s*$", auto_assign, re.MULTILINE)
    assert "github.event.pull_request.head.repo.full_name == github.repository" in auto_assign
    assert "CAMPAIGN_PROFILE: ${{ steps.profile.outputs.value }}" in fuzz
    run_block = fuzz[fuzz.index("- name: Run deterministic fuzz campaign") :]
    assert '--profile "$CAMPAIGN_PROFILE"' in run_block
    assert '--profile "${{ steps.profile.outputs.value }}"' not in run_block


def test_release_workflow_disables_dependency_caches() -> None:
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    setup_count = release.count("uses: astral-sh/setup-uv@")

    assert setup_count >= 3
    assert release.count("enable-cache: false") == setup_count


def test_renovate_validator_uses_committed_npm_lockfile() -> None:
    workflow = (WORKFLOWS / "renovate-config.yml").read_text(encoding="utf-8")
    package = (ROOT / ".github" / "renovate-validation" / "package.json").read_text(encoding="utf-8")
    lockfile = (ROOT / ".github" / "renovate-validation" / "package-lock.json").read_text(encoding="utf-8")

    assert "npm ci --ignore-scripts" in workflow
    assert "npm install --global" not in workflow
    assert ".github/renovate-validation/node_modules/.bin/renovate-config-validator --strict" in workflow
    assert '"renovate": "44.32.2"' in package
    assert '"lockfileVersion": 3' in lockfile
    assert '"node_modules/renovate"' in lockfile


def test_scorecard_can_read_pull_request_check_runs() -> None:
    workflow = (WORKFLOWS / "scorecard.yml").read_text(encoding="utf-8")
    scorecard_job = workflow.split("  scorecard:", 1)[1]
    permissions = scorecard_job.split("    steps:", 1)[0]

    assert "contents: read" in permissions
    assert "checks: read" in permissions
    assert "security-events: write" in permissions
    assert "checks: write" not in permissions


def test_security_workflow_has_read_only_default_permissions() -> None:
    workflow = (WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8")
    header = workflow.split("\njobs:", 1)[0]

    assert "\npermissions:\n  contents: read\n" in header


def test_semgrep_blocks_only_repository_specific_rules() -> None:
    workflow = (WORKFLOWS / "security-scan.yml").read_text(encoding="utf-8")
    semgrep_block = workflow[workflow.index("- name: Run Semgrep") : workflow.index("- name: Upload SARIF results")]

    assert "--config .semgrep.yml" in semgrep_block
    assert "p/default" not in semgrep_block


def test_auto_assign_is_idempotent_on_pull_request_events() -> None:
    workflow = (WORKFLOWS / "auto-assign.yml").read_text(encoding="utf-8")

    assert 'gh api "/repos/$REPO/issues/$NUMBER" --jq' in workflow
    assert "grep -Fxq oaslananka" in workflow
    assert "Already assigned to oaslananka" in workflow


def test_workflow_uvx_calls_never_build_packages() -> None:
    unsafe = [
        f"{path.name}:{line_number}"
        for path in sorted(WORKFLOWS.glob("*.yml"))
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "uvx " in line and "uvx --no-build " not in line
    ]
    assert unsafe == []


def test_docker_smoke_runs_compose_runtime_and_uploads_evidence() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")
    block = workflow[workflow.index("  docker-image-smoke:") : workflow.index("\n  kicad-oracle:")]

    assert "python3 scripts/ci_compose_smoke.py" in block
    assert "docker run --rm zaptrace:ci --help" not in block
    assert "if: always() && needs.changes.outputs.heavy_ci == 'true'" in block
    assert "artifacts/compose-smoke/" in block


def test_quality_workflow_enforces_and_uploads_critical_runtime_coverage() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")
    gate_block = workflow[
        workflow.index("- name: Combine coverage and enforce critical floors") : workflow.index(
            "- name: Upload critical runtime coverage evidence"
        )
    ]
    upload_block = workflow[workflow.index("- name: Upload critical runtime coverage evidence") :]

    assert ".venv/bin/coverage json -o coverage.json" in gate_block
    assert "scripts/ci_critical_runtime_coverage.py" in gate_block
    assert "--policy config/critical-runtime-coverage.json" in gate_block
    assert "--mode snapshot" in gate_block
    assert "--output critical-runtime-coverage.json" in gate_block
    assert "--markdown critical-runtime-coverage.md" in gate_block
    assert 'cat critical-runtime-coverage.md >> "$GITHUB_STEP_SUMMARY"' in gate_block
    assert "name: critical-runtime-coverage" in upload_block
    assert "critical-runtime-coverage.json" in upload_block
    assert "critical-runtime-coverage.md" in upload_block
    assert "if-no-files-found: error" in upload_block


def test_quality_workflow_enforces_bounded_version_contexts() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")
    lint_section = workflow[workflow.index("  lint:") : workflow.index("\n  mcp-compatibility:")]
    assert "fetch-depth: 0" in lint_section
    gate_start = workflow.index("- name: Verify version consistency")
    upload_start = workflow.index("- name: Upload version consistency evidence")
    gate_block = workflow[gate_start:upload_start]
    upload_block = workflow[upload_start:]

    assert 'VERSION_CONTEXT="development"' in gate_block
    assert 'if [[ "$GITHUB_EVENT_NAME" == "pull_request" && "$GITHUB_HEAD_REF" == release/v* ]]; then' in gate_block
    assert 'VERSION_CONTEXT="release-preparation"' in gate_block
    assert 'VERSION_SOURCE_REF="refs/heads/$GITHUB_HEAD_REF"' in gate_block
    assert 'elif [[ "$GITHUB_EVENT_NAME" == "push" && "$GITHUB_REF" == "refs/heads/main" ]]; then' in gate_block
    assert 'PACKAGE_VERSION="$(.venv/bin/python -c' in gate_block
    assert 'if [[ "$PACKAGE_VERSION" != *.dev* ]]; then' in gate_block
    assert "scripts/ci_version_consistency.py" in gate_block
    assert '--context "$VERSION_CONTEXT"' in gate_block
    assert '--source-ref "$VERSION_SOURCE_REF"' in gate_block
    assert '--source-commit "$(git rev-parse HEAD)"' in gate_block
    assert "--output version-consistency.json" in gate_block
    assert "--markdown version-consistency.md" in gate_block
    assert "--strict" in gate_block
    assert "name: version-consistency" in upload_block
    assert "version-consistency.json" in upload_block
    assert "version-consistency.md" in upload_block
    assert "if-no-files-found: error" in upload_block
