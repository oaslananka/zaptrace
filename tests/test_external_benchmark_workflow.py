from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / ".github" / "workflows" / "quality.yml"
CHANGE_POLICY = ROOT / "scripts" / "ci_change_policy.py"


def _load_change_policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_change_policy_external_benchmark_test", CHANGE_POLICY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _benchmark_job() -> str:
    text = QUALITY.read_text(encoding="utf-8")
    start = text.index("  benchmark-001:")
    end = text.index("\n  generated-board-release-gate:", start)
    return text[start:end]


def test_external_benchmark_paths_select_heavy_ci() -> None:
    module = _load_change_policy()
    for changed_path in (
        "benchmarks/external/manifest.json",
        "benchmarks/external/sparkfun-qwiic-navigation/source/design.kicad_sch",
        "scripts/ci_external_benchmark_corpus.py",
        "scripts/ci_benchmark_reproduce.py",
    ):
        policy = module.classify_paths([changed_path], event_name="pull_request")
        assert policy.heavy_ci is True, changed_path


def test_quality_benchmark_job_runs_external_integrity_and_reproduction_gates() -> None:
    job = _benchmark_job()

    assert "scripts/ci_external_benchmark_corpus.py" in job
    assert "--manifest benchmarks/external/manifest.json" in job
    assert "--output external-benchmark-corpus.json" in job
    assert "--markdown external-benchmark-corpus.md" in job
    assert "scripts/ci_benchmark_reproduce.py" in job
    assert "--output benchmark-reproduction.json" in job
    assert "--markdown benchmark-reproduction.md" in job
    assert job.count("--strict") >= 5


def test_quality_benchmark_job_uploads_complete_evidence_with_finite_retention() -> None:
    job = _benchmark_job()

    for artifact in (
        "external-benchmark-corpus.json",
        "external-benchmark-corpus.md",
        "benchmark-reproduction.json",
        "benchmark-reproduction.md",
    ):
        assert artifact in job
    assert "if: always() && needs.changes.outputs.heavy_ci == 'true'" in job
    assert "if-no-files-found: error" in job
    assert "retention-days: 30" in job
