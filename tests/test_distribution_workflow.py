from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github" / "workflows" / "quality.yml"
DISTRIBUTION = ROOT / ".github" / "workflows" / "quality-distribution.yml"
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
CHANGE_POLICY = ROOT / "scripts" / "ci_change_policy.py"


def _load_change_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_change_policy_under_test", CHANGE_POLICY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _job(workflow: Path, start: str, end: str) -> str:
    text = workflow.read_text(encoding="utf-8")
    return text[text.index(start) : text.index(end, text.index(start) + len(start))]


def test_distribution_policy_and_smoke_changes_select_heavy_ci() -> None:
    module = _load_change_policy()

    for changed_path in (
        "config/distribution-support.json",
        "scripts/ci_distribution_support.py",
        "scripts/ci_distribution_smoke.py",
        "tests/test_ci_distribution_support.py",
        "tests/test_ci_distribution_support_failures.py",
        "tests/test_ci_distribution_smoke.py",
        "tests/test_ci_distribution_smoke_failures.py",
        "tests/test_distribution_workflow.py",
    ):
        policy = module.classify_paths([changed_path], event_name="pull_request")
        assert policy.heavy_ci is True, changed_path
        assert policy.full_ci is True, changed_path


def test_quality_workflow_clean_installs_and_smokes_sdist() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    distribution = yaml.safe_load(DISTRIBUTION.read_text(encoding="utf-8"))
    caller = quality["jobs"]["distribution-clean-install"]
    assert caller == {
        "name": "Distribution clean-install",
        "needs": "changes",
        "uses": "./.github/workflows/quality-distribution.yml",
        "with": {"heavy_ci": "${{ needs.changes.outputs.heavy_ci }}"},
    }
    assert distribution["permissions"] == {"contents": "read"}
    assert distribution[True]["workflow_call"]["inputs"]["heavy_ci"] == {
        "description": "Heavy-CI eligibility from Quality change classification",
        "type": "string",
        "required": True,
    }
    job = distribution["jobs"]["sdist"]
    assert job["timeout-minutes"] == 20
    assert job["name"] == "Build and verify clean source distribution"
    assert job["env"] == {key: quality["env"][key] for key in ("PYTHON_VERSION", "UV_VERSION", "PYTHONPATH")}
    steps = job["steps"]
    assert steps[0]["if"] == "inputs.heavy_ci != 'true'"
    assert "skipping distribution clean-install" in steps[0]["run"]
    for step in steps[1:]:
        assert step["if"] == (
            "inputs.heavy_ci == 'true' && always()"
            if step.get("name") == "Upload distribution clean-install evidence"
            else "inputs.heavy_ci == 'true'"
        ), step.get("name", step.get("uses"))
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    evidence = next(step for step in steps if step.get("name") == "Upload distribution clean-install evidence")
    assert evidence["with"]["name"] == "distribution-smoke-sdist-linux-x86_64-cp313"
    assert evidence["with"]["if-no-files-found"] == "error"

    body = DISTRIBUTION.read_text(encoding="utf-8")
    assert "uv python install ${{ env.PYTHON_VERSION }}" in body
    assert "uv build --sdist" in body
    assert 'UV_PROJECT_ENVIRONMENT="$RUNNER_TEMP/zaptrace-sdist-smoke"' in body
    assert "uv sync --locked --all-extras --all-groups --no-install-project --no-build" in body
    assert "uv pip install" in body
    assert '--python "$RUNNER_TEMP/zaptrace-sdist-smoke/bin/python"' in body
    assert "--no-deps" in body
    assert 'sdist="$(realpath dist/*.tar.gz)"' in body
    assert 'cd "$RUNNER_TEMP"' in body
    assert '"$RUNNER_TEMP/zaptrace-sdist-smoke/bin/python"' in body
    assert '"$GITHUB_WORKSPACE/scripts/ci_distribution_smoke.py"' in body
    assert '--artifact-root "$GITHUB_WORKSPACE/dist"' in body
    assert "--artifact-type source-distribution" in body
    assert "--target sdist-linux-x86_64-cp313" in body
    assert '--policy "$GITHUB_WORKSPACE/config/distribution-support.json"' in body
    assert '--source-root "$GITHUB_WORKSPACE"' in body
    assert '--source-commit "$GITHUB_SHA"' in body
    assert '--lockfile "$GITHUB_WORKSPACE/uv.lock"' in body
    assert "--expected-native absent" in body
    assert '--output "$GITHUB_WORKSPACE/distribution-smoke-sdist-linux-x86_64-cp313.json"' in body
    assert '--markdown "$GITHUB_WORKSPACE/distribution-smoke-sdist-linux-x86_64-cp313.md"' in body
    assert "--strict" in body
    assert "name: distribution-smoke-sdist-linux-x86_64-cp313" in body
    assert "if-no-files-found: error" in body


