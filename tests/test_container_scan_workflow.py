from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "container-security.yml"
TRIVY_ACTION = "aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_container_workflow_builds_and_smokes_one_exact_image() -> None:
    workflow = _workflow()

    assert workflow.count("docker build ") == 1
    assert "--iidfile image-iid.txt" in workflow
    assert "docker image inspect zaptrace:scan" in workflow
    assert "docker run --rm zaptrace:scan --help" in workflow
    assert workflow.count("image-ref: zaptrace:scan") == 3


def test_container_workflow_emits_sbom_json_sarif_and_policy_summary() -> None:
    workflow = _workflow()

    assert workflow.count(TRIVY_ACTION) == 3
    assert "version: v0.72.0" in workflow
    assert "format: cyclonedx" in workflow
    assert "output: container-sbom.cdx.json" in workflow
    assert "format: json" in workflow
    assert "output: trivy-results.json" in workflow
    assert "format: sarif" in workflow
    assert "output: trivy-results.sarif" in workflow
    assert "scripts/ci_container_scan_policy.py" in workflow
    assert "--image-digest image-digest.txt" in workflow
    assert "--sbom container-sbom.cdx.json" in workflow
    assert "--strict" in workflow


def test_container_workflow_uploads_code_scanning_and_retained_evidence() -> None:
    workflow = _workflow()

    assert "github/codeql-action/upload-sarif@54f647b7e1bb85c95cddabcd46b0c578ec92bc1a" in workflow
    assert "sarif_file: trivy-results.sarif" in workflow
    assert "name: container-security-evidence" in workflow
    assert "retention-days: 30" in workflow
    for artifact in (
        "image-digest.txt",
        "container-sbom.cdx.json",
        "trivy-results.json",
        "trivy-results.sarif",
        "container-scan-policy.json",
        "container-scan-summary.md",
    ):
        assert artifact in workflow


def test_container_workflow_limits_expensive_pr_runs_to_runtime_inputs() -> None:
    workflow = _workflow()

    assert "workflow_call:" in workflow
    assert "pull_request:" in workflow
    assert "Dockerfile|pyproject.toml|uv.lock" in workflow
    assert "data/*|zaptrace/*|zaptrace_core/*" in workflow
    assert "scripts/ci_container_scan_policy.py" in workflow
    assert ".github/workflows/container-security.yml" in workflow
    assert "scan_required=false" in workflow


def test_release_workflow_requires_reusable_container_security_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "container-security:" in workflow
    assert "uses: ./.github/workflows/container-security.yml" in workflow
    assert "mode: release" in workflow
    assert "needs: [python-distributions, rust-wheels, container-security, pypi-verify]" in workflow


def test_container_security_workflow_has_read_only_default_permissions() -> None:
    workflow = _workflow()
    header = workflow.split("\njobs:", 1)[0]

    assert "\npermissions:\n  contents: read\n" in header


def test_release_caller_propagates_permissions_required_by_reusable_scan() -> None:
    container_workflow = _workflow()
    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    scan_job = container_workflow.split("\n  scan:", 1)[1].split("\n    steps:", 1)[0]
    caller = release_workflow.split("  container-security:", 1)[1].split("\n  quality:", 1)[0]
    for permission in ("contents: read", "security-events: write"):
        assert permission in scan_job
        assert permission in caller


def test_release_reusable_scan_skips_duplicate_sarif_publication() -> None:
    container_workflow = _workflow()
    release_workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    workflow_call = container_workflow.split("  workflow_call:", 1)[1].split("  pull_request:", 1)[0]
    assert "upload_sarif:" in workflow_call
    assert "default: true" in workflow_call

    upload_step = container_workflow.split("      - name: Upload Trivy SARIF", 1)[1].split(
        "      - name: Upload container security evidence", 1
    )[0]
    assert "github.event_name != 'workflow_call' || inputs.upload_sarif" in upload_step

    caller = release_workflow.split("  container-security:", 1)[1].split("\n  quality:", 1)[0]
    assert "upload_sarif: false" in caller
    assert "security-events: write" in caller


