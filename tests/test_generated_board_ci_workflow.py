from __future__ import annotations

from pathlib import Path


def test_quality_workflow_runs_generated_board_release_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "generated-board-release-gate:" in workflow
    assert "name: Generated board release gate" in workflow
    assert "scripts/ci_generated_board_release_gate.py" in workflow
    assert "--strict" in workflow
    assert "generated-board-release-gate.json" in workflow
    assert "name: generated-board-release-gate" in workflow
    assert "Validate physical reference-board plan" in workflow
    assert "scripts/ci_physical_validation_plan.py" in workflow
    assert "physical-validation-plan-gate.json" in workflow
    assert "name: physical-validation-plan-gate" in workflow


def test_release_summary_depends_on_generated_board_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "generated-board-release-gate" in workflow
    assert "needs.generated-board-release-gate.result" in workflow
    assert '--gate "generated-board-release-gate=${{ needs.generated-board-release-gate.result }}"' in workflow


def test_quality_workflow_runs_validation_environment_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "validation-environment:" in workflow
    assert "name: Validation environment parity" in workflow
    assert "scripts/ci_validation_environment.py" in workflow
    assert "--strict" in workflow
    assert "validation-environment.json" in workflow


def test_release_summary_depends_on_validation_environment_gate() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "needs.validation-environment.result" in workflow
    assert '--gate "validation-environment=${{ needs.validation-environment.result }}"' in workflow


def test_hardware_smoke_uses_current_router_result_shape() -> None:
    workflow = Path(".github/workflows/hardware.yml").read_text(encoding="utf-8")

    assert "_, d.routing, _ = route_design_smart(d, positions)" in workflow


def test_quality_summary_is_explicitly_snapshot_evidence() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "name: Generate snapshot gate summary" in workflow
    assert "--mode snapshot" in workflow
    assert "name: snapshot-gate-summary" in workflow


def test_release_workflow_publishes_tagged_identity_evidence() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")

    assert "name: Generate tagged release evidence" in workflow
    assert "uv lock --check && uv sync --locked --all-extras --all-groups --no-install-project --no-build" in workflow
    assert "scripts/ci_release_gate.py" in workflow
    assert "--mode release" in workflow
    assert '--tool-version "python=$(.venv/bin/python -c' in workflow
    assert '--tool-version "python=$(uv run python' not in workflow
    assert "tagged-release-evidence.json" in workflow
    assert "name: tagged-release-evidence" in workflow
    assert "Download tagged release evidence" in workflow


def test_validation_environment_uses_locked_identity_runtime() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "name: Install locked identity dependencies" in workflow
    assert "uv sync --locked --all-extras --all-groups --no-install-project --no-build" in workflow
    assert ".venv/bin/python scripts/ci_validation_environment.py" in workflow


def test_benchmark_job_publishes_identity_bound_evidence_bundle() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "scripts/ci_benchmark_001.py" in workflow
    assert "scripts/ci_benchmark_fixture_coverage.py" in workflow
    assert "scripts/ci_benchmark_fixture_integrity.py" in workflow
    assert "benchmark-fixture-coverage.json" in workflow
    assert "benchmark-fixture-integrity.json" in workflow
    assert "name: benchmark-evidence" in workflow


def test_docs_stale_job_enforces_evidence_identity_policy() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "name: Check evidence identity policy" in workflow
    assert "scripts/ci_evidence_identity.py" in workflow
    assert "--strict" in workflow
    assert "evidence-identity-policy.json" in workflow
    assert "name: evidence-identity-policy" in workflow
