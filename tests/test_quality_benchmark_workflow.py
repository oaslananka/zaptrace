"""Contract for the benchmark evidence boundary called by the required Quality gate."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github/workflows/quality.yml"
BENCHMARK = ROOT / ".github/workflows/quality-benchmark.yml"


def test_benchmark_reusable_boundary_retains_fail_closed_quality_dependency() -> None:
    quality = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))
    benchmark = yaml.safe_load(BENCHMARK.read_text(encoding="utf-8"))

    assert quality["jobs"]["benchmark-001"] == {
        "name": "Benchmark 001 acceptance",
        "needs": "changes",
        "uses": "./.github/workflows/quality-benchmark.yml",
        "with": {"heavy_ci": "${{ needs.changes.outputs.heavy_ci }}"},
    }
    assert benchmark["permissions"] == {"contents": "read"}
    assert benchmark[True]["workflow_call"]["inputs"]["heavy_ci"] == {
        "description": "Heavy-CI eligibility from Quality change classification",
        "type": "string",
        "required": True,
    }
    assert benchmark["jobs"]["acceptance"]["env"] == {
        key: quality["env"][key] for key in ("PYTHON_VERSION", "UV_VERSION", "PYTHONPATH")
    }
    assert "benchmark-001" in quality["jobs"]["release-gate-summary"]["needs"]
    summary = next(
        step
        for step in quality["jobs"]["release-gate-summary"]["steps"]
        if step.get("name") == "Generate snapshot gate summary"
    )
    assert '--gate "benchmark-001=${{ needs.benchmark-001.result }}"' in summary["run"]
    assert "secrets" not in quality["jobs"]["benchmark-001"]


def test_benchmark_producers_skip_explicitly_and_preserve_evidence() -> None:
    benchmark = yaml.safe_load(BENCHMARK.read_text(encoding="utf-8"))
    steps = benchmark["jobs"]["acceptance"]["steps"]
    assert steps[0]["if"] == "inputs.heavy_ci != 'true'"
    assert "skipping benchmark 001 acceptance" in steps[0]["run"]
    for step in steps[1:]:
        assert step["if"] == (
            "always() && inputs.heavy_ci == 'true'"
            if step.get("name") == "Upload benchmark evidence"
            else "inputs.heavy_ci == 'true'"
        ), step.get("name", step.get("uses"))
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    setup = next(step for step in steps if step.get("uses") == "./.github/actions/setup-locked-python")
    assert setup["with"] == {
        "uv-version": "${{ env.UV_VERSION }}",
        "python-version": "${{ env.PYTHON_VERSION }}",
    }
    evidence = next(step for step in steps if step.get("name") == "Upload benchmark evidence")
    assert evidence["with"]["name"] == "benchmark-evidence"
    assert evidence["with"]["if-no-files-found"] == "error"
    assert evidence["with"]["retention-days"] == 30
    for path in (
        "human-reference-scorecard.json",
        "agent-evaluation-report.json",
        "release-convergence-report.json",
        "simulation-signoff-report.json",
        "simulation-signoff-artifacts",
    ):
        assert path in evidence["with"]["path"]
    producer = next(step for step in steps if step.get("name") == "Run identity-bound benchmark evidence gates")["run"]
    assert 'if [[ "${{ github.event_name }}" == "schedule" ]]' in producer
    assert '--mode "$agent_evaluation_mode"' in producer
    for cmd in (
        "ci_benchmark_001.py",
        "ci_benchmark_fixture_coverage.py",
        "ci_benchmark_fixture_integrity.py",
        "ci_external_benchmark_corpus.py",
        "ci_benchmark_reproduce.py",
        "ci_human_reference_scorecard.py",
        "ci_agent_evaluation.py",
        "ci_release_verify_repair.py",
    ):
        assert cmd in producer
    simulation = next(step for step in steps if step.get("name") == "Run simulation-backed sign-off evidence gate")[
        "run"
    ]
    assert "--require-live-simulation" in simulation
    assert "--strict" in simulation
