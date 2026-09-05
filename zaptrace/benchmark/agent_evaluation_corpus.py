"""Versioned, secret-free scenario corpus for agent contract evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from zaptrace.benchmark.agent_evaluation_models import (
    AgentEvaluationCorpus,
    AgentEvaluationExecutor,
    AgentEvaluationOutcome,
    AgentEvaluationScenario,
    AgentEvaluationScenarioRole,
    AgentEvaluationStep,
)

DEFAULT_AGENT_EVALUATION_CORPUS_PATH = Path(__file__).with_name("manifests") / "agent-evaluation-v1.json"
_OUTPUT_PARAMETERS = frozenset({"output_dir", "output_path"})
_REQUIRED_STEP_TAGS = {
    "manufacturing": "at least one manufacturing scenario is required",
    "proof-pack": "at least one proof-pack scenario is required",
    "scorecard": "at least one benchmark scorecard scenario is required",
}


def _validate_corpus_header(corpus: AgentEvaluationCorpus) -> list[str]:
    errors: list[str] = []
    if corpus.schema_version != "1.0":
        errors.append("schema_version must be 1.0")
    if not corpus.corpus_version:
        errors.append("corpus_version is required")
    if len(corpus.scenarios) < 10:
        errors.append("at least ten agent evaluation scenarios are required")
    return errors


def _validate_unique_contracts(corpus: AgentEvaluationCorpus) -> list[str]:
    errors: list[str] = []
    ids = [scenario.scenario_id for scenario in corpus.scenarios]
    prompts = [scenario.prompt for scenario in corpus.scenarios]
    if len(ids) != len(set(ids)):
        errors.append("scenario_id values must be unique")
    if len(prompts) != len(set(prompts)):
        errors.append("scenario prompts must be unique")
    missing_outcomes = set(AgentEvaluationOutcome) - {scenario.expected_outcome for scenario in corpus.scenarios}
    if missing_outcomes:
        errors.append("missing expected outcome(s): " + ", ".join(sorted(item.value for item in missing_outcomes)))
    return errors


def _validate_step_output_path(scenario_id: str, step: AgentEvaluationStep) -> list[str]:
    errors: list[str] = []
    for parameter, value in step.params.items():
        if parameter not in _OUTPUT_PARAMETERS or not isinstance(value, str):
            continue
        if not value.startswith("${workspace}/") or ".." in value:
            errors.append(f"{scenario_id}.{step.step_id}: {parameter} must stay under ${{workspace}}")
    return errors


def _validate_step(scenario_id: str, step: AgentEvaluationStep, tool_registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if step.executor == AgentEvaluationExecutor.AGENT_TOOL and step.operation not in tool_registry:
        errors.append(f"{scenario_id}.{step.step_id}: unknown agent tool: {step.operation}")
    if step.executor == AgentEvaluationExecutor.SYNTHESIS_PROOF and step.operation != "generate_synthesis_proof":
        errors.append(f"{scenario_id}.{step.step_id}: unsupported synthesis-proof operation")
    if step.executor == AgentEvaluationExecutor.ENGINE_BENCHMARK and step.operation != "run_benchmark":
        errors.append(f"{scenario_id}.{step.step_id}: unsupported engine-benchmark operation")
    errors.extend(_validate_step_output_path(scenario_id, step))
    return errors


def _validate_scenario(scenario: AgentEvaluationScenario, tool_registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not scenario.steps:
        errors.append(f"{scenario.scenario_id}: at least one step is required")
    if not scenario.modes:
        errors.append(f"{scenario.scenario_id}: at least one execution mode is required")
    if not scenario.expected_artifact_kinds:
        errors.append(f"{scenario.scenario_id}: expected_artifact_kinds must not be empty")
    serialized = scenario.model_dump_json().lower()
    if "${env." in serialized or "api_key" in serialized or "https://" in serialized:
        errors.append(f"{scenario.scenario_id}: external secret or network dependency is not allowed")
    for step in scenario.steps:
        errors.extend(_validate_step(scenario.scenario_id, step, tool_registry))
    return errors


def _has_step_tag(corpus: AgentEvaluationCorpus, tag: str) -> bool:
    return any(tag in step.tags for scenario in corpus.scenarios for step in scenario.steps)


def _validate_surface_evaluation_contract(corpus: AgentEvaluationCorpus) -> list[str]:
    from zaptrace.agent.tool_surfaces import SUPPORTED_TOOL_SURFACES
    from zaptrace.security.policy import CAPABILITY_LEVELS

    errors: list[str] = []
    reduced = set(SUPPORTED_TOOL_SURFACES) - {"expert"}
    valid_capabilities = set(CAPABILITY_LEVELS)
    task_surfaces: set[str] = set()
    for scenario in corpus.scenarios:
        unsupported_grants = sorted(set(scenario.granted_capabilities) - valid_capabilities)
        if unsupported_grants:
            errors.append(f"{scenario.scenario_id}: unsupported capability grant(s): {', '.join(unsupported_grants)}")
        if scenario.evaluation_role == AgentEvaluationScenarioRole.LEGACY:
            if scenario.surface:
                errors.append(f"{scenario.scenario_id}: legacy scenario must not declare an MCP surface")
            continue
        if scenario.surface not in reduced:
            errors.append(f"{scenario.scenario_id}: unsupported MCP surface: {scenario.surface!r}")
            continue
        if scenario.evaluation_role == AgentEvaluationScenarioRole.TASK:
            task_surfaces.add(scenario.surface)
        if scenario.evaluation_role == AgentEvaluationScenarioRole.AUTHORIZATION_PROBE and not any(
            step.expect_authorization_denial for step in scenario.steps
        ):
            errors.append(f"{scenario.scenario_id}: authorization-probe must contain at least one expected denial step")
    missing_task_surfaces = sorted(reduced - task_surfaces)
    if missing_task_surfaces:
        errors.append("missing representative task scenario(s) for MCP surface(s): " + ", ".join(missing_task_surfaces))
    return errors


def validate_agent_evaluation_corpus(corpus: AgentEvaluationCorpus) -> list[str]:
    """Return deterministic corpus contract violations."""
    from zaptrace.agent.tool_impls.registry import TOOL_REGISTRY

    errors = [
        *_validate_corpus_header(corpus),
        *_validate_unique_contracts(corpus),
        *_validate_surface_evaluation_contract(corpus),
    ]
    for scenario in corpus.scenarios:
        errors.extend(_validate_scenario(scenario, TOOL_REGISTRY))
    for tag, message in _REQUIRED_STEP_TAGS.items():
        if not _has_step_tag(corpus, tag):
            errors.append(message)
    return errors


def agent_evaluation_corpus_json(corpus: AgentEvaluationCorpus | None = None) -> str:
    """Serialize the corpus as stable JSON."""
    payload = (corpus or DEFAULT_AGENT_EVALUATION_CORPUS).model_dump(mode="json")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _resolve_corpus_path(path: str | Path, *, root: str | Path | None = None) -> Path:
    candidate = Path(path)
    if root is None and candidate == DEFAULT_AGENT_EVALUATION_CORPUS_PATH:
        trusted_root = DEFAULT_AGENT_EVALUATION_CORPUS_PATH.parent.resolve(strict=True)
    else:
        trusted_root = Path(root or Path.cwd()).resolve(strict=True)
    if not candidate.is_absolute():
        candidate = trusted_root / candidate
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(trusted_root)
    except ValueError as exc:
        raise ValueError(f"agent evaluation corpus escapes trusted root: {resolved}") from exc
    if not resolved.is_file() or resolved.suffix.lower() != ".json":
        raise ValueError(f"agent evaluation corpus must be a JSON file: {resolved}")
    return resolved


def load_agent_evaluation_corpus(
    path: str | Path,
    *,
    root: str | Path | None = None,
) -> AgentEvaluationCorpus:
    """Load and validate a corpus file contained by a trusted root."""
    resolved = _resolve_corpus_path(path, root=root)
    corpus = AgentEvaluationCorpus.model_validate_json(resolved.read_text(encoding="utf-8"))
    errors = validate_agent_evaluation_corpus(corpus)
    if errors:
        raise ValueError("invalid agent evaluation corpus: " + "; ".join(errors))
    return corpus


# Parse the packaged fixture without importing the agent registry at module import time.
# Explicit callers and CI use ``load_agent_evaluation_corpus`` for full validation.
DEFAULT_AGENT_EVALUATION_CORPUS = AgentEvaluationCorpus.model_validate_json(
    DEFAULT_AGENT_EVALUATION_CORPUS_PATH.read_text(encoding="utf-8")
)
