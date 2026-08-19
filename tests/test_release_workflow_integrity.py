from __future__ import annotations

import re
import subprocess
from pathlib import Path


def _workflow_job(workflow: str, job_name: str) -> str:
    start = workflow.index(f"  {job_name}:")
    match = re.search(r"^  [A-Za-z0-9_-]+:\s*$", workflow[start + 1 :], flags=re.MULTILINE)
    if match is None:
        return workflow[start:]
    return workflow[start : start + 1 + match.start()]


def test_release_workflow_generates_and_verifies_checksums() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "Generate checksum manifest" in workflow
    assert "scripts/generate_checksum_manifest.py release-artifacts" in workflow
    assert "sha256sum --check SHA256SUMS" in workflow


def test_release_job_checks_out_repo_before_running_release_scripts() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    release_section = workflow.split("github-release:", 1)[1]
    checkout_pos = release_section.index("actions/checkout")
    checksum_pos = release_section.index("scripts/generate_checksum_manifest.py")
    assert checkout_pos < checksum_pos


def test_release_workflow_enforces_and_uploads_critical_runtime_coverage() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    gate_block = workflow[
        workflow.index("- name: Enforce critical runtime coverage") : workflow.index(
            "- name: Upload critical runtime coverage evidence"
        )
    ]
    upload_block = workflow[workflow.index("- name: Upload critical runtime coverage evidence") :]

    assert ".venv/bin/coverage json -o coverage.json" in workflow
    assert "lane_specs=(" in workflow
    for spec in (
        "unit:1:3",
        "unit:2:3",
        "unit:3:3",
        "integration",
        "benchmark:1:2",
        "benchmark:2:2",
        "hardware:1:2",
        "hardware:2:2",
        "external_tool",
        "native",
    ):
        assert f'"{spec}"' in workflow
    assert 'shard_args+=(--lane-shard-index "$shard_index" --lane-shard-count "$shard_count")' in workflow
    assert '--lane "$lane"' in workflow
    assert "scripts/ci_critical_runtime_coverage.py" in gate_block
    assert "--coverage coverage.json" in gate_block
    assert "--policy config/critical-runtime-coverage.json" in gate_block
    assert "--mode release" in gate_block
    assert "--strict" in gate_block
    assert "name: critical-runtime-coverage-release" in upload_block
    assert "critical-runtime-coverage.json" in upload_block
    assert "critical-runtime-coverage.md" in upload_block
    assert "coverage.json" in upload_block


def test_release_workflow_exposes_repository_root_on_pythonpath() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    env_section = workflow[workflow.index("env:") : workflow.index("jobs:")]

    assert 'PYTHONPATH: "."' in env_section


def test_release_quality_uses_the_locked_synced_environment_directly() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]

    assert "uv run" not in quality_section
    for executable in ("ruff", "pyright", "python", "pytest", "coverage"):
        assert f".venv/bin/{executable}" in quality_section


def test_release_workflow_verifies_exact_annotated_tag_and_uploads_version_evidence() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]

    assert "fetch-depth: 0" in quality_section
    assert "Verify tag matches package version" not in quality_section
    assert "name: Verify release version and tag identity" in quality_section
    assert "scripts/ci_version_consistency.py" in quality_section
    assert "--context release" in quality_section
    assert '--source-ref "$GITHUB_REF"' in quality_section
    assert '--source-commit "$(git rev-parse HEAD)"' in quality_section
    assert "--output version-consistency-release.json" in quality_section
    assert "--markdown version-consistency-release.md" in quality_section
    assert "name: version-consistency-release" in quality_section
    assert "if-no-files-found: error" in quality_section
    assert "name: Download release version consistency evidence" in workflow
    assert "name: version-consistency-release" in workflow[workflow.index("  github-release:") :]