def test_container_workflow_grants_only_required_sarif_permissions() -> None:
    workflow = _workflow()

    scan_job = workflow.split("\n  scan:", 1)[1].split("\n    steps:", 1)[0]
    assert "permissions:" in scan_job
    assert "contents: read" in scan_job
    assert "security-events: write" in scan_job
    assert "actions: write" not in scan_job
    assert "contents: write" not in scan_job


def test_release_caller_grants_only_permissions_required_by_reusable_scan() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    caller = workflow.split("  container-security:", 1)[1].split("\n  quality:", 1)[0]
    assert "permissions:" in caller
    assert "contents: read" in caller
    assert "security-events: write" in caller
    assert "upload_sarif: false" in caller
    assert "contents: write" not in caller
    assert "actions: write" not in caller


def test_fork_pull_requests_skip_only_sarif_publication() -> None:
    workflow = _workflow()

    upload_step = workflow.split("      - name: Upload Trivy SARIF", 1)[1].split(
        "      - name: Upload container security evidence", 1
    )[0]
    assert "github.event_name != 'pull_request'" in upload_step
    assert "github.event.pull_request.head.repo.fork == false" in upload_step
    assert "github.actor != 'dependabot[bot]'" in upload_step
    assert "if: always()" not in upload_step

    evidence_step = workflow.split("      - name: Upload container security evidence", 1)[1]
    assert "if: always()" in evidence_step


def test_container_triage_documentation_covers_enforcement_and_exceptions() -> None:
    policy = (ROOT / "docs" / "security" / "container-vulnerability-management.md").read_text(encoding="utf-8")

    for phrase in (
        "2026-08-14",
        "Critical",
        "High",
        "exploitability",
        "rationale",
        "owner",
        "expiry",
        "30 days",
        "image digest",
        "SBOM",
    ):
        assert phrase in policy


def test_dockerfile_uses_digest_only_base_and_sorted_packages() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert all("@sha256:" in line and ":3.13-alpine@" not in line for line in from_lines)
    assert "apk add --no-cache build-base cargo patchelf rust" in dockerfile


def test_container_workflow_verifies_lock_and_image_provenance() -> None:
    workflow = _workflow()

    assert "astral-sh/setup-uv@fac544c07dec837d0ccb6301d7b5580bf5edae39" in workflow
    assert "version: 0.11.29" in workflow
    assert "scripts/ci_container_reproducibility.py check-lock" in workflow
    assert "--manifest requirements/container-runtime.txt" in workflow
    assert "--build-arg SOURCE_COMMIT=" in workflow
    assert "--build-arg BASE_IMAGE_DIGEST=" in workflow
    assert "--build-arg CONTAINER_LOCK_SHA256=" in workflow
    assert "--build-arg CONTAINER_APK_LOCK_SHA256=" in workflow
    assert "--build-arg CONTAINER_BUILDER_LOCK_SHA256=" in workflow
    assert "--builder-dependency-manifest requirements/container-builder.txt" in workflow
    assert "/usr/share/zaptrace/container-build-provenance.json" in workflow
    assert "scripts/ci_container_reproducibility.py verify-image" in workflow
    assert "container-reproducibility-evidence.json" in workflow
    assert "container-reproducibility-evidence.md" in workflow


def test_container_workflow_tracks_all_reproducibility_inputs() -> None:
    workflow = _workflow()

    for path in (
        "requirements/container-runtime.txt",
        "requirements/container-apk.txt",
        "requirements/container-builder.txt",
        "scripts/ci_container_reproducibility.py",
    ):
        assert workflow.count(path) >= 2


def test_container_workflow_retains_lock_and_provenance_evidence() -> None:
    workflow = _workflow()

    for artifact in (
        "container-lock-evidence.json",
        "container-lock-evidence.md",
        "container-build-provenance.json",
        "container-reproducibility-evidence.json",
        "container-reproducibility-evidence.md",
    ):
        assert artifact in workflow


def test_release_archives_container_reproducibility_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "Download container reproducibility and scan evidence" in workflow
    assert "name: container-security-evidence" in workflow
    assert "path: release-artifacts/container-security" in workflow
    assert "subject-path: release-artifacts/**/*" in workflow
    assert "files: release-artifacts/**/*" in workflow
