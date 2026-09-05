"""Deterministic, secret-free end-to-end agent evaluation runner."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from zaptrace.agent.tool_impls.registry import TOOL_REGISTRY, call_tool
from zaptrace.agent.tool_impls.runtime import _sessions
from zaptrace.agent.tool_surfaces import SUPPORTED_TOOL_SURFACES, surface_tool_names
from zaptrace.benchmark.agent_evaluation_models import (
    AgentEvaluationArtifact,
    AgentEvaluationBenchmarkLink,
    AgentEvaluationCallDisposition,
    AgentEvaluationCorpus,
    AgentEvaluationExecutor,
    AgentEvaluationMode,
    AgentEvaluationOperator,
    AgentEvaluationOutcome,
    AgentEvaluationProofLink,
    AgentEvaluationReport,
    AgentEvaluationScenario,
    AgentEvaluationScenarioResult,
    AgentEvaluationScenarioRole,
    AgentEvaluationStep,
    AgentEvaluationStepStatus,
    AgentEvaluationSurfaceMetrics,
    AgentEvaluationTraceEntry,
    normalized_trace_sha256,
)
from zaptrace.security.policy import authorize_capability
from zaptrace.security.replay import get_replay, remove_replay
from zaptrace.security.sandbox import remove_sandbox

_PLACEHOLDER = re.compile(r"\$\{([^}]+)\}")
_OUTPUT_MARKER = ".zaptrace-agent-evaluation-output"
_SCENARIO_INPUT_NAME = "scenario-input.json"
_TOOL_TRACE_NAME = "tool-trace.json"
_SCENARIO_RESULT_NAME = "scenario-result.json"
_PROOF_LINK_NAME = "proof-link.json"
_BENCHMARK_SCORECARD_NAME = "benchmark-scorecard.json"
_PROOF_MANIFEST_NAME = "proof.yaml"
_PROOF_REPORT_NAME = "report.json"
_AGENT_EVALUATION_REPORT_NAME = "agent-evaluation-report.json"
_ARTIFACT_KIND_BY_NAME = {
    _SCENARIO_INPUT_NAME: "scenario-input",
    _TOOL_TRACE_NAME: "tool-trace",
    _SCENARIO_RESULT_NAME: "scenario-result",
    _PROOF_LINK_NAME: "proof-link",
    _BENCHMARK_SCORECARD_NAME: "benchmark-scorecard",
}
_ARTIFACT_KIND_BY_PREFIX = {
    "proof-pack/": "proof-pack",
    "manufacturing/": "manufacturing",
}


def _prepare_output_root(path: str | Path) -> Path:
    """Return a safe harness-owned output root without deleting unrelated content."""
    resolved = Path(path).resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    if resolved in forbidden:
        raise ValueError(f"unsafe agent evaluation output directory: {resolved}")
    marker = resolved / _OUTPUT_MARKER
    if resolved.exists():
        if not resolved.is_dir():
            raise ValueError(f"agent evaluation output is not a directory: {resolved}")
        children = list(resolved.iterdir())
        if children and not marker.is_file():
            raise ValueError(f"existing agent evaluation output is not harness-owned: {resolved}")
    else:
        resolved.mkdir(parents=True)
    marker.write_text("ZapTrace agent evaluation output\n", encoding="utf-8")
    return resolved


def _stable_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _replace_sensitive_paths(value: Any, *, workspace: Path, session_id: str) -> Any:
    """Replace run-local identities before deterministic hashing."""
    if isinstance(value, str):
        return value.replace(str(workspace), "${workspace}").replace(session_id, "${session_id}")
    if isinstance(value, dict):
        return {
            str(key): _replace_sensitive_paths(item, workspace=workspace, session_id=session_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_sensitive_paths(item, workspace=workspace, session_id=session_id) for item in value]
    if isinstance(value, tuple):
        return [_replace_sensitive_paths(item, workspace=workspace, session_id=session_id) for item in value]
    return value


def _lookup(value: Any, path: str) -> Any:
    current = value
    for part in path.split(".") if path else []:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(path)
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            current = getattr(current, part)
    return current


def _resolve_templates(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _resolve_templates(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_templates(item, context) for item in value]
    if not isinstance(value, str):
        return value
    full = _PLACEHOLDER.fullmatch(value)
    if full:
        return _lookup(context, full.group(1))

    def replace(match: re.Match[str]) -> str:
        return str(_lookup(context, match.group(1)))

    return _PLACEHOLDER.sub(replace, value)


def _rule_matches(actual: Any, operator: AgentEvaluationOperator, expected: Any) -> bool:
    if operator == AgentEvaluationOperator.EQUALS:
        return actual == expected
    if operator == AgentEvaluationOperator.NOT_EQUALS:
        return actual != expected
    if operator == AgentEvaluationOperator.TRUTHY:
        return bool(actual)
    if operator == AgentEvaluationOperator.FALSY:
        return not bool(actual)
    if operator == AgentEvaluationOperator.CONTAINS:
        return expected in actual
    if operator == AgentEvaluationOperator.IN:
        return actual in expected
    raise ValueError(f"unsupported outcome operator: {operator}")


def _evaluate_outcome(
    scenario: AgentEvaluationScenario, step_state: dict[str, Any]
) -> tuple[AgentEvaluationOutcome, str]:
    context = {"steps": step_state}
    for rule in scenario.outcome_rules:
        try:
            actual = _lookup(context, rule.path)
        except (KeyError, AttributeError, IndexError, TypeError):
            continue
        if _rule_matches(actual, rule.operator, rule.value):
            return rule.outcome, rule.reason
    return AgentEvaluationOutcome.SUCCESS, "all configured steps completed without a matching blocking rule"


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _workspace_files(workspace: Path) -> set[Path]:
    return {path for path in workspace.rglob("*") if path.is_file()}


def _artifact_kind(relative: str) -> str:
    exact = _ARTIFACT_KIND_BY_NAME.get(relative)
    if exact is not None:
        return exact
    return next(
        (kind for prefix, kind in _ARTIFACT_KIND_BY_PREFIX.items() if relative.startswith(prefix)),
        "generated-artifact",
    )


def _collect_artifacts(workspace: Path, produced_by: dict[str, str]) -> list[AgentEvaluationArtifact]:
    artifacts: list[AgentEvaluationArtifact] = []
    for path in sorted(_workspace_files(workspace)):
        relative = path.relative_to(workspace).as_posix()
        data = path.read_bytes()
        artifacts.append(
            AgentEvaluationArtifact(
                path=relative,
                kind=_artifact_kind(relative),
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                produced_by_step=produced_by.get(relative, "harness"),
            )
        )
    return artifacts


def _execute_step(executor: AgentEvaluationExecutor, operation: str, params: dict[str, Any], workspace: Path) -> Any:
    if executor == AgentEvaluationExecutor.AGENT_TOOL:
        return call_tool(operation, **params)
    if executor == AgentEvaluationExecutor.SYNTHESIS_PROOF:
        if operation != "generate_synthesis_proof":
            raise ValueError(f"unsupported synthesis-proof operation: {operation}")
        from zaptrace.synthesis.proof import generate_synthesis_proof

        pack = generate_synthesis_proof(**params)
        return {
            "name": pack.manifest.name,
            "passed": pack.passed,
            "autonomous_signoff": pack.autonomous_signoff.to_evidence_record(),
            "manifest_path": str(Path(params["output_dir"]) / _PROOF_MANIFEST_NAME),
            "report_path": str(Path(params["output_dir"]) / _PROOF_REPORT_NAME),
        }
    if executor == AgentEvaluationExecutor.ENGINE_BENCHMARK:
        if operation != "run_benchmark":
            raise ValueError(f"unsupported engine-benchmark operation: {operation}")
        from zaptrace.synthesis.benchmark import run_benchmark

        result = run_benchmark().to_dict()
        _write_json(workspace / _BENCHMARK_SCORECARD_NAME, result)
        return result
    raise ValueError(f"unsupported agent evaluation executor: {executor}")


def _proof_link_for_step(
    step: AgentEvaluationStep,
    *,
    workspace: Path,
    result: dict[str, Any],
) -> AgentEvaluationProofLink:
    """Build one proof link from an already-executed scenario step."""
    if step.executor != AgentEvaluationExecutor.SYNTHESIS_PROOF:
        status = "pass" if bool(result.get("passed")) else "blocked"
        return AgentEvaluationProofLink(step_id=step.step_id, autonomous_status=status)

    manifest = workspace / "proof-pack" / _PROOF_MANIFEST_NAME
    report = workspace / "proof-pack" / _PROOF_REPORT_NAME
    status = str(_lookup(result, "autonomous_signoff.status")) if result else ""
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else ""
    return AgentEvaluationProofLink(
        step_id=step.step_id,
        manifest_path=manifest.relative_to(workspace).as_posix(),
        report_path=report.relative_to(workspace).as_posix(),
        manifest_sha256=manifest_sha256,
        autonomous_status=status,
    )


def _proof_links(
    scenario: AgentEvaluationScenario,
    workspace: Path,
    step_state: dict[str, Any],
) -> list[AgentEvaluationProofLink]:
    links: list[AgentEvaluationProofLink] = []
    for step in scenario.steps:
        if "proof-pack" not in step.tags:
            continue
        state = step_state.get(step.step_id, {})
        result = state.get("result", {}) if isinstance(state, dict) else {}
        links.append(_proof_link_for_step(step, workspace=workspace, result=result))
    if links:
        _write_json(workspace / _PROOF_LINK_NAME, [link.model_dump(mode="json") for link in links])
    return links


def _benchmark_links(
    scenario: AgentEvaluationScenario,
    workspace: Path,
    step_state: dict[str, Any],
) -> list[AgentEvaluationBenchmarkLink]:
    links: list[AgentEvaluationBenchmarkLink] = []
    scorecard = workspace / _BENCHMARK_SCORECARD_NAME
    for step in scenario.steps:
        if "scorecard" not in step.tags:
            continue
        result = step_state.get(step.step_id, {}).get("result", {})
        links.append(
            AgentEvaluationBenchmarkLink(
                step_id=step.step_id,
                board_family_id=scenario.board_family_id,
                scorecard_sha256=(
                    hashlib.sha256(scorecard.read_bytes()).hexdigest() if scorecard.exists() else _stable_sha256(result)
                ),
                score=float(result["mean_score"]) if isinstance(result, dict) and "mean_score" in result else None,
                grade=str(result.get("grade", "")) if isinstance(result, dict) else "",
            )
        )
    return links


def _surface_call_preflight(
    scenario: AgentEvaluationScenario,
    step: AgentEvaluationStep,
) -> tuple[AgentEvaluationCallDisposition | None, str, str]:
    """Classify one explicit MCP-surface call before shared-dispatch execution."""
    if step.executor != AgentEvaluationExecutor.AGENT_TOOL or not scenario.surface:
        return None, "", ""
    if step.operation not in surface_tool_names(scenario.surface):
        return (
            AgentEvaluationCallDisposition.INVALID_SURFACE_CALL,
            "",
            f"tool {step.operation!r} is not visible on MCP surface {scenario.surface!r}",
        )
    required = str(TOOL_REGISTRY[step.operation]["capability"])
    allowed, reason = authorize_capability(required, set(scenario.granted_capabilities))
    if not allowed:
        disposition = (
            AgentEvaluationCallDisposition.EXPECTED_POLICY_DENIAL
            if step.expect_authorization_denial
            else AgentEvaluationCallDisposition.UNEXPECTED_POLICY_DENIAL
        )
        return disposition, required, reason
    if step.expect_authorization_denial:
        return (
            AgentEvaluationCallDisposition.AUTHORIZATION_EXPECTATION_MISMATCH,
            required,
            f"expected deny-by-default decision but authorization allowed: {reason}",
        )
    return None, required, reason


def _preflight_failure(
    step: AgentEvaluationStep,
    *,
    surface: str,
    disposition: AgentEvaluationCallDisposition,
    required_capability: str,
    reason: str,
    workspace: Path,
    session_id: str,
    call_number: int,
    params: dict[str, Any],
    step_state: dict[str, Any],
) -> tuple[AgentEvaluationTraceEntry, AgentEvaluationOutcome, str]:
    """Return stable evidence for a call rejected before runtime dispatch."""
    if disposition == AgentEvaluationCallDisposition.INVALID_SURFACE_CALL:
        error_type = "InvalidSurfaceToolCall"
    elif disposition == AgentEvaluationCallDisposition.AUTHORIZATION_EXPECTATION_MISMATCH:
        error_type = "AuthorizationExpectationMismatch"
    else:
        error_type = "OperationNotAuthorized"
    normalized_result = {
        "error_type": error_type,
        "error": _replace_sensitive_paths(reason, workspace=workspace, session_id=session_id),
    }
    step_state[step.step_id] = {"error": normalized_result, "status": "failed"}
    outcome = step.on_error_outcome or AgentEvaluationOutcome.BLOCKED
    status = (
        AgentEvaluationStepStatus.STOPPED
        if outcome == AgentEvaluationOutcome.STOP_CONDITION
        else AgentEvaluationStepStatus.FAILED
    )
    trace = AgentEvaluationTraceEntry(
        call_number=call_number,
        step_id=step.step_id,
        executor=step.executor,
        operation=step.operation,
        status=status,
        surface=surface,
        disposition=disposition,
        required_capability=required_capability,
        authorization_reason=reason,
        risk="safe",
        params_sha256=_stable_sha256(_replace_sensitive_paths(params, workspace=workspace, session_id=session_id)),
        result_sha256=_stable_sha256(normalized_result),
        error_type=error_type,
        error_message=str(normalized_result["error"]),
    )
    return trace, outcome, str(normalized_result["error"])


def _execute_scenario_step(
    scenario: AgentEvaluationScenario,
    step: AgentEvaluationStep,
    *,
    call_number: int,
    workspace: Path,
    session_id: str,
    context: dict[str, Any],
    step_state: dict[str, Any],
    produced_by: dict[str, str],
) -> tuple[AgentEvaluationTraceEntry, AgentEvaluationOutcome | None, str]:
    """Execute one bounded step and return its trace plus any stop outcome."""
    params = _resolve_templates(step.params, context)
    disposition, required_capability, authorization_reason = _surface_call_preflight(scenario, step)
    if disposition is not None:
        trace, outcome, stop_reason = _preflight_failure(
            step,
            surface=scenario.surface,
            disposition=disposition,
            required_capability=required_capability,
            reason=authorization_reason,
            workspace=workspace,
            session_id=session_id,
            call_number=call_number,
            params=params,
            step_state=step_state,
        )
        return trace, outcome, stop_reason
    before = _workspace_files(workspace)
    step_started = time.perf_counter()
    timestamp = time.time()
    outcome: AgentEvaluationOutcome | None = None
    stop_reason = ""
    try:
        raw_result = _execute_step(step.executor, step.operation, params, workspace)
        normalized_result = _replace_sensitive_paths(raw_result, workspace=workspace, session_id=session_id)
        step_state[step.step_id] = {"result": raw_result, "status": "passed"}
        for variable, path in step.captures.items():
            context[variable] = _lookup(raw_result, path)
        status = AgentEvaluationStepStatus.PASSED
        error_type = ""
        error_message = ""
        call_disposition = AgentEvaluationCallDisposition.EXECUTED
    except Exception as exc:  # scenario evidence must record tool failures
        normalized_result = {
            "error_type": type(exc).__name__,
            "error": _replace_sensitive_paths(str(exc), workspace=workspace, session_id=session_id),
        }
        step_state[step.step_id] = {"error": normalized_result, "status": "failed"}
        outcome = step.on_error_outcome or AgentEvaluationOutcome.BLOCKED
        stop_reason = str(normalized_result["error"])
        status = (
            AgentEvaluationStepStatus.STOPPED
            if outcome == AgentEvaluationOutcome.STOP_CONDITION
            else AgentEvaluationStepStatus.FAILED
        )
        error_type = type(exc).__name__
        error_message = stop_reason
        call_disposition = AgentEvaluationCallDisposition.RUNTIME_FAILURE
    new_files = sorted(path.relative_to(workspace).as_posix() for path in _workspace_files(workspace) - before)
    for relative in new_files:
        produced_by[relative] = step.step_id
    replay = get_replay(session_id)
    risk = replay.entries[-1].risk if replay and replay.entries else "safe"
    trace = AgentEvaluationTraceEntry(
        call_number=call_number,
        step_id=step.step_id,
        executor=step.executor,
        operation=step.operation,
        status=status,
        surface=scenario.surface,
        disposition=call_disposition,
        required_capability=required_capability,
        authorization_reason=authorization_reason,
        risk=risk,
        params_sha256=_stable_sha256(_replace_sensitive_paths(params, workspace=workspace, session_id=session_id)),
        result_sha256=_stable_sha256(normalized_result),
        duration_ms=round((time.perf_counter() - step_started) * 1000, 3),
        timestamp=timestamp,
        error_type=error_type,
        error_message=error_message,
        artifact_paths=new_files,
    )
    return trace, outcome, stop_reason


def _run_scenario_steps(
    scenario: AgentEvaluationScenario,
    *,
    workspace: Path,
    session_id: str,
    context: dict[str, Any],
    step_state: dict[str, Any],
    produced_by: dict[str, str],
) -> tuple[list[AgentEvaluationTraceEntry], AgentEvaluationOutcome, str]:
    traces: list[AgentEvaluationTraceEntry] = []
    for call_number, step in enumerate(scenario.steps, start=1):
        trace, outcome, stop_reason = _execute_scenario_step(
            scenario,
            step,
            call_number=call_number,
            workspace=workspace,
            session_id=session_id,
            context=context,
            step_state=step_state,
            produced_by=produced_by,
        )
        traces.append(trace)
        if outcome is not None:
            return traces, outcome, stop_reason
    outcome, stop_reason = _evaluate_outcome(scenario, step_state)
    return traces, outcome, stop_reason


def _finalize_scenario_evidence(
    scenario: AgentEvaluationScenario,
    *,
    workspace: Path,
    session_id: str,
    step_state: dict[str, Any],
    produced_by: dict[str, str],
    traces: list[AgentEvaluationTraceEntry],
    outcome: AgentEvaluationOutcome,
    stop_reason: str,
    replay_digest: str,
    started: float,
) -> AgentEvaluationScenarioResult:
    _write_json(workspace / _TOOL_TRACE_NAME, [entry.model_dump(mode="json") for entry in traces])
    produced_by[_TOOL_TRACE_NAME] = "harness"
    proof_links = _proof_links(scenario, workspace, step_state)
    if proof_links:
        produced_by[_PROOF_LINK_NAME] = proof_links[0].step_id
    benchmark_links = _benchmark_links(scenario, workspace, step_state)
    summary = {
        "scenario_id": scenario.scenario_id,
        "expected_outcome": scenario.expected_outcome.value,
        "outcome": outcome.value,
        "matched_expectation": outcome == scenario.expected_outcome,
        "stop_reason": stop_reason,
        "trace_sha256": normalized_trace_sha256(traces),
    }
    _write_json(workspace / _SCENARIO_RESULT_NAME, summary)
    produced_by[_SCENARIO_RESULT_NAME] = "harness"
    artifacts = _collect_artifacts(workspace, produced_by)
    missing_kinds = sorted(set(scenario.expected_artifact_kinds) - {artifact.kind for artifact in artifacts})
    if missing_kinds:
        outcome = AgentEvaluationOutcome.BLOCKED
        stop_reason = "missing expected artifact kind(s): " + ", ".join(missing_kinds)
        summary.update(
            {
                "outcome": outcome.value,
                "matched_expectation": outcome == scenario.expected_outcome,
                "stop_reason": stop_reason,
            }
        )
        _write_json(workspace / _SCENARIO_RESULT_NAME, summary)
        artifacts = _collect_artifacts(workspace, produced_by)
    return AgentEvaluationScenarioResult(
        scenario_id=scenario.scenario_id,
        title=scenario.title,
        risk_class=scenario.risk_class,
        expected_outcome=scenario.expected_outcome,
        outcome=outcome,
        matched_expectation=outcome == scenario.expected_outcome,
        stop_reason=stop_reason,
        session_id=session_id,
        tool_call_count=sum(1 for entry in traces if entry.executor == AgentEvaluationExecutor.AGENT_TOOL),
        failure_count=sum(1 for entry in traces if entry.status != AgentEvaluationStepStatus.PASSED),
        total_duration_ms=round((time.perf_counter() - started) * 1000, 3),
        trace_sha256=normalized_trace_sha256(traces),
        replay_digest=replay_digest,
        traces=traces,
        artifacts=artifacts,
        proof_links=proof_links,
        benchmark_links=benchmark_links,
        non_claims=[*scenario.non_claims],
    )


def _run_scenario(scenario: AgentEvaluationScenario, *, output_dir: Path) -> AgentEvaluationScenarioResult:
    workspace = output_dir / "scenarios" / scenario.scenario_id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    session_id = f"agent-eval-{scenario.scenario_id}"
    _sessions.pop(session_id, None)
    remove_replay(session_id)
    remove_sandbox(session_id)
    context: dict[str, Any] = {
        "prompt": scenario.prompt,
        "session_id": session_id,
        "workspace": str(workspace.resolve()),
    }
    _write_json(workspace / _SCENARIO_INPUT_NAME, scenario.model_dump(mode="json"))
    step_state: dict[str, Any] = {}
    produced_by: dict[str, str] = {_SCENARIO_INPUT_NAME: "harness"}
    started = time.perf_counter()
    previous_persistence = os.environ.get("ZAPTRACE_PERSISTENCE_DISABLED")
    os.environ["ZAPTRACE_PERSISTENCE_DISABLED"] = "1"
    try:
        traces, outcome, stop_reason = _run_scenario_steps(
            scenario,
            workspace=workspace,
            session_id=session_id,
            context=context,
            step_state=step_state,
            produced_by=produced_by,
        )
        replay = get_replay(session_id)
        return _finalize_scenario_evidence(
            scenario,
            workspace=workspace,
            session_id=session_id,
            step_state=step_state,
            produced_by=produced_by,
            traces=traces,
            outcome=outcome,
            stop_reason=stop_reason,
            replay_digest=replay.digest if replay else "",
            started=started,
        )
    finally:
        _sessions.pop(session_id, None)
        remove_replay(session_id)
        remove_sandbox(session_id)
        if previous_persistence is None:
            os.environ.pop("ZAPTRACE_PERSISTENCE_DISABLED", None)
        else:
            os.environ["ZAPTRACE_PERSISTENCE_DISABLED"] = previous_persistence


def _corpus_sha256(corpus: AgentEvaluationCorpus) -> str:
    return _stable_sha256(corpus.model_dump(mode="json"))


def _report_sha256(report: AgentEvaluationReport) -> str:
    payload = report.model_dump(mode="json", exclude={"generated_at", "report_sha256"})
    for scenario in payload["scenarios"]:
        scenario.pop("total_duration_ms", None)
        scenario.pop("replay_digest", None)
        for trace in scenario.get("traces", []):
            trace.pop("duration_ms", None)
            trace.pop("timestamp", None)
    return _stable_sha256(payload)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _surface_contract() -> tuple[str, dict[str, tuple[str, ...]]]:
    surfaces = {surface: surface_tool_names(surface) for surface in SUPPORTED_TOOL_SURFACES if surface != "expert"}
    payload = {
        surface: [{"name": name, "capability": TOOL_REGISTRY[name]["capability"]} for name in names]
        for surface, names in surfaces.items()
    }
    return _stable_sha256(payload), surfaces


def _surface_metrics(
    scenarios: list[AgentEvaluationScenario],
    results: list[AgentEvaluationScenarioResult],
) -> tuple[dict[str, AgentEvaluationSurfaceMetrics], int]:
    _, surface_contracts = _surface_contract()
    scenario_by_id = {scenario.scenario_id: scenario for scenario in scenarios}
    metrics: dict[str, AgentEvaluationSurfaceMetrics] = {}
    regressions = 0
    for surface, names in surface_contracts.items():
        surface_scenarios = [scenario for scenario in scenarios if scenario.surface == surface]
        surface_results = [result for result in results if scenario_by_id[result.scenario_id].surface == surface]
        traces = [
            trace
            for result in surface_results
            for trace in result.traces
            if trace.executor == AgentEvaluationExecutor.AGENT_TOOL
        ]
        planned = sum(
            1
            for scenario in surface_scenarios
            for step in scenario.steps
            if step.executor == AgentEvaluationExecutor.AGENT_TOOL
        )
        invalid = sum(trace.disposition == AgentEvaluationCallDisposition.INVALID_SURFACE_CALL for trace in traces)
        expected_denials = sum(
            trace.disposition == AgentEvaluationCallDisposition.EXPECTED_POLICY_DENIAL for trace in traces
        )
        unexpected_denials = sum(
            trace.disposition == AgentEvaluationCallDisposition.UNEXPECTED_POLICY_DENIAL for trace in traces
        )
        expectation_mismatches = sum(
            trace.disposition == AgentEvaluationCallDisposition.AUTHORIZATION_EXPECTATION_MISMATCH for trace in traces
        )
        denials = expected_denials + unexpected_denials
        runtime_failures = sum(trace.disposition == AgentEvaluationCallDisposition.RUNTIME_FAILURE for trace in traces)
        task_results = [
            result
            for result in surface_results
            if scenario_by_id[result.scenario_id].evaluation_role == AgentEvaluationScenarioRole.TASK
        ]
        task_outcomes = {outcome.value: 0 for outcome in AgentEvaluationOutcome}
        for result in task_results:
            task_outcomes[result.outcome.value] += 1
        task_completed = sum(result.matched_expectation for result in task_results)
        replay_results = [result for result in surface_results if result.replay_equivalent is not None]
        replay_equivalent = sum(result.replay_equivalent is True for result in replay_results)
        replay_mismatches = len(replay_results) - replay_equivalent
        regressions += invalid + unexpected_denials + expectation_mismatches + runtime_failures + replay_mismatches
        metrics[surface] = AgentEvaluationSurfaceMetrics(
            surface=surface,
            visible_tool_count=len(names),
            tool_contract_sha256=_stable_sha256(
                [{"name": name, "capability": TOOL_REGISTRY[name]["capability"]} for name in names]
            ),
            planned_call_count=planned,
            invalid_call_count=invalid,
            invalid_call_rate=_rate(invalid, planned),
            authorization_denial_count=denials,
            authorization_denial_rate=_rate(denials, planned),
            expected_policy_denial_count=expected_denials,
            unexpected_policy_denial_count=unexpected_denials,
            authorization_expectation_mismatch_count=expectation_mismatches,
            runtime_failure_count=runtime_failures,
            task_count=len(task_results),
            task_completion_count=task_completed,
            task_completion_rate=_rate(task_completed, len(task_results)),
            task_outcome_counts=task_outcomes,
            replay_check_count=len(replay_results),
            replay_equivalent_count=replay_equivalent,
            replay_mismatch_count=replay_mismatches,
            replay_equivalence_rate=_rate(replay_equivalent, len(replay_results)),
        )
    return metrics, regressions


def _run_scenario_with_replay_check(
    scenario: AgentEvaluationScenario,
    *,
    output_dir: Path,
) -> AgentEvaluationScenarioResult:
    result = _run_scenario(scenario, output_dir=output_dir)
    if not scenario.surface:
        return result
    replay_root = output_dir / ".replay-check" / scenario.scenario_id
    try:
        replay = _run_scenario(scenario, output_dir=replay_root)
        result.replay_trace_sha256 = replay.trace_sha256
        result.replay_equivalent = result.trace_sha256 == replay.trace_sha256 and result.outcome == replay.outcome
        return result
    finally:
        shutil.rmtree(replay_root, ignore_errors=True)


def run_agent_evaluation(
    corpus: AgentEvaluationCorpus,
    *,
    mode: AgentEvaluationMode | str,
    output_dir: str | Path,
    evidence_identity: dict[str, Any] | None = None,
) -> AgentEvaluationReport:
    """Execute all scenarios enabled for *mode* and write auditable evidence."""
    resolved_mode = AgentEvaluationMode(mode)
    root = _prepare_output_root(output_dir)
    selected = [scenario for scenario in corpus.scenarios if resolved_mode in scenario.modes]
    results = [_run_scenario_with_replay_check(scenario, output_dir=root) for scenario in selected]
    outcome_counts = {outcome.value: 0 for outcome in AgentEvaluationOutcome}
    for result in results:
        outcome_counts[result.outcome.value] += 1
    mismatch_count = sum(1 for result in results if not result.matched_expectation)
    surface_contract_sha256, _ = _surface_contract()
    surface_metrics, surface_regression_count = _surface_metrics(selected, results)
    report = AgentEvaluationReport(
        corpus_version=corpus.corpus_version,
        corpus_sha256=_corpus_sha256(corpus),
        protocol_version="2026-07-28",
        surface_contract_sha256=surface_contract_sha256,
        mode=resolved_mode,
        generated_at=datetime.now(UTC).isoformat(),
        passed=mismatch_count == 0 and surface_regression_count == 0,
        scenario_count=len(results),
        mismatch_count=mismatch_count,
        outcome_counts=outcome_counts,
        surface_regression_count=surface_regression_count,
        surface_metrics=surface_metrics,
        scenarios=results,
        evidence_identity=evidence_identity or {},
        non_claims=[*corpus.non_claims],
    )
    report.report_sha256 = _report_sha256(report)
    _write_json(root / _AGENT_EVALUATION_REPORT_NAME, report.model_dump(mode="json"))
    return report


__all__ = ["run_agent_evaluation"]