def test_release_python_distribution_is_sdist_only_and_clean_installed() -> None:
    job = _job(RELEASE, "  python-distributions:", "\n  rust-wheels:")

    assert "uv build --sdist" in job
    assert "uv build\n" not in job
    assert 'UV_PROJECT_ENVIRONMENT="$RUNNER_TEMP/zaptrace-sdist-smoke"' in job
    assert "uv sync --locked --all-extras --all-groups --no-install-project --no-build" in job
    assert 'sdist="$(realpath dist/*.tar.gz)"' in job
    assert "--require-hashes" in job
    assert "--no-deps" in job
    assert 'cd "$RUNNER_TEMP"' in job
    assert '"$GITHUB_WORKSPACE/scripts/ci_distribution_smoke.py"' in job
    assert '--artifact-root "$GITHUB_WORKSPACE/dist"' in job
    assert "--artifact-type source-distribution" in job
    assert "--target sdist-linux-x86_64-cp313" in job
    assert "--expected-native absent" in job
    assert "name: distribution-smoke-sdist-linux-x86_64-cp313" in job
    assert "if-no-files-found: error" in job


def test_release_native_wheel_matrix_runs_distribution_smoke_before_upload() -> None:
    job = _job(RELEASE, "  rust-wheels:", "\n  github-release:")

    for support_target in (
        "native-linux-x86_64-cp313",
        "native-macos-x86_64-cp313",
        "native-macos-arm64-cp313",
    ):
        assert f"support_target: {support_target}" in job
    smoke_pos = job.index("Run clean-install distribution smoke")
    wheel_upload_pos = job.index("Upload wheel")
    assert smoke_pos < wheel_upload_pos
    assert "--artifact-type native-wheel" in job
    assert '--target "${{ matrix.support_target }}"' in job
    assert "--expected-native required" in job
    assert "distribution-smoke-${{ matrix.support_target }}.json" in job
    assert "distribution-smoke-${{ matrix.support_target }}.md" in job
    assert "name: distribution-smoke-${{ matrix.support_target }}" in job
    assert "if: always()" in job
    assert "if-no-files-found: error" in job


def test_release_aggregation_downloads_distribution_evidence_before_checksums() -> None:
    release_job = RELEASE.read_text(encoding="utf-8").split("  github-release:", 1)[1]

    download_pos = release_job.index("Download distribution clean-install evidence")
    checksum_pos = release_job.index("Generate checksum manifest")
    assert download_pos < checksum_pos
    assert "pattern: distribution-smoke-*" in release_job
    assert "path: release-artifacts/distribution" in release_job
    assert "merge-multiple: true" in release_job


def test_public_distribution_support_page_matches_machine_policy() -> None:
    import json

    policy = json.loads((ROOT / "config" / "distribution-support.json").read_text(encoding="utf-8"))
    page_path = ROOT / "docs" / "installation" / "distribution-support.md"
    assert page_path.is_file()
    page = page_path.read_text(encoding="utf-8")

    for target in policy["targets"]:
        assert target["target_id"] in page
        assert target["support_level"] in page
    assert "GitHub Releases" in page
    assert "PyPI" in page
    assert "PyPI end-user installation is enabled" in page
    assert "zaptrace-eda==0.3.3" in page
    assert "GitHub Releases + PyPI" in page
    assert "GHCR" in page
    assert "not enabled" in page
    assert "distribution-smoke-sdist-linux-x86_64-cp313.json" in page
    assert "distribution-smoke-<target-id>.json" in page
    assert "source distribution" in page.lower()
    assert "universal platform support" in page.lower()


def test_committed_distribution_policy_records_verified_pypi_channel() -> None:
    import json

    policy = json.loads((ROOT / "config" / "distribution-support.json").read_text(encoding="utf-8"))
    python_rows = [
        row
        for row in policy["targets"]
        if row["artifact_type"] in {"native-wheel", "source-distribution"}
        and row["support_level"] in {"supported", "best-effort"}
    ]
    assert python_rows
    assert all(row["distribution_channel"] == "github-releases+pypi" for row in python_rows)
    assert all("PyPI" in row["guidance"] for row in python_rows)


def test_distribution_support_is_linked_from_install_release_and_navigation() -> None:
    getting_started = (ROOT / "docs" / "GETTING_STARTED.md").read_text(encoding="utf-8")
    release_process = (ROOT / "docs" / "development" / "release-process.md").read_text(encoding="utf-8")
    release_verification = (ROOT / "docs" / "security" / "release-verification.md").read_text(encoding="utf-8")
    native_boundary = (ROOT / "docs" / "security" / "native-extension-boundary.md").read_text(encoding="utf-8")
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    link = "installation/distribution-support.md"
    assert link in getting_started
    assert "../installation/distribution-support.md" in release_process
    assert "../installation/distribution-support.md" in release_verification
    assert "../installation/distribution-support.md" in native_boundary
    assert "Distribution Support: installation/distribution-support.md" in nav
    assert "superpowers/" not in nav


def test_distribution_support_documents_registry_identity_risk_review() -> None:
    page = (ROOT / "docs" / "installation" / "distribution-support.md").read_text(encoding="utf-8")

    assert "Name normalization and abuse-risk review" in page
    assert "collision" in page.lower()
    assert "typosquatting" in page.lower()
    assert "zaptrace_eda" in page
    assert "zaptrace.eda" in page


def test_distribution_support_uses_normalized_registry_artifact_filenames() -> None:
    page = (ROOT / "docs" / "installation" / "distribution-support.md").read_text(encoding="utf-8")

    assert "zaptrace_eda-<version>-*.whl" in page
    assert "zaptrace_eda-<version>.tar.gz" in page
    assert "/zaptrace-<version>-<tag>.whl" not in page
    assert "`zaptrace-<version>.tar.gz`" not in page