def test_release_wheel_matrix_tests_each_installed_wheel() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    wheel_job = workflow[workflow.index("  rust-wheels:") : workflow.index("\n  github-release:")]

    assert "Install built Rust wheel" in wheel_job
    assert "Run mandatory native boundary verification" in wheel_job
    assert "native-boundary-${{ matrix.target }}" in wheel_job
    assert 'ZAPTRACE_REQUIRE_NATIVE: "1"' in wheel_job
    assert "UV_PROJECT_ENVIRONMENT=" in wheel_job
    assert "uv sync --locked" in wheel_job
    assert "--no-install-project" in wheel_job
    assert "--no-deps" in wheel_job
    assert "--require-hashes" in wheel_job
    assert "sha256sum" in wheel_job
    assert "native-wheel.requirements.txt" in wheel_job


def test_release_native_wheel_smoke_allows_locked_dependency_source_builds() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    wheel_job = workflow[workflow.index("  rust-wheels:") : workflow.index("\n  github-release:")]
    install_block = wheel_job[
        wheel_job.index("- name: Install built Rust wheel") : wheel_job.index(
            "- name: Run mandatory native boundary verification"
        )
    ]

    assert "uv sync --locked --all-extras --all-groups --no-install-project" in install_block
    assert "--no-build" not in install_block


def test_release_workflow_binds_cargo_audit_to_gate_and_assets() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]
    release_section = workflow[workflow.index("  github-release:") :]

    assert 'CARGO_AUDIT_VERSION: "0.22.2"' in workflow
    assert "Install pinned cargo-audit" in quality_section
    assert "cargo audit --file zaptrace_core/Cargo.lock --json" in quality_section
    assert "scripts/ci_cargo_audit.py" in quality_section
    assert "cargo-audit-release-evidence.json" in quality_section
    assert '--gate "cargo-audit=success"' in quality_section
    assert "--source-input cargo-audit-release-evidence.json" in quality_section
    assert '--tool-version "cargo-audit=$(cargo-audit --version)"' in quality_section
    assert "name: cargo-audit-release" in quality_section
    assert "Download release Cargo advisory evidence" in release_section
    assert "name: cargo-audit-release" in release_section


def test_release_native_evidence_records_matrix_target_and_all_target_clippy() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]
    wheel_job = workflow[workflow.index("  rust-wheels:") : workflow.index("\n  github-release:")]

    assert "cargo clippy --manifest-path zaptrace_core/Cargo.toml --all-targets -- -D warnings" in quality_section
    assert '--target "${{ matrix.target }}"' in wheel_job


def test_release_dependency_sync_defers_project_install_until_native_build() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]
    install_block = quality_section[
        quality_section.index("- name: Install dependencies") : quality_section.index(
            "- name: Verify release version and tag identity"
        )
    ]

    assert "uv lock --check" in install_block
    assert "uv sync --locked --all-extras --all-groups --no-install-project --no-build" in install_block


def test_release_builds_native_extension_only_for_native_lane() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]

    assert "- name: Build native extension for release tests" not in quality_section
    loop_section = quality_section[
        quality_section.index("for spec in") : quality_section.index("done\n          .venv/bin/coverage report")
    ]
    build_guard = 'if [[ "$lane" == "native" ]]; then'
    builder = ".venv/bin/maturin develop --release --manifest-path zaptrace_core/Cargo.toml"
    pytest_call = ".venv/bin/pytest -p tests.lane_policy"

    assert build_guard in loop_section
    assert builder in loop_section
    assert loop_section.index(build_guard) < loop_section.index(builder) < loop_section.index(pytest_call)


def test_release_installs_external_tools_only_for_external_tool_lane() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]

    assert "- name: Install external test prerequisites" not in quality_section
    loop_section = quality_section[
        quality_section.index("for spec in") : quality_section.index("done\n          .venv/bin/coverage report")
    ]
    install_guard = 'if [[ "$lane" == "external_tool" ]]; then'
    installer = "bash scripts/ci_install_kicad.sh kicad ngspice"
    pytest_call = ".venv/bin/pytest -p tests.lane_policy"

    assert install_guard in loop_section
    assert installer in loop_section
    assert loop_section.index(install_guard) < loop_section.index(installer) < loop_section.index(pytest_call)


def test_release_shards_defer_global_coverage_threshold_until_aggregation() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    quality_section = workflow[workflow.index("  quality:") : workflow.index("\n  python-distributions:")]

    assert "--cov-fail-under=0" in quality_section
    assert ".venv/bin/coverage report" in quality_section


