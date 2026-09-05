"""CI/nightly agent evaluation harness tests."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_agent_evaluation import main
from zaptrace.benchmark.agent_evaluation_corpus import (
    DEFAULT_AGENT_EVALUATION_CORPUS,
    agent_evaluation_corpus_json,
)
from zaptrace.benchmark.agent_evaluation_models import AgentEvaluationOutcome


def test_ci_script_writes_identity_bound_json_and_markdown(tmp_path: Path) -> None:
    output = tmp_path / "agent-evaluation-report.json"
    markdown = tmp_path / "agent-evaluation-report.md"
    artifacts = tmp_path / "artifacts"

    code = main(
        [
            "--mode",
            "ci",
            "--scenario",
            "requirements-esp32-sensor",
            "--artifact-dir",
            str(artifacts),
            "--output",
            str(output),
            "--markdown",
            str(markdown),
            "--strict",
        ]
    )

    assert code == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["scenario_count"] == 1
    assert report["mode"] == "ci"
    assert report["evidence_identity"]["identity_sha256"]
    assert report["protocol_version"] == "2026-07-28"
    assert len(report["surface_contract_sha256"]) == 64
    assert report["surface_metrics"]["inspect"]["task_count"] == 1
    assert report["surface_metrics"]["inspect"]["replay_equivalent_count"] == 1
    assert len(report["report_sha256"]) == 64
    text = markdown.read_text(encoding="utf-8")
    assert "# Agent Evaluation Harness" in text
    assert "requirements-esp32-sensor" in text
    assert "## MCP surface metrics" in text
    assert "Invalid-call rate" in text
    assert "Authorization-denial rate" in text
    assert "Expected policy denials" in text
    assert "Replay equivalent" in text
    assert "not language-model quality" in text


def test_strict_mode_fails_when_observed_outcome_mismatches_contract(tmp_path: Path, monkeypatch) -> None:
    corpus = DEFAULT_AGENT_EVALUATION_CORPUS.model_copy(deep=True)
    scenario = next(item for item in corpus.scenarios if item.scenario_id == "requirements-esp32-sensor")
    scenario.expected_outcome = AgentEvaluationOutcome.BLOCKED
    corpus_path = tmp_path / "mismatch.json"
    corpus_path.write_text(agent_evaluation_corpus_json(corpus), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--corpus",
            str(corpus_path),
            "--scenario",
            "requirements-esp32-sensor",
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.md"),
            "--strict",
        ]
    )

    assert code == 1


def test_quality_workflow_runs_and_uploads_agent_evaluation_evidence() -> None:
    workflow = Path(".github/workflows/quality.yml").read_text(encoding="utf-8")

    assert "scripts/ci_agent_evaluation.py" in workflow
    assert "agent-evaluation-report.json" in workflow
    assert "agent-evaluation-report.md" in workflow
    assert "agent-evaluation-artifacts" in workflow
    assert "github.event_name" in workflow
    assert "nightly" in workflow


def test_ci_script_refuses_to_delete_an_unowned_existing_artifact_directory(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "valuable"
    artifact_dir.mkdir()
    sentinel = artifact_dir / "keep.txt"
    sentinel.write_text("do not delete", encoding="utf-8")

    code = main(
        [
            "--scenario",
            "requirements-esp32-sensor",
            "--artifact-dir",
            str(artifact_dir),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.md"),
        ]
    )

    assert code == 2
    assert sentinel.read_text(encoding="utf-8") == "do not delete"


def test_ci_script_fails_closed_when_committed_report_schema_drifts(tmp_path: Path, monkeypatch) -> None:
    import scripts.ci_agent_evaluation as module

    bad_schema = tmp_path / "agent-evaluation.schema.json"
    bad_schema.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "REPORT_SCHEMA", bad_schema)

    code = module.main(
        [
            "--scenario",
            "requirements-esp32-sensor",
            "--artifact-dir",
            str(tmp_path / "artifacts"),
            "--output",
            str(tmp_path / "report.json"),
            "--markdown",
            str(tmp_path / "report.md"),
        ]
    )

    assert code == 2


def test_agent_evaluation_docs_define_surface_metric_semantics_and_non_claims() -> None:
    text = Path("docs/benchmarks/agent-evaluation-harness.md").read_text(encoding="utf-8")

    assert "Invalid-call rate" in text
    assert "Authorization-denial rate" in text
    assert "Expected policy denial" in text
    assert "Runtime failure" in text
    assert "Task completion" in text
    assert "Replay equivalence" in text
    assert "2026-07-28" in text
    assert "surface contract SHA-256" in text
    assert "source commit" in text
    assert "does not prove hardware correctness" in text
