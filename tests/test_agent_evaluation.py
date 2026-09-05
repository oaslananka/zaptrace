"""End-to-end agent evaluation corpus, runner, and report contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from zaptrace.benchmark.agent_evaluation_corpus import (
    DEFAULT_AGENT_EVALUATION_CORPUS,
    agent_evaluation_corpus_json,
    load_agent_evaluation_corpus,
    validate_agent_evaluation_corpus,
)
from zaptrace.benchmark.agent_evaluation_models import (
    AgentEvaluationMode,
    AgentEvaluationOutcome,
    AgentEvaluationReport,
    AgentEvaluationTraceEntry,
    normalized_trace_sha256,
)

CORPUS_PATH = Path("zaptrace/benchmark/manifests/agent-evaluation-v1.json")
SCHEMA_PATH = Path("schemas/agent-evaluation-report-v1.schema.json")


def test_committed_corpus_has_ten_unique_secret_free_scenarios_and_all_outcomes() -> None:
    corpus = load_agent_evaluation_corpus(CORPUS_PATH)

    assert corpus.schema_version == "1.0"
    assert corpus.corpus_version == "2026.09"
    assert len(corpus.scenarios) >= 10
    assert len({scenario.scenario_id for scenario in corpus.scenarios}) == len(corpus.scenarios)
    assert len({scenario.prompt for scenario in corpus.scenarios}) == len(corpus.scenarios)
    assert {scenario.expected_outcome for scenario in corpus.scenarios} == set(AgentEvaluationOutcome)
    assert validate_agent_evaluation_corpus(corpus) == []

    serialized = corpus.model_dump_json().lower()
    assert "${env." not in serialized
    assert "api_key" not in serialized
    assert "https://" not in serialized
    assert all(scenario.steps for scenario in corpus.scenarios)
    assert all(scenario.expected_artifact_kinds for scenario in corpus.scenarios)


def test_committed_corpus_declares_representative_reduced_surface_tasks_and_policy_probe() -> None:
    from zaptrace.agent.tool_surfaces import SUPPORTED_TOOL_SURFACES

    corpus = load_agent_evaluation_corpus(CORPUS_PATH)
    reduced = set(SUPPORTED_TOOL_SURFACES) - {"expert"}
    task_surfaces = {scenario.surface for scenario in corpus.scenarios if scenario.evaluation_role == "task"}
    probes = [scenario for scenario in corpus.scenarios if scenario.evaluation_role == "authorization-probe"]

    assert task_surfaces == reduced
    assert probes
    assert any(
        scenario.surface == "design" and any(step.expect_authorization_denial for step in scenario.steps)
        for scenario in probes
    )
    assert all(
        set(scenario.granted_capabilities)
        <= {"read", "preview-write", "sandbox-write", "approved-commit", "release-export"}
        for scenario in corpus.scenarios
    )


def test_builtin_and_committed_corpus_are_byte_for_byte_equivalent() -> None:
    committed = load_agent_evaluation_corpus(CORPUS_PATH)

    assert committed.model_dump(mode="json") == DEFAULT_AGENT_EVALUATION_CORPUS.model_dump(mode="json")
    assert json.loads(agent_evaluation_corpus_json()) == committed.model_dump(mode="json")


def test_report_json_schema_matches_committed_contract() -> None:
    expected = AgentEvaluationReport.model_json_schema()
    committed = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed == expected


def test_normalized_trace_digest_ignores_timing_but_binds_tool_evidence() -> None:
    base = AgentEvaluationTraceEntry(
        call_number=1,
        step_id="requirements",
        executor="agent-tool",
        operation="requirements_parse",
        status="passed",
        risk="safe",
        params_sha256="a" * 64,
        result_sha256="b" * 64,
        duration_ms=1.25,
        timestamp=10.0,
    )
    slower = base.model_copy(update={"duration_ms": 999.0, "timestamp": 1000.0})
    changed = base.model_copy(update={"result_sha256": "c" * 64})

    assert normalized_trace_sha256([base]) == normalized_trace_sha256([slower])
    assert normalized_trace_sha256([base]) != normalized_trace_sha256([changed])


def test_report_modes_are_explicit() -> None:
    assert {mode.value for mode in AgentEvaluationMode} == {"ci", "nightly"}


def _subset(*scenario_ids: str):
    from zaptrace.benchmark.agent_evaluation_models import AgentEvaluationCorpus

    wanted = set(scenario_ids)
    return AgentEvaluationCorpus(
        corpus_version=DEFAULT_AGENT_EVALUATION_CORPUS.corpus_version,
        scenarios=[
            scenario for scenario in DEFAULT_AGENT_EVALUATION_CORPUS.scenarios if scenario.scenario_id in wanted
        ],
        non_claims=DEFAULT_AGENT_EVALUATION_CORPUS.non_claims,
    )


def test_runner_dispatches_tools_records_artifacts_and_cleans_session_state(tmp_path: Path) -> None:
    from zaptrace.agent.tool_impls.runtime import _sessions
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation
    from zaptrace.security.replay import get_replay
    from zaptrace.security.sandbox import sandbox_status

    report = run_agent_evaluation(
        _subset("requirements-esp32-sensor"),
        mode=AgentEvaluationMode.CI,
        output_dir=tmp_path,
    )

    result = report.scenarios[0]
    assert result.outcome == AgentEvaluationOutcome.SUCCESS
    assert result.matched_expectation is True
    assert [entry.operation for entry in result.traces] == ["requirements_parse"]
    assert result.tool_call_count == 1
    assert {artifact.kind for artifact in result.artifacts} >= {"scenario-input", "tool-trace", "scenario-result"}
    assert all(len(artifact.sha256) == 64 for artifact in result.artifacts)
    assert result.session_id not in _sessions
    assert get_replay(result.session_id) is None
    assert sandbox_status(result.session_id)["call_count"] == 0


def test_surface_metrics_treat_expected_policy_denial_as_evidence_not_runtime_failure(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    report = run_agent_evaluation(
        _subset("requirements-esp32-sensor", "design-capability-denial"),
        mode=AgentEvaluationMode.CI,
        output_dir=tmp_path,
    )

    assert report.protocol_version == "2026-07-28"
    assert len(report.surface_contract_sha256) == 64
    inspect = report.surface_metrics["inspect"]
    design = report.surface_metrics["design"]
    assert inspect.planned_call_count == 1
    assert inspect.invalid_call_count == 0
    assert inspect.authorization_denial_count == 0
    assert inspect.task_count == 1
    assert inspect.task_completion_count == 1
    assert inspect.replay_equivalent_count == 1
    assert design.planned_call_count == 1
    assert design.authorization_denial_count == 1
    assert design.expected_policy_denial_count == 1
    assert design.unexpected_policy_denial_count == 0
    assert design.runtime_failure_count == 0
    denial = next(item for item in report.scenarios if item.scenario_id == "design-capability-denial")
    assert denial.outcome == AgentEvaluationOutcome.BLOCKED
    assert denial.matched_expectation is True
    assert denial.replay_equivalent is True
    assert denial.traces[0].disposition == "expected-policy-denial"
    assert report.passed is True


def test_surface_metrics_count_hidden_registry_tool_as_invalid_call_without_dispatch(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_models import AgentEvaluationCorpus
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    scenario = next(
        item for item in DEFAULT_AGENT_EVALUATION_CORPUS.scenarios if item.scenario_id == "requirements-esp32-sensor"
    ).model_copy(deep=True)
    scenario.steps[0].operation = "synthesize_board"
    scenario.granted_capabilities = ["preview-write"]
    report = run_agent_evaluation(
        AgentEvaluationCorpus(corpus_version="surface-invalid-test", scenarios=[scenario]),
        mode=AgentEvaluationMode.CI,
        output_dir=tmp_path,
    )

    result = report.scenarios[0]
    metrics = report.surface_metrics["inspect"]
    assert result.outcome == AgentEvaluationOutcome.BLOCKED
    assert result.traces[0].disposition == "invalid-surface-call"
    assert result.traces[0].operation == "synthesize_board"
    assert metrics.planned_call_count == 1
    assert metrics.invalid_call_count == 1
    assert metrics.invalid_call_rate == 1.0
    assert metrics.runtime_failure_count == 0
    assert report.passed is False


def test_runner_classifies_all_four_outcomes_from_real_tool_contracts(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    corpus = _subset(
        "requirements-esp32-sensor",
        "proof-unrouted-board",
        "simulation-soft-skip",
        "prompt-injection-stop",
    )
    report = run_agent_evaluation(corpus, mode=AgentEvaluationMode.CI, output_dir=tmp_path)

    observed = {result.scenario_id: result.outcome for result in report.scenarios}
    assert observed == {
        "requirements-esp32-sensor": AgentEvaluationOutcome.SUCCESS,
        "proof-unrouted-board": AgentEvaluationOutcome.BLOCKED,
        "simulation-soft-skip": AgentEvaluationOutcome.HUMAN_REVIEW_REQUIRED,
        "prompt-injection-stop": AgentEvaluationOutcome.STOP_CONDITION,
    }
    assert report.passed is True
    assert report.mismatch_count == 0


def test_trace_identity_is_stable_across_output_directories(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    corpus = _subset("requirements-esp32-sensor")
    first = run_agent_evaluation(corpus, mode=AgentEvaluationMode.CI, output_dir=tmp_path / "one")
    second = run_agent_evaluation(corpus, mode=AgentEvaluationMode.CI, output_dir=tmp_path / "two")

    assert first.scenarios[0].trace_sha256 == second.scenarios[0].trace_sha256
    assert first.corpus_sha256 == second.corpus_sha256


def test_scorecard_scenario_links_benchmark_evidence(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    report = run_agent_evaluation(
        _subset("engine-scorecard"),
        mode=AgentEvaluationMode.CI,
        output_dir=tmp_path,
    )

    result = report.scenarios[0]
    assert result.outcome == AgentEvaluationOutcome.SUCCESS
    assert result.benchmark_links
    link = result.benchmark_links[0]
    assert link.step_id == "scorecard"
    assert len(link.scorecard_sha256) == 64
    assert link.score is not None
    assert any(artifact.kind == "benchmark-scorecard" for artifact in result.artifacts)


def test_synthesis_proof_scenario_generates_and_links_real_proof_pack(tmp_path: Path) -> None:
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    report = run_agent_evaluation(
        _subset("synthesis-proof-pack"),
        mode=AgentEvaluationMode.CI,
        output_dir=tmp_path,
    )

    result = report.scenarios[0]
    assert result.matched_expectation is True
    assert result.proof_links
    proof = result.proof_links[0]
    assert proof.manifest_path.endswith("proof.yaml")
    assert proof.report_path.endswith("report.json")
    assert len(proof.manifest_sha256) == 64
    assert {artifact.kind for artifact in result.artifacts} >= {"proof-pack", "tool-trace", "scenario-result"}


def test_scenario_and_step_ids_reject_path_traversal() -> None:
    import pytest
    from pydantic import ValidationError

    from zaptrace.benchmark.agent_evaluation_models import AgentEvaluationScenario, AgentEvaluationStep

    with pytest.raises(ValidationError):
        AgentEvaluationStep(step_id="../escape", executor="agent-tool", operation="requirements_parse")

    safe_step = AgentEvaluationStep(step_id="safe", executor="agent-tool", operation="requirements_parse")
    with pytest.raises(ValidationError):
        AgentEvaluationScenario(
            scenario_id="../escape",
            title="unsafe",
            prompt="unsafe",
            risk_class="low",
            expected_outcome="success",
            steps=[safe_step],
            expected_artifact_kinds=["scenario-input"],
        )


def test_corpus_validation_rejects_unknown_surface_capability_and_malformed_policy_probe() -> None:
    corpus = DEFAULT_AGENT_EVALUATION_CORPUS.model_copy(deep=True)
    task = next(item for item in corpus.scenarios if item.evaluation_role == "task")
    task.surface = "not-a-surface"
    task.granted_capabilities = ["root"]
    probe = next(item for item in corpus.scenarios if item.evaluation_role == "authorization-probe")
    for step in probe.steps:
        step.expect_authorization_denial = False

    errors = validate_agent_evaluation_corpus(corpus)

    assert any("unsupported MCP surface" in error for error in errors)
    assert any("unsupported capability grant" in error for error in errors)
    assert any("authorization-probe" in error and "expected denial" in error for error in errors)


def test_corpus_validation_rejects_unknown_tools_and_external_output_paths() -> None:
    corpus = DEFAULT_AGENT_EVALUATION_CORPUS.model_copy(deep=True)
    tool_step = corpus.scenarios[0].steps[0]
    tool_step.operation = "missing_tool"
    proof_step = next(
        step for scenario in corpus.scenarios for step in scenario.steps if step.executor == "synthesis-proof"
    )
    proof_step.params["output_dir"] = "/tmp/outside-evaluation-workspace"

    errors = validate_agent_evaluation_corpus(corpus)

    assert any("unknown agent tool" in error for error in errors)
    assert any("output_dir must stay under ${workspace}" in error for error in errors)


def test_missing_required_artifact_rewrites_scenario_result_consistently(tmp_path: Path) -> None:
    import hashlib

    from zaptrace.benchmark.agent_evaluation_models import AgentEvaluationCorpus
    from zaptrace.benchmark.agent_evaluation_runner import run_agent_evaluation

    scenario = DEFAULT_AGENT_EVALUATION_CORPUS.scenarios[0].model_copy(deep=True)
    scenario.expected_artifact_kinds.append("never-produced")
    report = run_agent_evaluation(
        AgentEvaluationCorpus(corpus_version="test", scenarios=[scenario]),
        mode="ci",
        output_dir=tmp_path,
    )

    result = report.scenarios[0]
    summary_path = tmp_path / "scenarios" / scenario.scenario_id / "scenario-result.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    artifact = next(item for item in result.artifacts if item.path == "scenario-result.json")

    assert result.outcome == AgentEvaluationOutcome.BLOCKED
    assert summary["outcome"] == "blocked"
    assert summary["stop_reason"] == "missing expected artifact kind(s): never-produced"
    assert artifact.sha256 == hashlib.sha256(summary_path.read_bytes()).hexdigest()


def test_runner_rejects_unsafe_output_root_before_executing_scenarios(monkeypatch) -> None:
    import pytest

    import zaptrace.benchmark.agent_evaluation_runner as runner

    monkeypatch.setattr(runner, "_run_scenario", lambda *_args, **_kwargs: pytest.fail("scenario executed"))

    corpus = _subset("requirements-esp32-sensor")
    unsafe_root = Path("/")
    with pytest.raises(ValueError, match="unsafe agent evaluation output directory"):
        runner.run_agent_evaluation(corpus, mode="ci", output_dir=unsafe_root)


def test_corpus_loader_rejects_file_outside_trusted_root(tmp_path: Path) -> None:
    import pytest

    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(agent_evaluation_corpus_json(), encoding="utf-8")

    with pytest.raises(ValueError, match="escapes trusted root"):
        load_agent_evaluation_corpus(outside, root=trusted_root)