def test_release_workflow_uses_checkout_with_annotated_tag_fix() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    fixed_checkout = "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd  # v6.0.2"

    assert workflow.count(fixed_checkout) == 8
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683" not in workflow


def test_release_generated_evidence_does_not_dirty_source_tree() -> None:
    generated_paths = (
        "version-consistency-release.json",
        "version-consistency-release.md",
        "test-lane-inventory.json",
        "test-lane-release-unit-1.json",
        "junit-release-unit-1.xml",
        "coverage.json",
        "critical-runtime-coverage.json",
        "critical-runtime-coverage.md",
        "cargo-audit-release.json",
        "cargo-audit-release-evidence.json",
        "cargo-audit-release-evidence.md",
        "tagged-release-evidence.json",
    )

    visible = []
    for path in generated_paths:
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--no-index", path],
            check=False,
            cwd=Path.cwd(),
        )
        if result.returncode != 0:
            visible.append(path)

    assert visible == [], f"release-generated evidence is visible to git status: {visible}"


def test_release_workflow_supports_manual_testpypi_staging_without_running_release_jobs() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "staging-build:" in workflow
    assert "staging-testpypi-publish:" in workflow
    assert "staging-testpypi-verify:" in workflow
    staging_publish = workflow[
        workflow.index("  staging-testpypi-publish:") : workflow.index("\n  staging-testpypi-verify:")
    ]
    assert "github.event_name == 'workflow_dispatch'" in staging_publish
    assert "github.ref == 'refs/heads/main'" in staging_publish
    assert "environment: testpypi" in staging_publish
    assert "id-token: write" in staging_publish
    assert "repository-url: https://test.pypi.org/legacy/" in staging_publish
    assert "skip-existing: true" in staging_publish

    for job_name in ("container-security", "quality", "python-distributions", "rust-wheels", "github-release"):
        section = _workflow_job(workflow, job_name)
        assert "github.event_name == 'push'" in section, f"{job_name} must not run during manual staging"


def test_tagged_release_stages_exact_artifacts_before_pypi_and_github_release() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    for job_name, environment in (("testpypi-publish", "testpypi"), ("pypi-publish", "pypi")):
        marker = f"  {job_name}:"
        assert marker in workflow
        section = _workflow_job(workflow, job_name)
        assert f"environment: {environment}" in section
        assert "id-token: write" in section
        assert "pypa/gh-action-pypi-publish@" in section
        assert "username:" not in section
        assert "password:" not in section

    assert "  testpypi-verify:" in workflow
    assert "  pypi-verify:" in workflow
    assert "scripts/ci_registry_distribution.py" in workflow
    release_section = workflow[workflow.index("  github-release:") :]
    assert "pypi-verify" in release_section.split("\n    runs-on:", 1)[0]


def test_trusted_publish_jobs_use_pinned_pypa_action_and_no_registry_tokens() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    trusted_action = "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33"

    assert workflow.count(trusted_action) >= 3
    assert "PYPI_TOKEN" not in workflow
    assert "TEST_PYPI" not in workflow


def test_release_workflow_uses_job_scoped_least_privilege_permissions() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    header = workflow.split("\njobs:", 1)[0]

    assert "\npermissions:" not in header
    for job_name in (
        "staging-build",
        "staging-testpypi-publish",
        "staging-testpypi-verify",
        "container-security",
        "quality",
        "python-distributions",
        "rust-wheels",
        "testpypi-publish",
        "testpypi-verify",
        "pypi-publish",
        "pypi-verify",
        "github-release",
    ):
        section = _workflow_job(workflow, job_name)
        assert "permissions:" in section, f"{job_name} must declare job-scoped permissions"


def test_registry_publish_jobs_stage_only_distribution_files() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    for job_name in ("testpypi-publish", "pypi-publish"):
        section = _workflow_job(workflow, job_name)
        assert "path: registry-source" in section
        assert "path: registry-wheels" in section
        assert "- name: Stage registry distributions" in section
        assert "mkdir -p registry-publish" in section
        assert "cp registry-source/*.tar.gz registry-publish/" in section
        assert "cp registry-wheels/*.whl registry-publish/" in section
        assert "packages-dir: registry-publish/" in section
