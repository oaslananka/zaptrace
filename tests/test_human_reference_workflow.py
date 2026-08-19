from __future__ import annotations

from pathlib import Path

from scripts.ci_change_policy import classify_paths

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github" / "workflows" / "quality.yml"


def _benchmark_job_text() -> str:
    workflow = QUALITY.read_text(encoding="utf-8")
    start = workflow.index("  benchmark-001:")
    end = workflow.index("\n  generated-board-release-gate:", start)
    return workflow[start:end]


def test_human_reference_paths_select_heavy_ci() -> None:
    for changed_path in (
        "benchmarks/human-reference-corpus/manifest.json",
        "benchmarks/human-reference-corpus/rubric.json",
        "scripts/ci_human_reference_scorecard.py",
        "zaptrace/benchmark/human_reference.py",
    ):
        policy = classify_paths([changed_path], event_name="pull_request")
        assert policy.heavy_ci is True, changed_path
        assert policy.full_ci is True, changed_path


def test_quality_benchmark_job_runs_human_reference_gate() -> None:
    job = _benchmark_job_text()

    assert "scripts/ci_human_reference_scorecard.py" in job
    assert "--output human-reference-scorecard.json" in job
    assert "--markdown human-reference-scorecard.md" in job
    assert "--strict" in job
    assert "human-reference-scorecard.md" in job


def test_quality_benchmark_job_uploads_human_reference_evidence_with_finite_retention() -> None:
    job = _benchmark_job_text()

    for artifact in ("human-reference-scorecard.json", "human-reference-scorecard.md"):
        assert artifact in job
    assert "if-no-files-found: error" in job
    assert "retention-days: 30" in job
    assert "if: always() && needs.changes.outputs.heavy_ci == 'true'" in job
