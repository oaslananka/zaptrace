"""Static contracts for CI observability and GitHub Actions security."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
QUALITY = WORKFLOWS / "quality.yml"
COVERAGE = WORKFLOWS / "quality-coverage.yml"
NATIVE = WORKFLOWS / "quality-native.yml"
LINT = WORKFLOWS / "quality-lint.yml"
PRE_COMMIT_WORKFLOW = WORKFLOWS / "pre-commit.yml"


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


def test_quality_matrix_generates_and_retains_junit_results() -> None:
    workflow = QUALITY.read_text(encoding="utf-8")

    assert "JUNIT_PATH: junit-lane-${{ matrix.artifact }}.xml" in workflow
    assert '--junitxml "$JUNIT_PATH"' in workflow
    assert "junit-${lane}-${{ matrix.python-version }}.xml" in workflow
    assert workflow.count("-o junit_family=legacy") >= 2
    assert "${{ env.JUNIT_PATH }}" in workflow
    assert "test-lane-report-${{ matrix.artifact }}.json" in workflow
    assert "test-lane-results-${{ matrix.artifact }}" in workflow
    assert "CODECOV_TOKEN" not in workflow
    assert "codecov/codecov-action@" not in workflow
    assert not (ROOT / "codecov.yml").exists()


def test_coverage_is_repository_owned_and_retained_as_artifacts() -> None:
    workflow = COVERAGE.read_text(encoding="utf-8")

    assert ".venv/bin/coverage combine test-lane-artifacts" in workflow
    assert ".venv/bin/coverage report" in workflow
    assert ".venv/bin/coverage xml -o coverage.xml" in workflow
    assert ".venv/bin/coverage json -o coverage.json" in workflow
    assert "name: critical-runtime-coverage" in workflow
    assert "coverage.xml" in workflow
    assert "coverage.json" in workflow
    assert "codecov/codecov-action@" not in workflow


def test_quality_coverage_reusable_boundary_preserves_gate_and_skip_contracts() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    coverage = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    caller = quality["jobs"]["coverage"]
    assert caller["needs"] == ["changes", "test"]
    assert caller["name"] == "Combined Python coverage"
    assert caller["uses"] == "./.github/workflows/quality-coverage.yml"
    assert caller["with"] == {"test_mode": "${{ needs.changes.outputs.test_mode }}"}
    assert "secrets" not in caller
    assert "if" not in caller  # Docs-only reports explicit success, not a missing check.

    assert coverage["permissions"] == {"contents": "read"}
    assert coverage[True]["workflow_call"]["inputs"]["test_mode"] == {
        "description": "Docs-only mode from the caller's change classifier",
        "type": "string",
        "required": True,
    }
    assert coverage["jobs"]["aggregate"]["name"] == "Aggregate and enforce"
    assert coverage["jobs"]["aggregate"]["env"]["UV_VERSION"] == quality["env"]["UV_VERSION"]
    assert coverage["jobs"]["aggregate"]["env"]["PYTHONPATH"] == quality["env"]["PYTHONPATH"]
    steps = coverage["jobs"]["aggregate"]["steps"]
    assert steps[0]["if"] == "inputs.test_mode == 'docs'"
    assert "coverage aggregation skipped" in steps[0]["run"]
    for step in steps[1:]:
        assert step["if"] == (
            "inputs.test_mode != 'docs' && always()"
            if step.get("name") == "Upload critical runtime coverage evidence"
            else "inputs.test_mode != 'docs'"
        ), step.get("name", step.get("uses"))
    assert (
        next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))["with"][
            "persist-credentials"
        ]
        is False
    )
    downloaded = next(step for step in steps if step.get("name") == "Download lane coverage data")
    assert downloaded["with"] == {
        "pattern": "test-lane-results-*",
        "path": "test-lane-artifacts",
        "merge-multiple": True,
    }
    assert "coverage" in quality["jobs"]["release-gate-summary"]["needs"]
    assert (
        '--gate "coverage=${{ needs.coverage.result }}"'
        in next(
            step
            for step in quality["jobs"]["release-gate-summary"]["steps"]
            if step.get("name") == "Generate snapshot gate summary"
        )["run"]
    )


def test_quality_native_reusable_boundary_preserves_heavy_gate_evidence_and_permissions() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    native = yaml.safe_load(NATIVE.read_text(encoding="utf-8"))
    caller = quality["jobs"]["rust"]
    assert caller == {
        "name": "Build Rust extension",
        "needs": "changes",
        "uses": "./.github/workflows/quality-native.yml",
        "with": {"heavy_ci": "${{ needs.changes.outputs.heavy_ci }}"},
    }
    assert native["permissions"] == {"contents": "read"}
    assert native[True]["workflow_call"]["inputs"]["heavy_ci"] == {
        "description": "Heavy-CI eligibility from Quality change classification",
        "type": "string",
        "required": True,
    }
    job = native["jobs"]["verify"]
    assert job["env"] == {key: quality["env"][key] for key in ("PYTHON_VERSION", "UV_VERSION", "PYTHONPATH")}
    steps = job["steps"]
    assert steps[0]["if"] == "inputs.heavy_ci != 'true'"
    assert "skipping Rust extension build" in steps[0]["run"]
    for step in steps[1:]:
        assert step["if"] == "inputs.heavy_ci == 'true'", step.get("name", step.get("uses"))
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    bootstrap = next(step for step in steps if step.get("uses") == "./.github/actions/setup-locked-python")
    assert bootstrap["with"] == {"uv-version": "${{ env.UV_VERSION }}", "python-version": "${{ env.PYTHON_VERSION }}"}
    evidence = next(step for step in steps if step.get("name") == "Upload native boundary evidence")
    assert evidence["with"]["name"] == "native-boundary-evidence"
    assert evidence["with"]["if-no-files-found"] == "error"
    assert "always()" not in evidence["if"]
    assert "rust" in quality["jobs"]["release-gate-summary"]["needs"]
    summary = next(
        step
        for step in quality["jobs"]["release-gate-summary"]["steps"]
        if step.get("name") == "Generate snapshot gate summary"
    )
    assert '--gate "rust=${{ needs.rust.result }}"' in summary["run"]


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
    package = json.loads((ROOT / ".github" / "renovate-validation" / "package.json").read_text(encoding="utf-8"))
    lockfile = json.loads((ROOT / ".github" / "renovate-validation" / "package-lock.json").read_text(encoding="utf-8"))

    assert "npm ci --ignore-scripts" in workflow
    assert "npm install --global" not in workflow
    assert ".github/renovate-validation/node_modules/.bin/renovate-config-validator --strict" in workflow
    assert package["devDependencies"]["renovate"]
    assert lockfile["lockfileVersion"] == 3
    resolved = lockfile["packages"]["node_modules/renovate"]["version"]
    assert resolved.startswith("44.")
    assert resolved == package["devDependencies"]["renovate"].lstrip("^~")

    # The validation-only CLI must not retain the unpatched sprintf-js chain
    # pulled in by global-agent 3 -> roarr 2. Hosted Renovate is independent.
    packages = lockfile["packages"]
    assert package["overrides"]["global-agent"].startswith("4.")
    assert packages["node_modules/global-agent"]["version"].startswith("4.")
    assert not any(path.endswith("node_modules/roarr") for path in packages)
    assert not any(path.endswith("node_modules/sprintf-js") for path in packages)

    # Renovate carries handlebars; older versions have critical JS injection
    # advisories, fixed upstream in 4.7.10.
    version = packages["node_modules/handlebars"]["version"]
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version), "require a stable patched Handlebars release"
    handlebars_version = tuple(int(part) for part in version.split("."))
    assert handlebars_version >= (4, 7, 10)


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


def test_compose_smoke_pins_mirrored_buildkit_without_relaxing_runtime_assurance() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    job = quality["jobs"]["docker-image-smoke"]
    assert job["name"] == "Docker image smoke"
    assert "docker-image-smoke" in quality["jobs"]["release-gate-summary"]["needs"]
    steps = job["steps"]
    mirror_step = next(step for step in steps if step.get("name") == "Configure digest-pinned mirrored BuildKit")
    assert mirror_step["if"] == "needs.changes.outputs.heavy_ci == 'true'"
    assert mirror_step["uses"] == "docker/setup-buildx-action@f87e5991a6d7451dcb8d9637bfbc97413f497069"
    assert mirror_step["with"]["name"] == "zaptrace-ci-mirror"
    assert (
        "image=mirror.gcr.io/moby/buildkit@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
        in mirror_step["with"]["driver-opts"]
    )
    assert 'mirrors = ["mirror.gcr.io"]' in mirror_step["with"]["buildkitd-config-inline"]
    smoke = next(step for step in steps if step.get("name") == "Exercise Compose REST and MCP runtimes")
    assert smoke["env"] == {"BUILDX_BUILDER": "zaptrace-ci-mirror"}
    assert smoke["run"] == "python3 scripts/ci_compose_smoke.py"
    upload = next(step for step in steps if step.get("name") == "Upload Compose smoke evidence")
    assert upload["if"] == "always() && needs.changes.outputs.heavy_ci == 'true'"
    assert upload["with"]["name"] == "compose-runtime-smoke"
    assert upload["with"]["if-no-files-found"] == "error"


def test_quality_workflow_enforces_and_uploads_critical_runtime_coverage() -> None:
    workflow = COVERAGE.read_text(encoding="utf-8")
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


def test_quality_lint_reusable_boundary_preserves_required_gates() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    lint = yaml.safe_load(LINT.read_text(encoding="utf-8"))
    caller = quality["jobs"]["lint"]
    assert caller == {
        "name": "Lint & Typecheck",
        "needs": "changes",
        "uses": "./.github/workflows/quality-lint.yml",
        "with": {"full_ci": "${{ needs.changes.outputs.full_ci }}"},
    }
    assert lint["permissions"] == {"contents": "read"}
    assert lint[True]["workflow_call"]["inputs"]["full_ci"] == {
        "description": "Full-CI eligibility from Quality change classification",
        "type": "string",
        "required": True,
    }
    job = lint["jobs"]["validate"]
    assert job["name"] == "Lint & Typecheck"
    assert job["env"] == {key: quality["env"][key] for key in ("PYTHON_VERSION", "UV_VERSION", "PYTHONPATH")}
    steps = job["steps"]
    assert steps[0]["if"] == "inputs.full_ci != 'true'"
    assert "Docs-only PR" in steps[0]["run"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["if"] == "inputs.full_ci == 'true'"
    assert checkout["with"] == {"persist-credentials": False, "fetch-depth": 0}
    bootstrap = next(step for step in steps if step.get("uses") == "./.github/actions/setup-locked-python")
    assert bootstrap["if"] == "inputs.full_ci == 'true'"
    assert bootstrap["with"] == {
        "uv-version": "${{ env.UV_VERSION }}",
        "python-version": "${{ env.PYTHON_VERSION }}",
    }
    for artifact_name in ("version-consistency", "component-evidence-gate", "architecture-compiler-evidence"):
        upload = next(step for step in steps if step.get("with", {}).get("name") == artifact_name)
        assert upload["if"] == "always() && inputs.full_ci == 'true'"
        assert upload["with"]["if-no-files-found"] == "error"
    summary = quality["jobs"]["release-gate-summary"]
    assert "lint" in summary["needs"]
    gate_step = next(step for step in summary["steps"] if step.get("name") == "Generate snapshot gate summary")
    assert '--gate "lint=${{ needs.lint.result }}"' in gate_step["run"]


def test_quality_workflow_enforces_bounded_version_contexts() -> None:
    workflow = LINT.read_text(encoding="utf-8")
    lint_section = workflow[workflow.index("  validate:") :]
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


def test_shared_locked_python_bootstrap_preserves_quality_job_contracts() -> None:
    action = yaml.safe_load((ROOT / ".github" / "actions" / "setup-locked-python" / "action.yml").read_text())
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    steps = action["runs"]["steps"]
    assert action["runs"]["using"] == "composite"
    assert steps[0]["uses"] == "astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39"
    assert steps[1]["run"] == 'uv python install "$PYTHON_VERSION"'
    assert steps[1]["env"]["PYTHON_VERSION"] == "${{ inputs.python-version }}"
    sync_script = steps[2]["run"]
    assert steps[2]["env"]["PYTHON_VERSION"] == "${{ inputs.python-version }}"
    assert steps[2]["env"]["SYNC_EXPLICIT_PYTHON"] == "${{ inputs.sync-explicit-python }}"
    assert action["inputs"]["sync-explicit-python"]["default"] == "false"
    assert "uv lock --check" in sync_script
    assert 'if [[ "$SYNC_EXPLICIT_PYTHON" == "true" ]]; then' in sync_script
    assert "sync_args=(--locked --all-extras --all-groups --no-install-project --no-build)" in sync_script
    assert 'sync_args+=(--python "$PYTHON_VERSION")' in sync_script
    assert 'uv sync "${sync_args[@]}"' in sync_script
    assert sync_script.count('uv sync "${sync_args[@]}"') == 1
    assert all("permissions" not in step and "secrets" not in step for step in steps)

    heavy_jobs = {"benchmark-001", "generated-board-release-gate", "kicad-oracle", "build"}
    full_jobs = {"mcp-compatibility"}
    unconditional_jobs = {"docs-stale", "release-gate-summary", "test-lane-policy"}
    for job_id in heavy_jobs | full_jobs | unconditional_jobs:
        job = quality["jobs"][job_id]
        matches = [step for step in job["steps"] if step.get("uses") == "./.github/actions/setup-locked-python"]
        assert len(matches) == 1, job_id
        assert matches[0]["with"] == {
            "uv-version": "${{ env.UV_VERSION }}",
            "python-version": "${{ env.PYTHON_VERSION }}",
        }
        if job_id in heavy_jobs:
            assert matches[0]["if"] == "needs.changes.outputs.heavy_ci == 'true'"
        elif job_id in full_jobs:
            assert matches[0]["if"] == "needs.changes.outputs.full_ci == 'true'"
        else:
            assert "if" not in matches[0]


def test_shared_locked_python_policy_jobs_preserve_evidence_and_skip_contracts() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    mcp_steps = quality["jobs"]["mcp-compatibility"]["steps"]
    lane_steps = quality["jobs"]["test-lane-policy"]["steps"]

    mcp_bootstrap = next(step for step in mcp_steps if step.get("uses") == "./.github/actions/setup-locked-python")
    assert mcp_bootstrap["if"] == "needs.changes.outputs.full_ci == 'true'"
    assert any(step.get("name") == "Skip MCP compatibility for docs-only PR" for step in mcp_steps)
    mcp_upload = next(step for step in mcp_steps if step.get("name") == "Upload MCP dependency evidence")
    assert mcp_upload["with"]["name"] == "mcp-dependency-evidence"
    assert mcp_upload["if"] == "needs.changes.outputs.full_ci == 'true' && always()"

    lane_bootstrap = next(step for step in lane_steps if step.get("uses") == "./.github/actions/setup-locked-python")
    assert "if" not in lane_bootstrap
    lane_upload = next(step for step in lane_steps if step.get("name") == "Upload test lane inventory")
    assert lane_upload["with"]["name"] == "test-lane-inventory"
    assert any(step.get("name") == "Validate lane policy and shard inventory" for step in lane_steps)


def test_shared_locked_python_matrix_keeps_version_and_skip_semantics() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    cases = {
        "test": "3.12",
        "test-compatibility": "${{ matrix.python-version }}",
    }
    for job_id, version in cases.items():
        job = quality["jobs"][job_id]
        matches = [step for step in job["steps"] if step.get("uses") == "./.github/actions/setup-locked-python"]
        assert len(matches) == 1
        step = matches[0]
        assert step["if"] == "needs.changes.outputs.test_mode != 'docs'"
        assert step["with"] == {
            "uv-version": "${{ env.UV_VERSION }}",
            "python-version": version,
            "sync-explicit-python": "true",
        }
        assert any("Upload" in step.get("name", "") for step in job["steps"])
    assert quality["jobs"]["test"]["name"] == "Test lane ${{ matrix.artifact }}"
    assert quality["jobs"]["test-compatibility"]["name"] == "Fast compatibility (Python ${{ matrix.python-version }})"
